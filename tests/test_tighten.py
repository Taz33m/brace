"""Tighter prices: fitting added to a matched product, built work priced as it was seen, building work priced for the finish read from the scan.
Each is used only when its page confirmed it, and no range is ever narrowed by arithmetic."""
import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from backend import flood, insurer_file, inventory_agent, schedule, tighten


@pytest.fixture(autouse=True)
def _one_product_prices_a_line(monkeypatch):
    """These tests are about the arithmetic and use a single product. The rule that a line needs two is tested in test_match_needs_two.py."""
    from backend import tighten as _t
    monkeypatch.setattr(_t, "MIN_TO_PRICE", 1)

SCAN = {"id": "u1", "name": "1BR", "structure": "A", "model_created_at": "2026-11-10T00:00:00Z",
        "rooms": [{"id": "rk", "type": "Kitchen", "area_sqft": 70.0, "height_m": 2.4384}, {"id": "rb", "type": "Bathroom", "area_sqft": 40.0, "height_m": 2.4384},
                  {"id": "rc", "type": "Closet", "area_sqft": 20.0, "height_m": 2.4384}],
        "sweeps": [{"id": "s1", "room_id": "rk", "heading": 90.0}, {"id": "s2", "room_id": "rk", "heading": 0.0}, {"id": "s3", "room_id": "rb", "heading": 0.0}]}
TUB, COUNTER = "white tub with tiled surround and handheld shower", "grey speckled quartz countertop with backsplash"
GUIDE = {"fit:refrigerator": (675.0, 2500.0), "fit:toilet": (350.0, 800.0), "fit:wall cabinet": (100.0, 200.0), "fit:base cabinet": (300.0, 400.0), "fit:kitchen countertop": (600.0, 3200.0),
         "fit:bathtub or shower": (1500.0, 8000.0), "flooring": (5.0, None), "drywall": (2.0, 3.0), "paint": (1.0, 2.0), "baseboard": (6.0, 9.0), "door": (226.0, 824.0)}
PAGES = {
    "https://guide.example/fridge": "Refrigerator delivery and hook-up costs $100 to $250 for labor alone, on top of the appliance.",
    "https://guide.example/toilet": "A plumber charges $150 to $400 for labor alone to install a toilet.",
    "https://guide.example/cabinet": "Labor to hang one wall cabinet runs $80 to $120 per cabinet.",
    "https://guide.example/tub": "A bathtub with a tiled surround costs $2,000 to $12,000 installed.",
    "https://guide.example/quartz": "Quartz countertops with a backsplash cost $1,500 to $3,000 installed for a small kitchen.",
    "https://guide.example/carpet": "Carpet installation costs $2 to $4 per square foot with pad.",
    "https://la.example/carpet": "In Los Angeles, carpet with pad runs $3 to $7 per square foot installed.",
    "https://guide.example/door": "A flush interior door costs $150 to $400 installed.",
    "https://guide.example/paint": "Painting smooth interior walls costs $1.50 to $2.50 per square foot.",
    "https://guide.example/blocked": None,
}


def said(item, low, high, url, quote=None, place="United States"):
    return {"item": item, "price": low, "price_high": high, "place": place, "source_title": "A cost guide", "source_url": url, "quote": quote or PAGES[url]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """One scanned home: a kitchen with a refrigerator, a quartz countertop, built-in wall cabinets and a stock base cabinet; a bathroom with a toilet and a tiled tub; a closet nobody stood in."""
    (tmp_path / "b" / "7").mkdir(parents=True)
    (tmp_path / "b" / "7" / "building.json").write_text(json.dumps({"scans": [SCAN], "structures": [{"id": "A", "footprint_sqft": 3000}]}))
    Image.new("RGB", (64, 64), (200, 200, 200)).save(tmp_path / "x.jpg")
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path / "b")
    monkeypatch.setattr(inventory_agent, "OUT", tmp_path / "inv")
    monkeypatch.setattr(inventory_agent.matterport, "face_image", lambda scan, sweep, face: tmp_path / "x.jpg")
    run = inventory_agent.InventoryRun(7, "u1")
    t = run.tools()
    t["look"]("kitchen-1", "p1", "left"); t["look"]("bathroom-1", "p1", "ahead")
    for room, kind, n, seen in (("kitchen-1", "refrigerator", 1, "stainless top-freezer refrigerator"), ("kitchen-1", "kitchen countertop", 1, COUNTER),
                                ("kitchen-1", "wall cabinet", 2, "white built-in upper cabinets, two boxes"), ("kitchen-1", "base cabinet", 1, "white two-door sink base cabinet"),
                                ("bathroom-1", "toilet", 1, "white toilet"), ("bathroom-1", "bathtub or shower", 1, TUB)):
        t["record_item"](room, kind, n, "p1", "left" if room == "kitchen-1" else "ahead", 0.5, 0.5, seen)
    (tmp_path / "inv").mkdir()
    (tmp_path / "inv" / "u1.json").write_text(json.dumps({**run.record("Two rooms read.", {}, {}, "finished"), "seconds": 60.0}))
    src = {"url": "https://example.org/p", "title": "t", "quote": "q"}
    (tmp_path / "prices.json").write_text(json.dumps({"seconds": 120.0, "prices": [{"item": k, "price": low, "price_high": high, "checked": True, "source": src} for k, (low, high) in GUIDE.items()]}))
    monkeypatch.setattr(schedule, "PRICES", tmp_path / "prices.json"); monkeypatch.setattr(insurer_file, "PRICES", tmp_path / "none.json")
    monkeypatch.setattr(insurer_file, "inside", lambda pid, sid: {"name": "1BR", "under_roof": "A", "model_made": "2026-11-10", "floor_sqft": 130, "wall_ft": 100, "wall_less_doorways_ft": 90, "inner_doors": 3})
    monkeypatch.setattr(schedule.openings, "layout", lambda scan, walls: {"rooms": [{"id": "rk", "walls": [[[0, 0], [3.048, 0]]]}, {"id": "rb", "walls": [[[0, 0], [6.096, 0]]]}, {"id": "rc", "walls": []}]})
    monkeypatch.setattr(schedule.matterport, "MP_CACHE", tmp_path)
    (tmp_path / "openings").mkdir(); (tmp_path / "openings" / "u1.json").write_text("[]")
    monkeypatch.setattr(flood, "site", lambda pid: {"name": "Hill Court", "address": "1 Hill Rd", "homes": 10, "bounds": [0, 0, 1, 1], "aerial": {"width": 1, "height": 1},
                                                    "buildings": [{"id": "A", "polygon": [], "trees_within_5ft_percent": 20.0}]})
    monkeypatch.setattr(schedule.portfolio, "floor_plans", lambda pid: [])
    return tmp_path


def model_says(monkeypatch, *calls):
    """Stand in for the research run: it records these prices in order, and reads pages from PAGES. Returns what each record was told, and what the run was asked."""
    told, asked = [], []

    def loop(client, system, ask, tools, handle, fetch):
        steps = []
        note = lambda kind, text, **more: steps.append({"t": 0.0, "kind": kind, "text": text, **more})
        assert [t["name"] for t in tools] == ["web_search", "web_fetch", "record_price"]
        asked.append({"system": system, "ask": ask, "ids": tools[2]["input_schema"]["properties"]["item"]["enum"]})
        told.extend(handle("record_price", dict(args), PAGES.get, note) for args in calls)
        return {"made_at": "2026-11-14T00:00:00+00:00", "model": "m", "seconds": 1.0, "stop": "end_turn", "steps": steps, "usage": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(tighten.flood_agent, "_loop", loop)
    return told, asked


def how():
    return {"client": object(), "fetch": lambda url: None}


def matched(home, **entries):
    """Save matches as the product matcher does: a range of listed prices under '<room_id>:<kind>'."""
    (home / "inv" / "u1.matches.json").write_text(json.dumps({k: {"key": k, "low": low, "high": high, "label": "Closest match", "candidates": [{"make": "M", "price": low, "url": "https://shop.example/x"}]}
                                                              for k, (low, high) in entries.items()}))


def lines(s=None):
    s = s or schedule.schedule(7)
    return {(room["name"], l["what"]): l for room in s["buildings"][0]["units"][0]["rooms"] for l in room["items"]}


def adds_up(s):
    unit = s["buildings"][0]["units"][0]
    every = [l for room in unit["rooms"] for l in room["items"]]
    assert all(room["total"]["low"] == sum(l["low"] for l in room["items"] if l["low"] is not None) and room["total"]["high"] == sum(l["high"] for l in room["items"] if l["high"] is not None) for room in unit["rooms"])
    assert s["home"]["total"]["low"] == sum(l["low"] for l in every if l["low"] is not None) and s["home"]["total"]["high"] == sum(l["high"] for l in every if l["high"] is not None)
    assert all(l["low"] == round(l["quantity"] * l["price_low"]) and l["high"] == round(l["quantity"] * l["price_high"]) for l in every if l["low"] is not None)
    assert s["total"]["low"] == s["home"]["total"]["low"] * 10 and s["total"]["high"] == s["home"]["total"]["high"] * 10
    return s["home"]["total"]


# ---- A: fitting --------------------------------------------------------------------------------------

def test_fitting_is_asked_for_products_only_and_a_price_is_kept_as_confirmed_only_when_its_page_holds_it(home, monkeypatch):
    items = tighten.fitting_items(["toilet"])
    assert items[0]["id"] == "fitting:toilet" and len(items) == len(inventory_agent.KINDS) - 2 and all(i["unit"] == "each" and "abour only" in i["what"] for i in items)      # the kinds in a scan come first
    assert not {"fitting:bathtub or shower", "fitting:kitchen countertop"} & {i["id"] for i in items}                                  # built work is not a product somebody fits
    assert next(i for i in items if i["id"] == "fitting:refrigerator")["what"].startswith("Delivery and hook-up of one refrigerator")
    told, asked = model_says(monkeypatch, said("fitting:refrigerator", 100, 250, "https://guide.example/fridge"), said("fitting:toilet", 150, 400, "https://guide.example/blocked", "x costs $150 to $400"),
                             said("fitting:sofa", 50, None, "https://guide.example/fridge"), said("fitting:range", 0, None, "https://guide.example/fridge"),
                             said("fitting:dishwasher", 100, 900, "https://guide.example/fridge"))
    run = tighten.price_fitting(**how())
    assert told[0] == ("Recorded. Check of the page: the price and the sentence are on the page.", False) and told[1][0].startswith("Recorded, but not confirmed and so not used: the page could not be read.")
    assert told[2] == ("Not recorded: the item must be one on the list and the price a number.", True) and told[3][1] is True and "the price is not on the page" in told[4][0]      # both ends of a range must be there
    assert [(r["item"], r["checked"]) for r in run["prices"]] == [("fitting:refrigerator", True), ("fitting:toilet", False), ("fitting:dishwasher", False)]
    assert "labour only, for ONE" in asked[0]["system"] and "Do not narrow a range" in asked[0]["system"] and len(asked[0]["ids"]) == 21
    saved = json.loads(tighten.fitting_path().read_text())
    assert set(saved["prices"][0]) == {"item", "price", "price_high", "unit", "what", "source", "checked", "check_note", "place"} and set(saved["prices"][0]["source"]) == {"title", "url", "quote"}      # the price files' row
    assert list(tighten.confirmed(tighten.fitting_path())) == ["fitting:refrigerator"]
    # Running it again is the retry: only what has no confirmed price is asked for, and what was confirmed is left as it was.
    told, asked = model_says(monkeypatch, said("fitting:toilet", 150, 400, "https://guide.example/toilet"))
    tighten.price_fitting(**how())
    assert "fitting:refrigerator" not in asked[0]["ids"] and "fitting:toilet" in asked[0]["ids"] and len(asked[0]["ids"]) == 20
    again = json.loads(tighten.fitting_path().read_text())
    assert again["prices"][0] == saved["prices"][0] and [r["checked"] for r in again["prices"]] == [True, False, False, True] and again["runs"] == 2
    assert {k: (r["price"], r["price_high"]) for k, r in tighten.confirmed(tighten.fitting_path()).items()} == {"fitting:refrigerator": (100.0, 250.0), "fitting:toilet": (150.0, 400.0)}
    model_says(monkeypatch)
    assert tighten.research([i for i in items if i["id"] in ("fitting:refrigerator", "fitting:toilet")], tighten.fitting_path(), "x", **how())["stop"] == "nothing to price"


def test_a_matched_line_is_the_product_plus_its_fitting_and_says_which_basis_it_rests_on(home, monkeypatch):
    before = adds_up(schedule.schedule(7))
    matched(home, **{"kitchen-1:refrigerator": (698.0, 749.0), "bathroom-1:toilet": (199.0, 229.0)})
    bare = lines()
    assert (bare["Kitchen", "Refrigerator"]["price_low"], bare["Kitchen", "Refrigerator"]["price_high"], bare["Kitchen", "Refrigerator"]["price_basis"]) == (698.0, 749.0, "matched product, fitting not priced")
    model_says(monkeypatch, said("fitting:refrigerator", 100, 250, "https://guide.example/fridge"), said("fitting:toilet", 150, 400, "https://guide.example/blocked", "x costs $150 to $400"),
               said("fitting:wall cabinet", 80, 120, "https://guide.example/cabinet"))
    tighten.price_fitting(**how())
    s = schedule.schedule(7)
    got = lines(s)
    fridge, toilet, cabinets = got["Kitchen", "Refrigerator"], got["Bathroom", "Toilet"], got["Kitchen", "Wall cabinet"]
    assert (fridge["price_low"], fridge["price_high"], fridge["low"], fridge["high"]) == (798.0, 999.0, 798, 999)                       # low with low, high with high, and nothing else
    assert (fridge["fitting_low"], fridge["fitting_high"], fridge["fitting_url"], fridge["price_basis"]) == (100.0, 250.0, "https://guide.example/fridge", "matched product plus fitting")
    assert (fridge["guide_low"], fridge["guide_high"], fridge["match"]["low"]) == (675.0, 2500.0, 698.0)                                 # the guide's range and the product's are both still there
    assert (toilet["price_low"], toilet["price_high"], toilet["price_basis"]) == (199.0, 229.0, "matched product, fitting not priced")   # its fitting price was not confirmed, so it is not used
    assert (toilet["fitting_low"], toilet["fitting_high"], toilet["fitting_url"]) == (None, None, None)
    assert (cabinets["price_low"], cabinets["price_high"], cabinets["price_basis"], cabinets["fitting_low"]) == (100.0, 200.0, "cost guide, supplied and installed", None)      # no product matched: the guide already includes fitting
    after = adds_up(s)
    assert after["low"] == before["low"] + (798 - 675) + (199 - 350) and after["high"] == before["high"] + (999 - 2500) + (229 - 800) and after["lines_priced"] == before["lines_priced"]
    assert any("matched" in a and "plus a page's labour-only price to fit one" in a and "leaves out delivery and fitting" in a for a in s["assumptions"])
    with tighten.set_aside():                                                                                                            # the schedule as it was, for a before and after
        assert lines()["Kitchen", "Refrigerator"]["price_basis"] == "matched product, fitting not priced"


# ---- B: built work, priced as it was seen ------------------------------------------------------------

def test_built_work_is_priced_for_what_the_reader_described_and_only_from_a_page_that_confirms_it(home, monkeypatch):
    items = tighten.built_items("u1")
    assert [i["id"] for i in items] == ["kitchen-1:kitchen countertop", "kitchen-1:wall cabinet", "bathroom-1:bathtub or shower"]      # a cabinet only when the reader called it built-in
    assert f'"{TUB}"' in items[2]["what"] and items[2]["seen"] == TUB and "There are 2 in the room: the price of one." in items[1]["what"] and "The kitchen is 70 sq ft of floor." in items[0]["what"]
    told, asked = model_says(monkeypatch, said("bathroom-1:bathtub or shower", 2000, 12000, "https://guide.example/tub"),
                             said("kitchen-1:kitchen countertop", 1500, 3000, "https://guide.example/quartz"), said("kitchen-1:wall cabinet", 900, 1400, "https://guide.example/cabinet", "Built-in cabinets cost $900 to $1,400 each."))
    before = adds_up(schedule.schedule(7))
    run = tighten.price_specific("u1", **how())
    assert [r["checked"] for r in run["prices"]] == [True, True, False] and "the price is not on the page" in told[2][0] and "its material and its form as described" in asked[0]["system"]
    saved = json.loads(tighten.specific_path("u1").read_text())
    assert set(saved) == {"bathroom-1:bathtub or shower", "kitchen-1:kitchen countertop", "kitchen-1:wall cabinet", "runs"} and saved["bathroom-1:bathtub or shower"]["seen"] == TUB
    s = schedule.schedule(7)
    got = lines(s)
    tub, counter, cabinets = got["Bathroom", "Bathtub or shower"], got["Kitchen", "Kitchen countertop, one run"], got["Kitchen", "Wall cabinet"]
    assert (tub["price_low"], tub["price_high"], tub["price_basis"], tub["source_url"]) == (2000.0, 12000.0, "cost guide for what was seen", "https://guide.example/tub")      # wider than the guide's, and still used: it is for this tub
    assert (tub["guide_low"], tub["guide_high"]) == (1500.0, 8000.0) and (counter["price_low"], counter["price_high"], counter["guide_high"]) == (1500.0, 3000.0, 3200.0)
    assert (cabinets["price_low"], cabinets["price_high"], cabinets["price_basis"], cabinets["source_url"]) == (100.0, 200.0, "cost guide, supplied and installed", "https://example.org/p")      # not confirmed: it keeps the price it had
    after = adds_up(s)
    assert after["low"] == before["low"] + (2000 - 1500) + (1500 - 600) and after["high"] == before["high"] + (12000 - 8000) + (3000 - 3200)
    # A reviewer can set a confirmed price aside, with a reason that stays in the file. The line goes back to the price it had. An unconfirmed row has nothing to set aside.
    assert tighten.set_row_aside(tighten.specific_path("u1"), "kitchen-1:wall cabinet", "x") == 0 and tighten.set_row_aside(tighten.specific_path("u1"), "kitchen-1:kitchen countertop", "the page's small kitchen is  twice this one") == 1
    counter = lines()["Kitchen", "Kitchen countertop, one run"]
    assert (counter["price_low"], counter["price_high"], counter["price_basis"]) == (600.0, 3200.0, "cost guide, supplied and installed")
    assert json.loads(tighten.specific_path("u1").read_text())["kitchen-1:kitchen countertop"]["set_aside"] == "the page's small kitchen is twice this one"
    with pytest.raises(ValueError, match="say why"):
        tighten.set_row_aside(tighten.specific_path("u1"), "bathroom-1:bathtub or shower", " ")
    # A matched product wins over a price for what was seen.
    matched(home, **{"kitchen-1:kitchen countertop": (450.0, 500.0)})
    counter = lines()["Kitchen", "Kitchen countertop, one run"]
    assert (counter["price_low"], counter["price_high"], counter["price_basis"]) == (450.0, 500.0, "matched product, fitting not priced")
    # The price belongs to the words. When the room is read again and the reader says something else, it no longer applies.
    inv = json.loads((home / "inv" / "u1.json").read_text())
    next(i for i in inv["items"] if i["kind"] == "bathtub or shower")["seen"] = "fibreglass shower stall"
    (home / "inv" / "u1.json").write_text(json.dumps(inv))
    tub = lines()["Bathroom", "Bathtub or shower"]
    assert (tub["price_low"], tub["price_high"], tub["price_basis"]) == (1500.0, 8000.0, "cost guide, supplied and installed")
    told, asked = model_says(monkeypatch)
    tighten.price_specific("u1", **how())
    assert asked[0]["ids"] == ["kitchen-1:wall cabinet", "bathroom-1:bathtub or shower"]                                                 # the tub is asked for again; the countertop, set aside for these words, is not


# ---- C: the finishes ---------------------------------------------------------------------------------

class Looker:
    """Stands in for the API on the one look at the scan."""
    def __init__(self, answer, stop="end_turn"):
        self.answer, self.stop, self.sent = answer, stop, []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.sent.append(kw)
        return NS(stop_reason=self.stop, usage=NS(input_tokens=900, output_tokens=80), content=[NS(type="thinking", thinking=""), NS(type="text", text=self.answer if isinstance(self.answer, str) else json.dumps(self.answer))])


ANSWER = {"rooms": [{"room": "kitchen-1", "finish": "vinyl plank", "seen": "grey wood-look planks,  tight seams"}, {"room": "kitchen-1", "finish": "carpet", "seen": "said twice"},
                    {"room": "bathroom-1", "finish": "marble", "seen": "veined stone"}, {"room": "closet-1", "finish": "carpet", "seen": "beige loop pile"}],
          "door": {"finish": "flush", "seen": "flat white slab doors"}, "wall": {"finish": "smooth painted", "seen": " "}, "baseboard": {"finish": "cannot tell", "seen": "hidden behind furniture"}}


def test_one_look_reads_the_finishes_held_to_a_schema_and_checked_again_in_code(home):
    client = Looker(ANSWER)
    f = tighten.read_finishes(7, "u1", client=client)
    sent = client.sent[0]
    assert len(client.sent) == 1 and [b["type"] for b in sent["messages"][0]["content"]] == ["text", "image", "text", "image", "text"]      # one call; one picture for each room the camera stood in
    schema = sent["output_config"]["format"]["schema"]
    assert sent["output_config"]["format"]["type"] == "json_schema" and schema["properties"]["rooms"]["items"]["properties"]["room"]["enum"] == ["kitchen-1", "bathroom-1"]
    assert schema["properties"]["rooms"]["items"]["properties"]["finish"]["enum"] == [*tighten.FLOORS, "cannot tell"] and schema["properties"]["door"]["properties"]["finish"]["enum"][-1] == "cannot tell"
    assert f["rooms"] == {"kitchen-1": {"finish": "vinyl plank", "seen": "grey wood-look planks, tight seams"}}                           # said once; a finish off the list and a room not pictured are dropped
    assert f["home"] == {"door": {"finish": "flush", "seen": "flat white slab doors"}, "wall": None, "baseboard": {"finish": "cannot tell", "seen": "hidden behind furniture"}}      # no phrase of what was seen, no finish
    assert tighten.saved_finishes("u1")["rooms"] == f["rooms"] and [p["room"] for p in f["pictures"]] == ["kitchen-1", "bathroom-1"] and f["usage"] == {"input_tokens": 900, "output_tokens": 80}
    fin = tighten.saved_finishes("u1")
    assert tighten.finish_of(fin, "flooring", "kitchen-1") == "vinyl plank" and tighten.finish_of(fin, "flooring", "bathroom-1") is None and tighten.finish_of(fin, "door") == "flush"
    assert tighten.finish_of(fin, "baseboard") is None and tighten.finish_of(fin, "drywall") is None and tighten.finish_of(fin, "paint") is None      # cannot tell, and no answer, price nothing
    assert [i["id"] for i in tighten.work_items("u1")] == ["flooring:vinyl plank", "door:flush"]
    # A look that was declined, or did not answer in the form asked for, saves nothing and leaves what was saved.
    assert tighten.read_finishes(7, "u1", client=Looker(ANSWER, stop="refusal"))["rooms"] == {} and tighten.read_finishes(7, "u1", client=Looker("not json"))["stop"].startswith("error")
    assert tighten.saved_finishes("u1")["rooms"] == f["rooms"]
    with pytest.raises(ValueError, match="have not been read yet"):
        tighten.work_items("nope")


def test_building_work_is_priced_for_the_finish_that_was_read_and_keeps_its_price_when_none_is_confirmed(home, monkeypatch):
    before = adds_up(schedule.schedule(7))
    tighten.finishes_path("u1").write_text(json.dumps({"rooms": {"kitchen-1": {"finish": "carpet", "seen": "beige cut pile"}, "bathroom-1": {"finish": "ceramic or porcelain tile", "seen": "square tiles, grey grout"}},
                                                       "home": {"door": {"finish": "flush", "seen": "flat slabs"}, "wall": {"finish": "smooth painted", "seen": "flat white walls"}, "baseboard": {"finish": "cannot tell", "seen": "x"}}}))
    assert [i["id"] for i in tighten.work_items("u1")] == ["flooring:carpet", "flooring:ceramic or porcelain tile", "door:flush", "drywall:smooth painted", "paint:smooth painted"]      # nothing for a baseboard nobody could see
    told, asked = model_says(monkeypatch, said("flooring:carpet", 2, 4, "https://guide.example/carpet"), said("flooring:carpet", 3, 7, "https://la.example/carpet", place="Los Angeles"),
                             said("door:flush", 150, 400, "https://guide.example/door", place="California"), said("drywall:smooth painted", 1.5, 2.5, "https://guide.example/paint"),
                             said("paint:smooth painted", 1.5, 2, "https://guide.example/paint"))
    run = tighten.price_work("u1", **how())
    assert [(r["checked"], r["place"]) for r in run["prices"]] == [(True, None), (True, "Los Angeles"), (True, None), (True, None), (False, None)]      # a place is kept only when the page names it
    assert told[4][0].startswith("Recorded, but not confirmed and so not used: the sentence is on the page but does not itself state this price")      # $2 is not what a page that says $2.50 states
    assert "Los Angeles or for California" in asked[0]["system"] and "in an apartment refit" in asked[0]["system"]
    use = tighten.confirmed(tighten.work_path())
    assert (use["flooring:carpet"]["price"], use["flooring:carpet"]["price_high"]) == (3.0, 7.0)                                         # the local figure is used though it is the wider one: place decides, never width
    s = schedule.schedule(7)
    got = lines(s)
    floor = got["Kitchen", "Flooring"]
    assert (floor["price_low"], floor["price_high"], floor["finish"], floor["price_basis"], floor["source_url"]) == (3.0, 7.0, "carpet, read from the scan", "cost guide for what was seen", "https://la.example/carpet")
    assert (floor["guide_low"], floor["guide_high"], floor["low"], floor["high"]) == (5.0, 5.0, 210, 490)
    tiled = got["Bathroom", "Flooring"]                                                                                                  # read, but no page confirmed a price for it
    assert (tiled["price_low"], tiled["price_high"], tiled["finish"], tiled["price_basis"]) == (5.0, 5.0, "ceramic or porcelain tile, read from the scan", "cost guide, supplied and installed")
    assert (got["Closet", "Flooring"]["finish"], got["Closet", "Flooring"]["price_low"], got["Closet", "Flooring"]["price_basis"]) == (None, 5.0, "cost guide, supplied and installed")      # nobody stood in it
    doors, drywall, paint, base = got["Throughout the home", "Interior doors"], got["Kitchen", "Drywall"], got["Kitchen", "Painting"], got["Kitchen", "Baseboard"]
    assert (doors["price_low"], doors["price_high"], doors["low"], doors["high"], doors["finish"], doors["price_basis"]) == (150.0, 400.0, 450, 1200, "flush, read from the scan", "cost guide for what was seen")
    assert (drywall["price_low"], drywall["price_high"], drywall["finish"], drywall["guide_low"]) == (1.5, 2.5, "smooth painted, read from the scan", 2.0)
    assert (paint["price_low"], paint["price_high"], paint["finish"], paint["price_basis"]) == (1.0, 2.0, "smooth painted, read from the scan", "cost guide, supplied and installed")      # its range was not on the page
    assert (base["price_low"], base["finish"], base["price_basis"]) == (6.0, None, "cost guide, supplied and installed") and got["Kitchen", "Refrigerator"]["finish"] is None
    after = adds_up(s)
    assert after["low"] == before["low"] + 70 * (3 - 5) + 3 * (150 - 226) + round(72 * 1.5) - 72 * 2 + round(144 * 1.5) - 144 * 2
    with tighten.set_aside():
        assert adds_up(schedule.schedule(7)) == before
    saved = {r["item"]: r for r in json.loads(tighten.work_path().read_text())["prices"]}
    assert saved["door:flush"]["seen"] == "flat slabs" and "seen" not in saved["flooring:carpet"] and 'with its frame (pre-hung), supplied and installed. In a scan of the home: "flat slabs"' in saved["door:flush"]["what"]
    # A price for the doors is for the words the look used of them. If the look is run again and says something else, the price is dropped and asked for again.
    fin = json.loads(tighten.finishes_path("u1").read_text())
    fin["home"]["door"]["seen"] = "flat slabs, two with vents"
    tighten.finishes_path("u1").write_text(json.dumps(fin))
    doors = lines()["Throughout the home", "Interior doors"]
    assert (doors["price_low"], doors["price_high"], doors["finish"], doors["price_basis"]) == (226.0, 824.0, "flush, read from the scan", "cost guide, supplied and installed")
    # A reviewer sets the carpet price aside: both rows, and it is not asked for again.
    assert tighten.set_row_aside(tighten.work_path(), "flooring:carpet", "the page is about stair runners") == 2 and tighten.set_row_aside(tighten.work_path(), "paint:smooth painted", "x") == 0
    assert (lines()["Kitchen", "Flooring"]["price_low"], lines()["Kitchen", "Flooring"]["price_basis"]) == (5.0, "cost guide, supplied and installed")
    told, asked = model_says(monkeypatch)
    tighten.price_work("u1", **how())
    assert asked[0]["ids"] == ["flooring:ceramic or porcelain tile", "door:flush", "paint:smooth painted"]


# ---- the rules ---------------------------------------------------------------------------------------

def test_no_price_is_worked_out_and_unknown_stays_null():
    row = lambda low, high, url="https://example.org/g": {"price": low, "price_high": high, "checked": True, "source": {"url": url, "title": "t", "quote": "q"}}
    guide, seen, fit, match = row(1500.0, 8000.0), row(2000.0, 12000.0, "https://example.org/s"), row(100.0, None, "https://example.org/f"), {"low": 698.0, "high": 749.0, "candidates": [{"make": "M", "price": 698.0, "url": "https://shop.example/x"}]}
    stated = {1500.0, 8000.0, 2000.0, 12000.0, 698.0, 749.0, 698.0 + 100.0, 749.0 + 100.0}
    for args in ((guide,), (guide, match), (guide, match, fit), (guide, None, fit), (guide, None, None, seen), (guide, None, fit, seen), (guide, match, None, seen), (None, match, fit), (None, None, None, seen)):
        p = tighten.price_of(*args)
        assert p["price_low"] in stated and p["price_high"] in stated                                                                    # an end of a stated range, or a product plus its fitting: never a point between
    assert tighten.price_of(guide, match, fit, seen)["price_basis"] == "matched product plus fitting" and tighten.price_of(guide, None, fit, seen)["price_basis"] == "cost guide for what was seen"
    assert (tighten.price_of(guide, None, fit)["price_low"], tighten.price_of(guide, None, fit)["fitting_low"]) == (1500.0, None)        # fitting is never added to a cost-guide price, which has it already
    none = tighten.price_of(None)
    assert none == {"price_low": None, "price_high": None, "price_basis": None, "source_url": None, "source_title": None, "guide_low": None, "guide_high": None, "fitting_low": None, "fitting_high": None, "fitting_url": None}
    assert tighten.price_of(None, {"low": None, "high": None}, fit)["price_low"] is None and tighten.price_of(row(0, None))["price_low"] is None      # never zero
    line = schedule._line("fit:toilet", "Toilet", 2, "each", "read from the scan", {})
    assert (line["low"], line["high"], line["price_basis"], line["finish"]) == (None, None, None, None) and schedule._sum([line])["lines_priced"] == 0


def test_only_a_confirmed_row_is_ever_in_use(home):
    src = {"url": "https://example.org/p", "title": "t", "quote": "q"}
    tighten.fitting_path().write_text(json.dumps({"prices": [{"item": "fitting:toilet", "price": 90.0, "price_high": 100.0, "checked": False, "source": src}, {"item": "fitting:range", "price": 90.0, "checked": "yes", "source": src},
                                                             {"item": "fitting:dryer", "price": 0, "checked": True, "source": src}, {"item": "fitting:washer", "price": 120.0, "price_high": None, "checked": True, "source": src},
                                                             {"item": "fitting:washer", "price": 110.0, "price_high": 115.0, "checked": True, "source": src}]}))
    assert {k: r["price"] for k, r in tighten.confirmed(tighten.fitting_path()).items()} == {"fitting:washer": 120.0}                   # the first recorded, though the second is the tighter
    tighten.specific_path("u1").write_text("not json")
    assert tighten.confirmed(tighten.specific_path("u1")) == {} and tighten.Tight("u1").fit({"room": "bathroom-1", "kind": "toilet", "seen": "x"}) == {"fitting": None, "specific": None}
    assert tighten.Tight("u1").built("flooring", "kitchen-1") == {"specific": None, "finish": None}


def test_the_report_prints_the_schedule_before_and_after(home, monkeypatch, capsys):
    from scripts import tighten as cli
    matched(home, **{"kitchen-1:refrigerator": (698.0, 749.0)})
    model_says(monkeypatch, said("fitting:refrigerator", 100, 250, "https://guide.example/fridge"))
    tighten.price_fitting(**how())
    cli.report(7)
    out = capsys.readouterr().out
    assert "before  one home" in out and "after   one home" in out and "$698 to $749" in out and "$798 to $999" in out and "matched product plus fitting" in out
