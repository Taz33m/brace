"""A product matched to one item in the scan: kept only when its page bears out its price, labelled by rule, and never guessed."""
import json

import pytest
from PIL import Image

from backend import flood, insurer_file, inventory_agent, product_match, schedule


@pytest.fixture(autouse=True)
def _one_product_prices_a_line(monkeypatch):
    """These tests are about the arithmetic and use a single product. The rule that a line needs two is tested in test_match_needs_two.py."""
    from backend import tighten as _t
    monkeypatch.setattr(_t, "MIN_TO_PRICE", 1)

SCAN = {"id": "u1", "name": "2BR", "structure": "A", "model_created_at": "2026-11-10T00:00:00Z",
        "rooms": [{"id": "rk", "type": "Kitchen", "area_sqft": 70.0, "height_m": 2.4384}, {"id": "rc", "type": "Closet", "area_sqft": 20.0, "height_m": 2.4384}],
        "sweeps": [{"id": "s1", "room_id": "rk", "heading": 90.0, "model_position": [0, 0, 0]}, {"id": "s2", "room_id": "rk", "heading": 0.0, "model_position": [1, 0, 0]}]}
PAGES = {
    "https://www.shop.example/fftr1835vs": "Frigidaire 18.3 cu. ft. Top Freezer Refrigerator in Stainless Steel Model # FFTR1835VS $698.00 Add to cart",
    "https://maker.example/gts18": "GE 17.5 cu. ft. top-freezer refrigerator GTS18GSNRSS  $ 749.00",
    "https://shop.example/blocked": None,                                                              # the page could not be read
    "https://shop.example/other-price": "Whirlpool top freezer WRT318FZDM now $829.00",
    "https://shop.example/no-model": "Top freezer refrigerators from $650.00",
}
FRIDGE = {"make": "Frigidaire", "model": "FFTR1835VS", "name": "18.3 cu. ft. Top Freezer Refrigerator", "price": 698.0, "price_text": "$698.00", "url": "https://www.shop.example/fftr1835vs", "why": "stainless, top freezer, bar handles"}
GE = {"make": "GE Appliances", "model": "GTS18GSNRSS", "name": "17.5 cu. ft. Top-Freezer Refrigerator", "price": 749.0, "price_text": "$749.00", "url": "https://maker.example/gts18", "why": "stainless, top freezer"}
BLOCKED = {"make": "LG", "model": "LTCS20020S", "name": "20 cu. ft. Top Freezer", "price": 799.0, "price_text": "$799.00", "url": "https://shop.example/blocked", "why": "stainless, top freezer"}
WRONG_PRICE = {"make": "Whirlpool", "model": "WRT318FZDM", "name": "18 cu. ft. Top Freezer", "price": 699.0, "price_text": "$699.00", "url": "https://shop.example/other-price", "why": "stainless, top freezer"}
WRONG_MODEL = {"make": "Hotpoint", "model": "HPS16BTNRWW", "name": "15.6 cu. ft. Top Freezer", "price": 650.0, "price_text": "$650.00", "url": "https://shop.example/no-model", "why": "top freezer"}
SEEN = {"seen": ["stainless finish", "top freezer", "curved bar handles"], "brand_read": None, "brand_where": None}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """One scanned home whose kitchen holds a refrigerator and three wall cabinets, with cost-guide prices for both."""
    (tmp_path / "b" / "7").mkdir(parents=True)
    (tmp_path / "b" / "7" / "building.json").write_text(json.dumps({"scans": [SCAN], "structures": [{"id": "A", "footprint_sqft": 3000}]}))
    Image.new("RGB", (64, 64), (200, 200, 200)).save(tmp_path / "x.jpg")
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path / "b")
    monkeypatch.setattr(inventory_agent, "OUT", tmp_path / "inv")
    monkeypatch.setattr(inventory_agent.matterport, "face_image", lambda scan, sweep, face: tmp_path / "x.jpg")
    run = inventory_agent.InventoryRun(7, "u1")
    t = run.tools()
    t["look"]("kitchen-1", "p1", "left"); t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "left", 0.8, 0.5, "stainless top-freezer refrigerator")
    t["look"]("kitchen-1", "p2", "ahead"); t["record_item"]("kitchen-1", "wall cabinet", 3, "p2", "ahead", 0.2, 0.3, "white wall cabinets")
    (tmp_path / "inv").mkdir()
    (tmp_path / "inv" / "u1.json").write_text(json.dumps({**run.record("One room read.", {}, {}, "finished"), "seconds": 60.0}))
    src = {"url": "https://example.org/p", "title": "t", "quote": "q"}
    (tmp_path / "prices.json").write_text(json.dumps({"seconds": 120.0, "prices": [{"item": "fit:refrigerator", "price": 675.0, "price_high": 2500.0, "checked": True, "source": src},
                                                                                {"item": "fit:wall cabinet", "price": 100.0, "price_high": 200.0, "checked": True, "source": src},
                                                                                {"item": "flooring", "price": 5.0, "price_high": None, "checked": True, "source": src}]}))
    monkeypatch.setattr(schedule, "PRICES", tmp_path / "prices.json"); monkeypatch.setattr(insurer_file, "PRICES", tmp_path / "none.json")
    monkeypatch.setattr(insurer_file, "inside", lambda pid, sid: {"name": "2BR", "under_roof": "A", "model_made": "2026-11-10", "floor_sqft": 90, "wall_ft": 100, "wall_less_doorways_ft": 90, "inner_doors": 3})
    monkeypatch.setattr(schedule.openings, "layout", lambda scan, walls: {"rooms": [{"id": "rk", "walls": [[[0, 0], [3.048, 0]]]}, {"id": "rc", "walls": []}]})
    monkeypatch.setattr(schedule.matterport, "MP_CACHE", tmp_path)
    (tmp_path / "openings").mkdir(); (tmp_path / "openings" / "u1.json").write_text("[]")
    monkeypatch.setattr(flood, "site", lambda pid: {"name": "Hill Court", "address": "1 Hill Rd", "homes": 10, "bounds": [0, 0, 1, 1], "aerial": {"width": 1, "height": 1},
                                                    "buildings": [{"id": "A", "polygon": [], "trees_within_5ft_percent": 20.0}]})
    monkeypatch.setattr(schedule.portfolio, "floor_plans", lambda pid: [])
    return tmp_path


def model_says(monkeypatch, *calls, stop="end_turn"):
    """Stand in for the model's run: it makes these tool calls in order, and reads pages from PAGES. Returns what each call was told."""
    told: list = []

    def loop(client, system, ask, tools, handle, fetch):
        steps = []
        note = lambda kind, text, **more: steps.append({"t": 0.0, "kind": kind, "text": text, **more})
        assert [b["type"] for b in ask] == ["text", "image", "text", "image", "text", "image", "text"]      # the recorded view, a close-up, the room from the other standpoint, then the ask
        assert [t["name"] for t in tools] == ["web_search", "web_fetch", "note_what_is_visible", "report_product"]
        told.extend(handle(name, dict(args), PAGES.get, note) for name, args in calls)
        return {"made_at": "2026-11-14T00:00:00+00:00", "model": "m", "seconds": 1.0, "stop": stop, "steps": steps, "usage": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(product_match.flood_agent, "_loop", loop)
    return told


def match(**more):
    return product_match.match(7, "u1", "kitchen-1", "refrigerator", client=object(), fetch=lambda url: None, **more)


def test_a_product_is_kept_only_when_its_page_bears_out_the_price_and_the_range_is_the_kept_ones(home, monkeypatch):
    told = model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE), ("report_product", BLOCKED), ("report_product", WRONG_PRICE),
                      ("report_product", WRONG_MODEL), ("report_product", GE))
    e = match()
    assert [c["model"] for c in e["candidates"]] == ["FFTR1835VS", "GTS18GSNRSS"] and (e["low"], e["high"]) == (698.0, 749.0)
    assert [(d["make"], d["why_dropped"]) for d in e["dropped"]] == [("LG", "the page could not be read"), ("Whirlpool", "the price is not on the page"),
                                                                    ("Hotpoint", "the price is on the page but the model number is not")]
    assert told[1] == ("Kept: the price and the model number are on the page.", False) and told[2][0].startswith("Not kept: the page could not be read.")
    assert (e["key"], e["room_id"], e["kind"], e["make"], e["model"], e["name"]) == ("kitchen-1:refrigerator", "kitchen-1", "refrigerator", "Frigidaire", "FFTR1835VS", FRIDGE["name"])
    assert e["candidates"][0] == {"make": "Frigidaire", "model": "FFTR1835VS", "name": FRIDGE["name"], "price": 698.0, "url": FRIDGE["url"], "store": "shop.example", "why": FRIDGE["why"]}
    assert e["label"] == "Closest match" and e["brand_read"] is None and e["seen"] == SEEN["seen"] and e["usage"]["input_tokens"] == 10
    assert "Closest match: Frigidaire FFTR1835VS. 2 products kept at $698 to $749 each" in e["statement"] and "3 more were left out" in e["statement"] and "not an identification" in e["statement"]
    assert set(e) == {"key", "room_id", "kind", "label", "make", "model", "name", "low", "high", "candidates", "seen", "brand_read", "dropped", "stop", "steps", "said", "made_at", "seconds", "usage", "statement"}
    assert product_match.saved("u1") == {"kitchen-1:refrigerator": e}


def test_nothing_confirmed_is_no_match_and_what_was_saved_before_is_left_alone(home, monkeypatch):
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", BLOCKED), ("report_product", WRONG_PRICE))
    e = match()
    assert e["candidates"] == [] and e["label"] is None and e["make"] is None and e["low"] is None and e["high"] is None and len(e["dropped"]) == 2      # unknown is null, never zero
    assert e["statement"] == "No product could be confirmed for the refrigerator in Kitchen: no product's page bore out its price. The line keeps its cost-guide price."
    assert product_match.saved("u1") == {} and product_match.for_schedule(e) is None
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE))
    kept = match()
    model_says(monkeypatch, ("note_what_is_visible", SEEN))
    assert match()["statement"].startswith("No product could be confirmed for the refrigerator in Kitchen: no product was reported.")
    assert product_match.saved("u1") == {"kitchen-1:refrigerator": kept}
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", GE))
    assert match(save=False)["make"] == "GE Appliances" and product_match.saved("u1")["kitchen-1:refrigerator"]["make"] == "Frigidaire"      # a dry run saves nothing


def test_the_gate_is_the_same_check_the_price_research_uses(home, monkeypatch):
    asked = []
    monkeypatch.setattr(product_match.flood_agent, "confirm", lambda row, text: (asked.append((row, text)), (False, "the price is not on the page"))[1])
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE))
    assert match()["candidates"] == []
    row = {"price": 698.0, "price_high": None, "source": {"quote": "$698.00"}}
    assert asked == [(row, PAGES[FRIDGE["url"]]), (row, None)]      # the page as the model's fetch read it, then one fetch from here (which read nothing); the same check both times


def test_a_page_the_models_fetch_could_not_read_gets_one_fetch_from_here_and_the_same_check(home, monkeypatch):
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", BLOCKED), ("report_product", WRONG_PRICE))
    e = product_match.match(7, "u1", "kitchen-1", "refrigerator", client=object(), fetch=lambda url: "LG LTCS20020S top freezer $799.00" if "blocked" in url else "Whirlpool WRT318FZDM $829.00")
    assert [c["make"] for c in e["candidates"]] == ["LG"] and [d["why_dropped"] for d in e["dropped"]] == ["the price is not on the page"]


def test_the_label_says_a_brand_was_read_only_when_the_model_read_one_and_a_kept_product_is_that_brand(home, monkeypatch):
    read = {**SEEN, "brand_read": "GE", "brand_where": "badge at the top of the freezer door"}
    model_says(monkeypatch, ("note_what_is_visible", read), ("report_product", FRIDGE), ("report_product", GE))
    e = match()
    assert e["label"] == "Brand read from the scan" and e["brand_read"] == "GE" and (e["make"], e["model"]) == ("GE Appliances", "GTS18GSNRSS")      # the brand that was read comes first
    assert (e["low"], e["high"]) == (698.0, 749.0) and "not an identification" in e["statement"] and "identified" not in e["statement"] and "exact" not in e["statement"]
    model_says(monkeypatch, ("note_what_is_visible", read), ("report_product", FRIDGE), ("report_product", {**GE, "url": "https://shop.example/blocked"}))
    e = match()
    assert e["label"] == "Closest match" and e["brand_read"] == "GE" and e["make"] == "Frigidaire"      # the GE product's page did not bear it out, so no kept product is the brand that was read
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", GE))
    assert match()["label"] == "Closest match"                                                          # a GE product, but no brand was read in the picture
    assert product_match.same_brand("GE", "GE Appliances") and product_match.same_brand("frigidaire", "Frigidaire") and product_match.same_brand("Frigidaire Gallery", "Frigidaire")
    assert not product_match.same_brand("GE", "Gerber") and not product_match.same_brand(None, "GE") and not product_match.same_brand("", "")


def test_a_product_cannot_be_reported_before_looking_or_without_a_price_and_three_is_enough(home, monkeypatch):
    third = {**FRIDGE, "model": None, "url": "https://shop.example/no-model", "price": 650.0, "price_text": "$650.00"}
    told = model_says(monkeypatch, ("report_product", FRIDGE), ("note_what_is_visible", SEEN), ("report_product", {**FRIDGE, "price": 0}), ("report_product", {**FRIDGE, "url": "ftp://x"}),
                      ("report_product", FRIDGE), ("report_product", FRIDGE), ("report_product", GE), ("report_product", third), ("report_product", WRONG_PRICE))
    e = match()
    assert told[0] == ("Not taken: call note_what_is_visible first, with what you can see in the pictures.", True) and told[2][1] and told[3][1]
    assert told[5] == ("Not taken: that page is already kept. Report a different product.", True) and told[7] == ("Kept: the price is on the page.", False)
    assert told[8] == ("Not taken: 3 products are already kept. Stop here.", True)
    assert len(e["candidates"]) == 3 and e["candidates"][2]["model"] is None and (e["low"], e["high"]) == (650.0, 749.0) and e["dropped"] == []


def test_there_must_be_such_an_item_and_a_picture_of_it(home, monkeypatch):
    model_says(monkeypatch)
    for room, kind, why in (("kitchen-1", "dishwasher", "no dishwasher is recorded in that room"), ("kitchen-1", "sofa", "'sofa' is not a kind of fit-out the inventory records"),
                            ("bedroom-9", "refrigerator", "no refrigerator is recorded in that room")):
        with pytest.raises(ValueError, match=why):
            product_match.match(7, "u1", room, kind, client=object())
    with pytest.raises(ValueError, match="has not been read yet"):
        product_match.match(7, "nope", "kitchen-1", "refrigerator", client=object())
    shown = product_match.pictures(7, "u1", "kitchen-1", "refrigerator")
    assert (shown["across"], shown["down"]) == (0.8, 0.5) and len(shown["shots"]) == 3                 # where the reader said it was, got back from the turn and tilt that were saved
    assert product_match.view_jpeg(7, "u1", "kitchen-1", "refrigerator")[:3] == b"\xff\xd8\xff"
    monkeypatch.setattr(product_match.matterport, "face_image", lambda *a: (_ for _ in ()).throw(product_match.matterport.MatterportError("gone")))
    with pytest.raises(ValueError, match="could not be fetched"):
        product_match.view_jpeg(7, "u1", "kitchen-1", "refrigerator")


def test_a_matched_line_takes_the_products_price_keeps_the_guides_and_the_totals_still_add_up(home, monkeypatch):
    before = schedule.schedule(7)
    kitchen = before["buildings"][0]["units"][0]["rooms"][0]
    fridge, cabinets, floor = kitchen["items"][0], kitchen["items"][1], kitchen["items"][2]
    assert (fridge["key"], fridge["match"], fridge["guide_low"], fridge["guide_high"], fridge["low"], fridge["high"]) == ("kitchen-1:refrigerator", None, 675.0, 2500.0, 675, 2500)
    assert (cabinets["key"], cabinets["low"], cabinets["high"]) == ("kitchen-1:wall cabinet", 300, 600) and (floor["key"], floor["match"], floor["guide_low"]) == (None, None, 5.0)
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE), ("report_product", GE))
    entry = match()
    after = schedule.schedule(7)
    unit = after["buildings"][0]["units"][0]
    fridge, cabinets = unit["rooms"][0]["items"][0], unit["rooms"][0]["items"][1]
    assert (fridge["price_low"], fridge["price_high"], fridge["low"], fridge["high"], fridge["guide_low"], fridge["guide_high"]) == (698.0, 749.0, 698, 749, 675.0, 2500.0)
    assert fridge["match"] == {k: v for k, v in entry.items() if k not in ("usage", "statement", "steps", "said")} and fridge["match"]["label"] == "Closest match"
    assert cabinets["match"] is None and (cabinets["low"], cabinets["high"]) == (300, 600)
    every = [l for r in unit["rooms"] for l in r["items"]]
    assert after["home"]["total"]["low"] == sum(l["low"] for l in every if l["low"] is not None) == before["home"]["total"]["low"] + 698 - 675
    assert after["home"]["total"]["high"] == sum(l["high"] for l in every if l["high"] is not None) == before["home"]["total"]["high"] + 749 - 2500
    assert unit["rooms"][0]["total"]["high"] == sum(l["high"] for l in unit["rooms"][0]["items"] if l["high"] is not None)
    assert after["total"]["low"] == after["home"]["total"]["low"] * 10 and after["home"]["total"]["lines_priced"] == before["home"]["total"]["lines_priced"]
    assert any("matched" in a and "leaves out delivery and fitting" in a for a in after["assumptions"])
    # A match is for one; a line of three takes three times it.
    saved = product_match.saved("u1")
    saved["kitchen-1:wall cabinet"] = {**entry, "key": "kitchen-1:wall cabinet", "kind": "wall cabinet", "low": 150.0, "high": 180.0}
    (home / "inv" / "u1.matches.json").write_text(json.dumps(saved))
    cabinets = schedule.schedule(7)["buildings"][0]["units"][0]["rooms"][0]["items"][1]
    assert (cabinets["price_low"], cabinets["low"], cabinets["high"], cabinets["guide_high"]) == (150.0, 450, 540, 200.0)


def test_the_voice_can_ask_for_a_model_and_is_told_what_is_already_matched(home, monkeypatch):
    from backend import voice
    assert "No line has a product matched to it yet." in voice.schedule_instructions(schedule.schedule(7))
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE), ("report_product", GE))
    match()
    told = voice.schedule_instructions(schedule.schedule(7))
    assert "call find_model" in told and "not an identification" in told and "Kitchen, Refrigerator: closest is Frigidaire FFTR1835VS; 2 lookalike products at 698 to 749 dollars each; the line is 698 to 749 dollars each (products only, fitting not priced; closest match, no brand read)" in told
    tool = next(t for t in voice.schedule_tools() if t["name"] == "find_model")
    assert tool["parameters"]["required"] == ["room", "item"] and "Takes about a minute" in tool["description"]


def test_the_endpoints_find_the_line_by_room_and_item_and_say_plainly_when_it_is_not_there(home, monkeypatch):
    from fastapi.testclient import TestClient
    from backend import server
    c = TestClient(server.app)
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", FRIDGE), ("report_product", BLOCKED))
    for url, why in (("/api/schedule/7/match?room=Garage&item=Refrigerator", "that room is not one the camera stood in"),
                     ("/api/schedule/7/match?room=Closet&item=Flooring", "that room is not one the camera stood in"),
                     ("/api/schedule/7/match?room=Kitchen&item=Dishwasher", "no such item was read from the scan in that room"),
                     ("/api/schedule/7/match?room=Kitchen&item=Flooring", "no such item was read from the scan in that room")):      # measured building work has no product
        r = c.post(url)
        assert r.status_code == 404 and r.json()["detail"] == why
    assert c.get("/api/schedule/7/view.jpg?room=Kitchen&item=Dishwasher").status_code == 404 and c.get("/api/schedule/7/view.jpg?room=Hall&item=Refrigerator").status_code == 404
    seen = c.get("/api/schedule/7/view.jpg?room=kitchen-1&item=refrigerator")
    assert seen.status_code == 200 and seen.headers["content-type"] == "image/jpeg" and seen.content[:3] == b"\xff\xd8\xff"
    monkeypatch.setattr("anthropic.Anthropic", lambda *a, **k: object())
    got = c.post("/api/schedule/7/match?room=Kitchen&item=Refrigerator").json()
    assert got["ok"] is True and got["key"] == "kitchen-1:refrigerator" and got["match"]["model"] == "FFTR1835VS" and "usage" not in got["match"] and got["seconds"] is not None
    assert got["statement"].startswith("Closest match: Frigidaire FFTR1835VS. 1 product kept at $698 each") and "1 more was left out" in got["statement"]
    assert got["home_after"]["high"] == got["home_before"]["high"] + 698 - 2500
    model_says(monkeypatch, ("note_what_is_visible", SEEN), ("report_product", BLOCKED))
    none = c.post("/api/schedule/7/match?room=kitchen-1&item=wall cabinet").json()
    assert none["ok"] is True and none["key"] == "kitchen-1:wall cabinet" and none["match"] is None and "keeps its cost-guide price" in none["statement"]
