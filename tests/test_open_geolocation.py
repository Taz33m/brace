"""Open problem "better geolocation": the pure parts, on small made-up shapes.

No network, no keys and no cached sponsor data: the one test that walks a whole scan feeds it a
synthetic model through a patched loader.
"""
from __future__ import annotations

import math

import pytest
from shapely import affinity
from shapely.geometry import Polygon

from backend import geo
from backend.openproblems import geolocation as G


def rect(x0, y0, w, h):
    return Polygon([(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)])


# An L with unequal arms: no turn other than a full one maps it onto itself.
L_SHAPE = Polygon([(0, 0), (20, 0), (20, 6), (8, 6), (8, 30), (0, 30)])


# --- the correction measurement ------------------------------------------------------------------

def test_correction_is_the_shift_of_the_plan_centre_and_the_turn_between_the_two_maps():
    raw = geo.Transform([[1.0, 0.0], [0.0, 1.0]], [100.0, 50.0])
    fitted = raw.then_rigid(3.0, 4.0, 10.0, 105.0, 55.0)  # turn 10 degrees about the plan centre, then shift 3 east 4 north
    c = G.measure_correction(raw, fitted, (5.0, 5.0), corners=[(0, 0), (10, 0), (10, 10), (0, 10)])
    assert c["shift_m"] == 5.0 and c["east_m"] == 3.0 and c["north_m"] == 4.0
    assert c["rotation_deg"] == 10.0
    # a corner is 7.07 m from the centre, so the turn alone moves it 1.23 m; with the shift it moves more than 5 m
    assert c["max_corner_move_m"] > c["shift_m"]


def test_no_fit_means_no_correction_even_when_matterports_own_map_is_turned():
    th = math.radians(37)
    raw = geo.Transform([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]], [12.0, -7.0])
    c = G.measure_correction(raw, raw, (2.0, 3.0), corners=[(0, 0), (4, 6)])
    assert c == {"shift_m": 0.0, "east_m": 0.0, "north_m": 0.0, "rotation_deg": 0.0, "max_corner_move_m": 0.0}


def test_clockwise_turn_is_negative():
    raw = geo.Transform([[1.0, 0.0], [0.0, 1.0]], [0.0, 0.0])
    c = G.measure_correction(raw, raw.then_rigid(0.0, 0.0, -6.0, 0.0, 0.0), (0.0, 0.0))
    assert c["rotation_deg"] == -6.0 and c["shift_m"] == 0.0


# --- heading from wall directions ----------------------------------------------------------------

def _ring(poly):
    return list(poly.exterior.coords)


def test_walls_five_degrees_off_the_roof_are_turned_back():
    roof = rect(0, 0, 60, 15)
    unit = affinity.rotate(rect(10, 3, 9, 7), 5, origin="centroid")
    h = G.heading_correction([_ring(unit)], _ring(roof))
    assert h["applied"] and h["turn_deg"] == pytest.approx(-5.0, abs=0.01)
    assert h["plan_squareness"] == 1.0 and h["roof_squareness"] == 1.0


def test_a_right_angle_turn_counts_as_no_turn():
    # Walls only say which way the grid runs, not which wall is "front".
    h = G.heading_correction([_ring(affinity.rotate(rect(0, 0, 9, 7), 90, origin="centroid"))], _ring(rect(0, 0, 60, 15)))
    assert h["turn_deg"] == pytest.approx(0.0, abs=0.01)


def test_a_large_disagreement_is_reported_but_not_applied():
    unit = affinity.rotate(rect(10, 3, 9, 7), 20, origin="centroid")
    h = G.heading_correction([_ring(unit)], _ring(rect(0, 0, 60, 15)))
    assert h["turn_deg"] == pytest.approx(-20.0, abs=0.01)
    assert not h["applied"] and "left as Matterport gave it" in h["why"]


def test_a_roof_that_is_not_square_gives_no_heading():
    hexagon = Polygon([(10 * math.cos(math.radians(a)), 10 * math.sin(math.radians(a))) for a in range(0, 360, 60)])
    h = G.heading_correction([_ring(affinity.rotate(rect(0, 0, 9, 7), 3, origin="centroid"))], _ring(hexagon))
    assert h["roof_squareness"] < G.MIN_SQUARENESS and not h["applied"]


# --- outline from camera positions ---------------------------------------------------------------

def test_too_few_camera_positions_give_no_outline():
    assert G.camera_outline([(0, 0), (1, 0), (2, 0), (3, 0)]) is None


def test_camera_outline_covers_the_positions_and_little_else():
    pts = [(x, y) for x in (0, 2, 4, 6) for y in (0, 2)]
    out = G.camera_outline(pts)
    assert out is not None
    assert all(out.buffer(0.01).contains(geo.Point(x, y)) for x, y in pts)
    assert out.area < rect(-1.5, -1.5, 9, 5).area  # stays within about a metre of where the camera stood


# --- placing a scan by shape ---------------------------------------------------------------------

def _cand(sid, score, inside=1.0):
    return {"structure": sid, "score": score, "inside": inside, "rotation_deg": 0.0}


def test_a_clear_winner_is_placed():
    v = G.decide_placement([_cand("S2", 0.52), _cand("S1", 0.88), _cand("S3", 0.31)])
    assert v["placed"] and v["best"]["structure"] == "S1" and v["runner_up"]["structure"] == "S2"
    assert v["margin"] == pytest.approx(0.36)


def test_too_close_to_call_is_not_placed():
    # Two buildings with the same outline: both score well, neither can be chosen.
    v = G.decide_placement([_cand("S1", 0.91), _cand("S2", 0.89), _cand("S3", 0.2)])
    assert not v["placed"] and "too close to call" in v["why"]
    assert v["best"]["structure"] == "S1" and v["runner_up"]["structure"] == "S2" and v["margin"] == pytest.approx(0.02)


def test_the_same_roof_at_another_heading_is_a_rival_too():
    v = G.decide_placement([{**_cand("S1", 0.9), "rotation_deg": 0.0}, {**_cand("S1", 0.9), "rotation_deg": 180.0}])
    assert not v["placed"] and "too close to call" in v["why"]


def test_a_plan_that_merely_fits_inside_a_roof_is_not_placed():
    # A unit under a big roof: all of it is inside, but the two outlines look nothing alike.
    v = G.decide_placement([_cand("S1", 0.12, inside=1.0), _cand("S2", 0.03, inside=1.0)])
    assert not v["placed"] and "only scores" in v["why"]


def test_a_good_score_on_camera_positions_is_still_refused():
    v = G.decide_placement([_cand("S1", 0.9), _cand("S2", 0.3)], outline_is_floor_plan=False)
    assert not v["placed"] and "camera positions" in v["why"]


def test_no_roof_outlines_means_not_placed():
    v = G.decide_placement([])
    assert not v["placed"] and v["best"] is None and v["runner_up"] is None


def test_shape_match_finds_the_one_building_with_the_plans_outline():
    plan = affinity.rotate(L_SHAPE, 73, origin="centroid")  # a scan without GPS has an arbitrary heading
    roofs = {"S1": rect(100, 0, 70, 18), "S2": affinity.translate(affinity.rotate(L_SHAPE, 20, origin="centroid"), 300, 40)}
    cands = G.match_by_shape(plan, roofs)
    assert {c["structure"] for c in cands} == {"S1", "S2"}  # every roof is scored
    v = G.decide_placement(cands)
    assert v["placed"] and v["best"]["structure"] == "S2" and v["best"]["score"] > 0.9
    c = roofs["S2"].centroid  # the plan's centre lands on the roof's centre, within the fit's step
    assert math.hypot(v["best"]["x"] - c.x, v["best"]["y"] - c.y) < 1.0


def test_shape_match_cannot_choose_between_twin_buildings():
    twin = affinity.rotate(L_SHAPE, 20, origin="centroid")
    roofs = {"S1": affinity.translate(twin, 300, 40), "S2": affinity.translate(twin, 380, 40)}
    v = G.decide_placement(G.match_by_shape(L_SHAPE, roofs))
    assert not v["placed"] and "too close to call" in v["why"]
    assert {v["best"]["structure"], v["runner_up"]["structure"]} == {"S1", "S2"}


def test_shape_match_does_not_place_a_small_unit_under_big_roofs():
    unit = rect(0, 0, 9, 7)
    roofs = {"S1": rect(100, 0, 60, 15), "S2": rect(100, 60, 55, 16)}
    cands = G.match_by_shape(unit, roofs)
    v = G.decide_placement(cands)
    assert not v["placed"] and v["best"]["inside"] == pytest.approx(1.0) and v["best"]["score"] < 0.1
    assert all(c["score"] <= c["score_ceiling"] + 1e-6 for c in cands)  # overlap can never beat the area ratio


# --- one scan end to end, on a synthetic model -----------------------------------------------------

FRAME = geo.LocalFrame(29.6, -95.2)
ROOFS = {"S1": rect(0, 0, 60, 15), "S2": rect(0, 60, 60, 15)}


def _model(geo_fix: bool, at=(20.0, -3.0), heading_deg=0.0):
    """A 9 x 7 m two-room unit. With a GPS fix its corner sits at `at`, turned `heading_deg` from the roof."""
    th = math.radians(heading_deg)
    ex, ey = (math.cos(th), math.sin(th)), (-math.sin(th), math.cos(th))
    ll = lambda x, y: list(FRAME.to_lonlat(x, y))
    fix = {"source": "processing", "origin": ll(*at), "ex10": ll(at[0] + 10 * ex[0], at[1] + 10 * ex[1]),
           "ey10": ll(at[0] + 10 * ey[0], at[1] + 10 * ey[1])} if geo_fix else \
        {"source": None, "origin": None, "ex10": None, "ey10": None}
    return {"geo": fix,
            "rooms": [{"polygon": [[0, 0], [5, 0], [5, 7], [0, 7], [0, 0]]}, {"polygon": [[5, 0], [9, 0], [9, 7], [5, 7], [5, 0]]}],
            "sweeps": [{"x": x, "y": y, "has_pano": True} for x in (1, 3, 5, 7) for y in (2, 5)]}


def test_a_unit_gps_left_half_outside_the_roof_is_moved_under_it(monkeypatch):
    monkeypatch.setattr(G, "_model", lambda scan_id: _model(True, at=(20.0, -3.0), heading_deg=4.0))
    r = G._scan_result({"id": "scanA", "name": "1BR, 1BA - 622SF", "structure": "S1"}, FRAME, ROOFS)
    assert r["status"] == "aligned" and r["structure"] == "S1" and r["outline_source"] == "room outlines"
    assert r["raw"]["inside"] < 0.75 and r["fitted"]["inside"] == pytest.approx(1.0, abs=0.01)
    assert 2.5 < r["correction"]["shift_m"] < 4.5              # it was about 3 m outside
    assert r["correction"]["rotation_deg"] == pytest.approx(-4.0, abs=0.1)  # walls made parallel to the roof
    assert r["fit_quality"] == "loose" and r["position_pinned"] is False     # the roof is far bigger than the unit
    assert "only proves the unit is under it" in r["why"]
    lon, lat = r["fitted"]["outline"][0]
    assert abs(lon - -95.2) < 0.01 and abs(lat - 29.6) < 0.01   # the outline is in lon/lat, ready to draw


def test_a_unit_far_from_every_roof_is_left_on_raw_gps(monkeypatch):
    monkeypatch.setattr(G, "_model", lambda scan_id: _model(True, at=(20.0, -40.0)))
    r = G._scan_result({"id": "scanB", "name": "Unit"}, FRAME, ROOFS)
    assert r["status"] == "raw_gps_only" and r["reason"] == "too_far_from_any_roof"
    assert r["fitted"] is None and r["correction"] is None and r["raw"]["outline"]


def test_a_scan_without_gps_is_not_placed_and_says_why(monkeypatch):
    monkeypatch.setattr(G, "_model", lambda scan_id: _model(False))
    r = G._scan_result({"id": "scanC", "name": "2BR, 2BA - 892 SF"}, FRAME, ROOFS)
    assert r["status"] == "not_placed" and r["has_gps"] is False and r["raw"] is None and r["fitted"] is None
    sm = r["shape_match"]
    assert sm["placed"] is False and sm["best"] and sm["runner_up"] and sm["structures_it_fits_inside"] == 2
    assert "no geocoordinates" in r["why"] and "ould not be placed" in r["why"]


def test_an_outdoor_scan_is_never_fitted_to_a_roof(monkeypatch):
    monkeypatch.setattr(G, "_model", lambda scan_id: _model(True, at=(20.0, -3.0)))
    r = G._scan_result({"id": "scanD", "name": "Pool"}, FRAME, ROOFS)
    assert r["status"] == "raw_gps_only" and r["reason"] == "outdoor" and r["fitted"] is None


def test_summary_numbers_are_the_measured_ones():
    def scan(status, shift=None, turn=0.0, quality="loose", gps=True):
        s = {"status": status, "has_gps": gps, "fit_quality": None, "correction": None, "raw": None, "fitted": None}
        if status == "aligned":
            s.update(fit_quality=quality, correction={"shift_m": shift, "rotation_deg": turn},
                     raw={"inside": 0.5}, fitted={"inside": 1.0})
        return s

    out = G.summarise([scan("aligned", 0.0), scan("aligned", 2.0, turn=-3.0), scan("aligned", 6.5, quality="good"),
                       scan("raw_gps_only"), scan("not_placed", gps=False)])
    assert (out["scans"], out["with_matterport_gps"], out["aligned"], out["raw_gps_only"], out["not_placed"]) == (5, 4, 3, 1, 1)
    assert out["aligned_position_pinned"] == 1 and out["aligned_under_roof_only"] == 2 and out["moved_by_fit"] == 2
    a = out["correction_all_aligned"]
    assert (a["median_shift_m"], a["min_shift_m"], a["max_shift_m"]) == (2.0, 0.0, 6.5)
    assert out["correction_moved_only"]["median_shift_m"] == 4.25
    assert G.summarise([scan("not_placed", gps=False)])["correction_all_aligned"]["median_shift_m"] is None
