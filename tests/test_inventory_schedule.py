"""The inventory agent's rules and the schedule's arithmetic: no sighting, no item; the model never measures or totals."""
import json

import pytest

from backend import flood, insurer_file, inventory_agent, schedule

SCAN = {"id": "u1", "name": "2BR", "structure": "A", "model_created_at": "2026-11-10T00:00:00Z",
        "rooms": [{"id": "rk", "type": "Kitchen", "area_sqft": 70.0, "height_m": 2.4384}, {"id": "rb", "type": "Bedroom", "area_sqft": 120.0, "height_m": 2.4384},
                  {"id": "rv", "type": "Void", "area_sqft": 2.0, "height_m": None}, {"id": "rc", "type": "Closet", "area_sqft": 20.0, "height_m": 2.4384}],
        "sweeps": [{"id": "s1", "room_id": "rk", "heading": 90.0}, {"id": "s2", "room_id": "rk", "heading": 0.0}, {"id": "s3", "room_id": "rb", "heading": 0.0}]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    (tmp_path / "b" / "7").mkdir(parents=True)
    (tmp_path / "b" / "7" / "building.json").write_text(json.dumps({"scans": [SCAN], "structures": [{"id": "A", "footprint_sqft": 3000}, {"id": "B", "footprint_sqft": 1000}]}))
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path / "b")
    monkeypatch.setattr(inventory_agent, "OUT", tmp_path / "inv")
    monkeypatch.setattr(inventory_agent.matterport, "face_image", lambda scan, sweep, face: tmp_path / "x.jpg")
    monkeypatch.setattr(inventory_agent.vision, "image_block", lambda path, max_side=896: {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": ""}})
    return inventory_agent.InventoryRun(7, "u1")


def test_only_rooms_the_camera_stood_in_can_be_read(run):
    assert list(run.rooms) == ["kitchen-1", "bedroom-1"]                                     # the closet has no standpoint and the void is not a room
    assert list(run.rooms["kitchen-1"]["standpoints"]) == ["p1", "p2"]


def test_an_item_is_recorded_only_against_a_view_that_was_looked_at_and_only_if_the_owner_insures_it(run):
    t = run.tools()
    assert t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "white fridge").startswith("Not recorded: nobody has looked")
    assert t["look"]("kitchen-1", "p1", "ahead")[1]["type"] == "image"
    assert t["record_item"]("kitchen-1", "sofa", 1, "p1", "ahead", 0.5, 0.5, "blue sofa").startswith("Not recorded: 'sofa' is not fit-out")
    assert t["record_item"]("kitchen-1", "refrigerator", 0, "p1", "ahead", 0.5, 0.5, "x").startswith("Not recorded: quantity")
    assert t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "white fridge") == "Recorded as i1: 1 x Refrigerator in Kitchen."
    assert run.items[0]["at"] == {"sweep_id": "s1", "standpoint": "p1", "direction": "ahead", "yaw_deg": 90.0, "pitch_deg": 0.0}     # dead centre of the face the camera headed along
    t["look"]("kitchen-1", "p2", "right")
    t["record_item"]("kitchen-1", "base cabinet", 3, "p2", "right", 1.0, 0.5, "white base cabinets")
    assert run.items[1]["at"]["yaw_deg"] == 135.0                                                                              # heading 0, the right face, its right edge


def test_the_same_thing_seen_twice_is_merged_and_a_different_kind_never_is(run):
    t = run.tools()
    for p in ("p1", "p2"):
        t["look"]("kitchen-1", p, "ahead")
        t["record_item"]("kitchen-1", "refrigerator", 1, p, "ahead", 0.5, 0.5, "fridge")
    t["record_item"]("kitchen-1", "range", 1, "p1", "ahead", 0.2, 0.6, "gas range")
    assert t["merge"]("i1", ["i3"], "x").startswith("Nothing merged: records of different kinds")
    assert t["merge"]("i1", ["i2"], "the same refrigerator from the other standpoint") == "Merged 1 record(s) into i1."
    rec = run.record("done", {}, {"input_tokens": 0, "output_tokens": 0}, "finished")
    assert [i["id"] for i in rec["items"]] == ["i1", "i3"] and rec["numbers"] == {"rooms_read": 1, "views_looked_at": 2, "items_named": 2, "lines": 2}


def test_homes_are_shared_among_buildings_in_whole_numbers_that_add_up():
    assert schedule._share([3000, 1000], 10) == [8, 2] or schedule._share([3000, 1000], 10) == [7, 3]
    assert sum(schedule._share([1, 1, 1], 10)) == 10 and schedule._share([0, 0], 5) == [0, 0] and schedule._share([5, 5], 0) == [0, 0]


def test_a_line_without_a_confirmed_price_has_null_money_and_stays_out_of_the_total():
    prices = {"fit:refrigerator": {"price": 600.0, "price_high": 1200.0, "source": {"url": "https://example.org/r", "title": "t"}}}
    priced = schedule._line("fit:refrigerator", "Refrigerator", 1, "each", "read from the scan", prices)
    bare = schedule._line("fit:range", "Range", 1, "each", "read from the scan", prices)
    assert (priced["low"], priced["high"], priced["source_url"]) == (600, 1200, "https://example.org/r") and bare["low"] is None and bare["source_url"] is None
    assert schedule._sum([priced, bare]) == {"low": 600, "high": 1200, "lines": 2, "lines_priced": 1}
    assert schedule._sum([bare]) == {"low": None, "high": None, "lines": 1, "lines_priced": 0} and schedule._times(schedule._sum([bare]), 5) == {"low": None, "high": None}
    assert schedule._times(schedule._sum([priced, bare]), 268) == {"low": 160_800, "high": 321_600}


def test_the_schedule_multiplies_one_home_across_the_property_and_says_so(run, tmp_path, monkeypatch):
    t = run.tools()
    t["look"]("kitchen-1", "p1", "ahead"); t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "white fridge")
    (tmp_path / "inv").mkdir()
    (tmp_path / "inv" / "u1.json").write_text(json.dumps({**run.record("One room read.", {}, {}, "finished"), "seconds": 60.0}))
    src = {"url": "https://example.org/p", "title": "t", "quote": "q"}
    (tmp_path / "prices.json").write_text(json.dumps({"seconds": 120.0, "prices": [{"item": "fit:refrigerator", "price": 600.0, "price_high": 1200.0, "checked": True, "source": src},
                                                                                {"item": "flooring", "price": 5.0, "price_high": None, "checked": True, "source": src},
                                                                                {"item": "drywall", "price": 2.0, "price_high": None, "checked": False, "source": src}]}))
    monkeypatch.setattr(schedule, "PRICES", tmp_path / "prices.json"); monkeypatch.setattr(insurer_file, "PRICES", tmp_path / "none.json")
    monkeypatch.setattr(insurer_file, "inside", lambda pid, sid: {"name": "2BR", "under_roof": "A", "model_made": "2026-11-10", "floor_sqft": 210, "wall_ft": 100, "wall_less_doorways_ft": 90, "inner_doors": 3})
    monkeypatch.setattr(schedule.openings, "layout", lambda scan, walls: {"rooms": [{"id": "rk", "walls": [[[0, 0], [3.048, 0]]]}, {"id": "rb", "walls": [[[0, 0], [6.096, 0]]]}, {"id": "rc", "walls": []}]})
    monkeypatch.setattr(schedule.matterport, "MP_CACHE", tmp_path)
    (tmp_path / "openings").mkdir(); (tmp_path / "openings" / "u1.json").write_text("[]")
    monkeypatch.setattr(flood, "site", lambda pid: {"name": "Hill Court", "address": "1 Hill Rd", "homes": 10, "bounds": [0, 0, 1, 1], "aerial": {"width": 1, "height": 1},
                                                    "buildings": [{"id": "A", "polygon": [], "trees_within_5ft_percent": 20.0}, {"id": "B", "polygon": [], "trees_within_5ft_percent": 80.0}]})
    monkeypatch.setattr(schedule.portfolio, "rent", lambda pid: {"low": 2000, "high": 2500})
    s = schedule.schedule(7)
    kitchen = s["buildings"][1]["units"][0]["rooms"][0]
    assert [b["id"] for b in s["buildings"]] == ["B", "A"] and s["buildings"][0]["exposure_rank"] == 1                       # the building with more brush at its walls ranks first
    assert kitchen["name"] == "Kitchen" and [l["what"] for l in kitchen["items"]] == ["Refrigerator", "Flooring", "Drywall", "Painting", "Baseboard"]
    assert kitchen["items"][0]["from"] == "read from the scan" and kitchen["items"][0]["at"]["sweep_id"] == "s1" and kitchen["items"][1]["from"] == "measured from the scan"
    assert kitchen["items"][2]["quantity"] == 72 and kitchen["items"][2]["low"] is None                                     # 10 ft of wall less doorways (x0.9) to an 8 ft ceiling; its price was not confirmed
    home_total = s["home"]["total"]
    assert home_total == {"low": 600 + 5 * 210, "high": 1200 + 5 * 210, "lines": 14, "lines_priced": 4}                      # the fridge and three rooms of flooring; nothing else is priced
    assert s["total"]["low"] == home_total["low"] * 10 and s["home"]["multiplied_by"] == 10 and s["buildings"][1]["units"][0]["extrapolated"] is True
    assert sum(b["homes_assumed"] for b in s["buildings"]) == 10 and s["buildings"][1]["homes_assumed"] > s["buildings"][0]["homes_assumed"]
    assert s["lost_rent_per_month"]["low"] == 20_000 and s["lost_rent_per_month"]["high"] == 25_000 and s["numbers"]["minutes"] == 3.0 and s["numbers"]["model_cost_usd"] is None and s["numbers"]["prices_confirmed"] == 2
    assert [r["name"] for r in s["buildings"][1]["units"][0]["rooms"]] == ["Kitchen", "Bedroom", "Closet", "Throughout the home"] and s["buildings"][1]["units"][0]["rooms"][2]["read"] is False


def test_a_scan_nobody_has_read_has_no_schedule(run):
    with pytest.raises(schedule.ScheduleError):
        schedule.home(7, "u1")
