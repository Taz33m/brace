"""The insurer's file: quantities from the scan, a line priced only from a confirmed price, and unknown money never zero."""
import json
from types import SimpleNamespace as NS

import pytest

from backend import flood, flood_agent, insurer_file as f

HOME = {"scan_id": "u1", "name": "1BR", "kind": "apartment unit", "under_roof": "A", "floor_known": False, "model_made": "2026-11-10",
        "rooms": [{"type": "Living Room", "area_sqft": 300.0, "ceiling_ft": 8.0}], "floor_sqft": 300, "ceiling_ft": 8.0, "wall_ft": 110, "wall_less_doorways_ft": 100,
        "inner_doors": 2, "outside_doors": 1, "windows": 1, "contents_room": "Living Room", "contents_note": "n", "has_photo": False,
        "contents": [{"name": "blue sofa", "kind": "sofa", "look": "navy loveseat", "height_ft": 2.8, "stands_at_ft": 0.0},
                     {"name": "left table lamp", "kind": "lamp", "look": "navy base", "height_ft": 1.9, "stands_at_ft": 2.2},
                     {"name": "right table lamp", "kind": "lamp", "look": "navy base", "height_ft": 1.9, "stands_at_ft": 2.2}]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    run = {"name": "Low Court", "address": "1 Low St", "sale": None, "bounds": [0, 0, 1, 1], "aerial": {"width": 10, "height": 10}, "assumptions": ["Ground under each building: Vexcel."],
           "buildings": [{"id": "A", "polygon": [[0, 0]], "ground_m": 10.0, "depth_ft": 1.5, "trees_within_5ft_percent": 12.0}, {"id": "B", "polygon": [[0, 0]], "ground_m": 10.6, "depth_ft": 0.0}]}
    monkeypatch.setattr(f.flood, "test", lambda pid, water_ft: run)
    monkeypatch.setattr(f, "inside", lambda pid, sid: HOME)
    monkeypatch.setattr(f, "PRICES", tmp_path / "prices.json")
    monkeypatch.setattr(f.flood, "HEIGHTS", tmp_path)
    return run


def _prices(tmp_path, rows):
    src = {"title": "t", "url": "https://example.org/p", "quote": "q"}
    (tmp_path / "prices.json").write_text(json.dumps({"made_at": "2026-11-14T22:00:00+00:00", "steps": [{"kind": "search", "text": "x"}],
                                                      "prices": [{"unit": "u", "source": src, "price_high": None, "checked": True, **r} for r in rows]}))


def test_quantities_come_from_the_scan_and_the_drywall_is_cut_two_feet_above_the_water(home, tmp_path):
    r = f.file(7, "u1", 4)
    by = {l["id"]: l for l in r["schedule"]["work"]}
    assert r["water"] == {"set_ft": 4, "at_this_building_ft": 1.5, "drywall_cut_ft": 3.5} and r["outside"]["below_highest_ft"] == 2.0
    assert (by["flooring"]["quantity"], by["drywall"]["quantity"], by["baseboard"]["quantity"], by["paint"]["quantity"], by["door"]["quantity"]) == (300, 350, 100, 800, 2)
    assert by["drywall"]["how"] == "100 ft of wall, less doorways, cut out to 3.5 ft"


def test_with_no_confirmed_price_a_line_has_no_figure_and_the_total_is_unknown_not_zero(home, tmp_path):
    r = f.file(7, "u1", 4)
    assert all(l["low"] is None and l["source"] is None for l in r["schedule"]["work"]) and r["schedule"]["total"] is None
    _prices(tmp_path, [{"item": "flooring", "price": 4.0, "price_high": 9.0}, {"item": "door", "price": 300.0}, {"item": "drywall", "price": 2.0, "checked": False}])
    r = f.file(7, "u1", 4)
    by = {l["id"]: l for l in r["schedule"]["work"]}
    assert (by["flooring"]["low"], by["flooring"]["high"]) == (1200, 2700) and (by["door"]["low"], by["door"]["high"]) == (600, 600)
    assert by["drywall"]["low"] is None                                                       # recorded, but its page did not confirm it
    assert r["schedule"]["work_total"] == {"low": 1800, "high": 3300, "lines": 6, "priced": 2} and r["schedule"]["total"] == {"low": 1800, "high": 3300}


def test_furniture_standing_above_the_water_is_spared_and_two_of_a_kind_share_one_price(home, tmp_path):
    _prices(tmp_path, [{"item": "piece:blue sofa", "price": 500.0, "price_high": 900.0}, {"item": "piece:table lamp", "price": 40.0}])
    r = f.file(7, "u1", 4)                                                                    # 1.5 ft at the building: the lamps stand 2.2 ft up
    assert [l["what"] for l in r["schedule"]["contents"]] == ["Blue sofa"] and r["schedule"]["contents_spared"] == ["left table lamp", "right table lamp"]
    assert r["schedule"]["contents_total"] == {"low": 500, "high": 900, "lines": 1, "priced": 1}
    home["buildings"][0]["depth_ft"] = 3.0
    r = f.file(7, "u1", 6)
    assert [(l["what"], l["low"]) for l in r["schedule"]["contents"]] == [("Blue sofa", 500), ("Left table lamp", 40), ("Right table lamp", 40)] and r["water"]["drywall_cut_ft"] == 5.0


def test_a_dry_building_has_an_empty_schedule(home):
    home["buildings"][0]["depth_ft"] = 0.0
    r = f.file(7, "u1", 2)
    assert r["schedule"]["work"] == [] and r["schedule"]["contents"] == [] and r["schedule"]["total"] is None and r["water"]["drywall_cut_ft"] == 0


def test_the_price_list_asks_for_each_kind_of_furniture_once():
    assert f._piece_key("left side table") == f._piece_key("right side table") == "side table"


class _Client:
    def __init__(self, calls):
        self.turns = [NS(stop_reason="tool_use", usage=NS(input_tokens=10, output_tokens=2), content=[NS(type="tool_use", name="record_price", id=str(i), input=c) for i, c in enumerate(calls)]),
                      NS(stop_reason="end_turn", usage=NS(input_tokens=5, output_tokens=1), content=[NS(type="text", text="Done.")])]
        self.sent = []
        self.beta = NS(messages=NS(create=lambda **kw: (self.sent.append(kw), self.turns.pop(0))[1]))


def test_the_price_research_records_only_listed_items_and_checks_each_against_its_page(tmp_path):
    items = [{"id": "drywall", "what": "Drywall, hung and finished", "unit": "per square foot"}, {"id": "door", "what": "Interior door, installed", "unit": "each"}]
    ok = {"item": "drywall", "price": 1.5, "price_high": 3.5, "source_title": "Guide", "source_url": "https://example.org/drywall", "quote": "Drywall installation costs $1.50 to $3.50 per square foot."}
    client = _Client([ok, {**ok, "item": "roof"}, {**ok, "item": "door", "price": 250, "price_high": None, "source_url": "https://example.org/none", "quote": "A door costs $250."}])
    run = flood_agent.price(items, client=client, save_to=tmp_path / "p.json", fetch=lambda url: "Drywall installation costs $1.50 to $3.50 per square foot." if url.endswith("/drywall") else None)
    assert [(p["item"], p["checked"]) for p in run["prices"]] == [("drywall", True), ("door", False)]
    assert client.sent[1]["messages"][2]["content"][1]["is_error"] and "- door: Interior door, installed (each)" in client.sent[0]["messages"][0]["content"]
    assert client.sent[0]["tools"][2]["input_schema"]["properties"]["item"]["enum"] == ["drywall", "door"] and json.loads((tmp_path / "p.json").read_text())["prices"][0]["price_high"] == 3.5
