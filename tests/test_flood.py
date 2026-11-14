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
    monkeypatch.setattr(flood.portfolio, "building", lambda pid: {"last_sale": {"price": 10_000_000, "date": "2019-05-01"}})
    return 7


def test_water_is_measured_from_the_lowest_building_and_higher_ground_gets_less(site):
    r = flood.test(site, 2)
    by = {b["id"]: b for b in r["buildings"]}
    assert set(by) == {"A", "B", "C"}                                          # D has no measured ground: it is left out, not guessed
    assert (by["A"]["depth_ft"], by["B"]["depth_ft"], by["C"]["depth_ft"]) == (2.0, 1.0, 0.0)
    assert by["A"]["value"] == 6_000_000 and by["A"]["loss"] == round(6_000_000 * 0.209) and by["C"]["loss"] == 0
    assert r["do_nothing"] == {"loss": by["A"]["loss"] + by["B"]["loss"], "buildings_wet": 2} and r["plan"] is None


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
