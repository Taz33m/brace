"""The flood stress test: the Corps' curve read as published, water by ground level, and a plan held to its two limits."""
import json

import pytest

from backend import flood


def test_the_curve_is_the_published_one_and_nothing_is_lost_above_the_water():
    assert flood.damage_share(0) == 0 and flood.damage_share(-1) == 0
    assert flood.damage_share(2) == pytest.approx(0.209) and flood.damage_share(4) == pytest.approx(0.314) and flood.damage_share(6) == pytest.approx(0.407)
    assert flood.damage_share(2.5) == pytest.approx(0.236)                    # halfway between 2 ft and 3 ft
    assert flood.damage_share(40) == pytest.approx(0.692)                     # never past the end of the table


@pytest.fixture
def site(tmp_path, monkeypatch):
    square = lambda x: [[x, 0.0], [x + 0.0003, 0.0], [x + 0.0003, 0.0003], [x, 0.0003]]
    (tmp_path / "b" / "7").mkdir(parents=True); (tmp_path / "h" / "7").mkdir(parents=True)
    (tmp_path / "b" / "7" / "building.json").write_text(json.dumps({
        "record": {"name": "Low Court", "units": 90}, "aerial": {"bounds": [0, 0, 1, 1], "width": 100, "height": 100},
        "structures": [{"id": "A", "polygon": square(0.0), "footprint_sqft": 6000}, {"id": "B", "polygon": square(0.001), "footprint_sqft": 3000},
                       {"id": "C", "polygon": square(0.002), "footprint_sqft": 1000}, {"id": "D", "polygon": square(0.003), "footprint_sqft": 500}]}))
    (tmp_path / "h" / "7" / "heights.json").write_text(json.dumps({
        "source": {"terrain": {"first_capture": "2025-01-31", "last_capture": "2025-03-05"}},
        "structures": [{"id": "A", "ground_elevation_m": 10.0}, {"id": "B", "ground_elevation_m": 10.3048}, {"id": "C", "ground_elevation_m": 12.0}, {"id": "D"}]}))
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path / "b"); monkeypatch.setattr(flood, "HEIGHTS", tmp_path / "h")
    monkeypatch.setattr(flood, "RESEARCH", tmp_path / "research.json")
    monkeypatch.setattr(flood.portfolio, "building", lambda pid: {"last_sale": {"price": 10_000_000, "date": "2019-05-01"}})
    return 7


def test_water_is_measured_from_the_lowest_building_and_higher_ground_gets_less(site):
    r = flood.test(site, 2)
    by = {b["id"]: b for b in r["buildings"]}
    assert set(by) == {"A", "B", "C"}                                          # D has no measured ground: it is left out, not guessed
    assert (by["A"]["depth_ft"], by["B"]["depth_ft"], by["C"]["depth_ft"]) == (2.0, 1.0, 0.0)
    assert by["A"]["value"] == 6_000_000 and by["A"]["loss"] == round(6_000_000 * 0.209) and by["C"]["loss"] == 0
    assert r["do_nothing"] == {"loss": by["A"]["loss"] + by["B"]["loss"], "buildings_wet": 2} and r["plan"] is None
    assert r["why"][0] == {"text": "Building A stands on the lowest ground here, 6.6 ft below the highest", "source": "Vexcel"}
    assert {"text": "Last sold for $10,000,000 in 2019", "source": "CoStar"} in r["why"] and r["research"]["by"] == "hand"


def test_the_plan_keeps_to_the_budget_and_the_hours_and_never_uses_a_barrier_lower_than_the_water(site):
    full = flood.test(site, 2, budget=1_000_000, hours=48, crews=1)
    assert full["plan"]["buildings_protected"] == 2 and full["plan"]["loss"] == 0 and full["plan"]["saved"] == full["do_nothing"]["loss"]
    assert all(b["fix"]["measure"] == "tube30" for b in full["buildings"] if b["fix"])                # the cheaper barrier that still holds
    short = flood.test(site, 2, budget=1_000_000, hours=24, crews=1)                                   # one crew day: one building
    by = {b["id"]: b for b in short["buildings"]}
    assert by["A"]["fix"] and by["B"]["left_out"] == "the time ran out" and short["plan"]["crew_hours_used"] == 12.0
    poor = flood.test(site, 2, budget=100, hours=48, crews=3)
    assert poor["plan"]["buildings_protected"] == 0 and {b["left_out"] for b in poor["buildings"] if b["loss"]} == {"the budget ran out"}
    deep = flood.test(site, 6, budget=1_000_000, hours=48, crews=3)
    by = {b["id"]: b for b in deep["buildings"]}
    assert by["A"]["left_out"] == "no barrier here holds 6 ft" and by["A"]["fix"] is None              # 6 ft is over the tallest barrier
    assert by["C"]["fix"] is None and "Low Court" in full["plan"]["work_order"] and "Nothing is ordered until the owner approves" in full["plan"]["work_order"]


def test_a_site_without_a_terrain_model_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path); monkeypatch.setattr(flood, "HEIGHTS", tmp_path)
    with pytest.raises(flood.FloodError):
        flood.test(9, 2)


def _research(tmp_path, fixes):
    (tmp_path / "research.json").write_text(json.dumps({"made_at": "2026-11-14T20:00:00+00:00", "model": "m", "steps": [{"t": 1, "kind": "search", "text": "flood barrier price"}], "fixes": fixes}))


def _fix(**over):
    return {"name": "Box barrier, 3 ft", "type": "quick", "holds_ft": 3.0, "price": 10.0, "price_unit": "per linear foot", "crew_hours_per_100ft": None, "bags_per_person_hour": None,
            "weeks": None, "time_text": None, "source": {"title": "t", "url": "https://example.org/a", "quote": "q"}, "checked": True, **over}


def test_the_plan_uses_what_the_agent_found_only_when_its_page_confirmed_the_price(site, tmp_path):
    _research(tmp_path, [_fix(), _fix(name="Cheap wall, 3 ft", price=1.0, checked=False), _fix(name="Floodwall", type="long-term", price=900.0, weeks=10.0)])
    r = flood.test(site, 2, budget=1_000_000, hours=48, crews=1)
    assert {b["fix"]["measure"] for b in r["buildings"] if b["fix"]} == {"box-barrier--3-ft"}                    # never the cheaper one that was not confirmed
    found = {f["name"]: f for f in r["research"]["found"]}
    assert found["Cheap wall, 3 ft"]["why_not"] == "the price could not be confirmed on the page" and found["Box barrier, 3 ft"]["planned"]
    assert "Floodwall: 10 weeks. It does not fit 48 hours." in r["plan"]["tradeoffs"] and found["Floodwall"]["why_not"] == "long-term work" and r["research"]["by"] == "agent" and r["research"]["searches"] == 1
    assert "what Brace's research agent found on the web on 2026-11-14" in " ".join(r["assumptions"])


def test_the_barriers_entered_by_hand_stay_and_a_price_its_page_calls_incomplete_is_never_planned(site, tmp_path):
    _research(tmp_path, [_fix(checked=False), _fix(name="Sand box, 4 ft", holds_ft=4.0, price=5.0, source={"title": "t", "url": "https://example.org/b", "quote": "About $5 per linear foot (not including sand)."})])
    r = flood.test(site, 2, budget=1_000_000, hours=48, crews=1)
    assert {b["fix"]["measure"] for b in r["buildings"] if b["fix"]} == {"tube30"}
    assert {f["name"]: f["why_not"] for f in r["research"]["found"]}["Sand box, 4 ft"] == "the page says this price leaves something out"


def test_a_sandbag_wall_is_priced_and_timed_by_its_bags_and_the_plan_pays_more_when_time_is_short(site, tmp_path):
    assert flood.bags_per_ft(2) == 21 and flood.bags_per_ft(1) == 6
    _research(tmp_path, [_fix(name="Sandbag", holds_ft=None, price=0.5, price_unit="per sandbag", bags_per_person_hour=30.0), _fix(name="Sandbag, no rate", holds_ft=None, price=0.4, price_unit="per sandbag")])
    cat = flood.catalogue()
    wall = {m["id"]: m for m in cat["measures"]}["sandbags-2ft"]
    assert wall["cost_per_ft"] == 10.5 and wall["crew_hours_per_100ft"] == 17.5                                       # 21 bags a foot; 2,100 bags at 30 a person-hour, four people
    assert [f["why_not"] for f in cat["found"]] == [None, "no stated filling rate"]
    short = flood.test(site, 2, budget=1_000_000, hours=48, crews=1)                                                   # 24 crew hours: a 2 ft sandbag wall round A needs about 76
    assert {b["id"]: b["fix"]["measure"] for b in short["buildings"] if b["fix"]} == {"A": "tube30", "B": "tube30"} and short["plan"]["loss"] == 0   # the dearer barrier, because it is the one that fits
    long = flood.test(site, 2, budget=1_000_000, hours=48, crews=10)                                                   # with the crews, the cheaper wall
    assert {b["id"]: b["fix"]["measure"] for b in long["buildings"] if b["fix"]} == {"A": "sandbags-2ft", "B": "sandbags-1ft"} and long["plan"]["spent"] < short["plan"]["spent"]


def test_the_top_of_a_price_range_is_counted_and_a_panel_wall_is_priced_by_its_face(site, tmp_path):
    _research(tmp_path, [_fix(name="Tube, 3 ft", price=15.0, price_high=40.0), _fix(name="Panel wall", holds_ft=None, price=50.0, price_high=100.0, price_unit="per square foot"), _fix(name="Fence", holds_ft=None)])
    cat = flood.catalogue(); by = {m["id"]: m for m in cat["measures"]}
    assert by["tube--3-ft"]["cost_per_ft"] == 40.0 and by["panel-wall-4ft"]["cost_per_ft"] == 400.0 and by["panel-wall-6ft"]["holds_ft"] == 6.0
    assert {f["name"]: f["why_not"] for f in cat["found"]}["Fence"] == "no stated height"
    deep = flood.test(site, 6, budget=10_000_000, hours=72, crews=3)                                                   # 6 ft is over the tube; the 6 ft panel wall holds it
    assert {b["id"]: b for b in deep["buildings"]}["A"]["fix"]["measure"] == "panel-wall-6ft"


def test_the_scenario_is_in_the_shape_the_screens_read(site):
    sc = flood.scenario(site, 2, budget=1_000_000, hours=24, crews=1)
    assert sc["flood"] == {"severityFt": 2, "hoursBeforeFlood": 24} and sc["budget"] == 1_000_000 and sc["property"]["name"] == "Low Court" and sc["property"]["value"] == 10_000_000
    assert sc["lossBefore"] - sc["lossAfter"] == sc["saved"] == sum(f["lossAvoided"] for f in sc["fixes"] if f["selected"])
    first, second = sc["fixes"][0], sc["fixes"][1]
    assert first["selected"] and first["type"] == "quick" and 0 <= first["position"]["x"] <= 1 and 0 <= first["position"]["y"] <= 1 and first["cost"] > 0
    assert not second["selected"] and second["leftOut"] == "the time ran out" and "Crews will put flood barriers round building A." in sc["notice"]
