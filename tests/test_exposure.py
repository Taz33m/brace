"""Exposure: each building's three facts and the order they put it in. An ordering, never a chance of fire."""
import json

import pytest

from backend import exposure

SQUARE = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]


def _b(id, brush, roof, lon):
    return {"id": id, "trees_within_5ft_percent": brush, "roof_tree_cover_percent": roof, "centroid": [lon, 34.0], "polygon": SQUARE, "footprint_sqft": 1000}


# The stand-in fire map goes by longitude: 1 is outside every zone, 2 is High, 3 is Very High.
ZONES = {1.0: None, 2.0: "High", 3.0: "Very High"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    (tmp_path / "7").mkdir()
    (tmp_path / "7" / "building.json").write_text(json.dumps({"structures": [
        _b("A", 90.0, 0.0, 1.0), _b("B", 5.0, 10.0, 2.0), _b("C", 5.0, 40.0, 2.0), _b("D", None, None, 3.0)]}))
    monkeypatch.setattr(exposure, "BUILDINGS", tmp_path)
    monkeypatch.setattr(exposure, "zone_at", lambda lat, lon: (ZONES[lon], True))
    return tmp_path


def test_rank_is_zone_then_vegetation_at_the_wall_then_tree_cover_over_the_roof(site):
    rows = exposure.exposure(7)["buildings"]
    assert [b["id"] for b in rows] == ["D", "C", "B", "A"]
    assert [b["exposure_rank"] for b in rows] == [1, 2, 3, 4]
    assert rows[1] == {"id": "C", "exposure_rank": 2, "brush_within_5ft_percent": 5.0, "tree_cover_over_roof_percent": 40.0, "fire_zone": "High", "in_fire_zone": True,
                       "polygon": SQUARE, "footprint_sqft": 1000}


def test_a_missing_fact_is_null_and_sorts_last_within_its_zone(site):
    (site / "7" / "building.json").write_text(json.dumps({"structures": [_b("N", None, 80.0, 2.0), _b("M", 0.0, 0.0, 2.0)]}))
    rows = exposure.exposure(7)["buildings"]
    assert [b["id"] for b in rows] == ["M", "N"]
    assert rows[1]["brush_within_5ft_percent"] is None


def test_no_fire_map_on_disk_leaves_the_zone_unknown_not_false(site, monkeypatch):
    monkeypatch.setattr(exposure, "zone_at", lambda lat, lon: (None, False))
    rows = exposure.exposure(7)["buildings"]
    assert all(b["in_fire_zone"] is None and b["fire_zone"] is None for b in rows)
    assert rows[0]["id"] == "A"                                                              # the order still rests on vegetation


def test_outside_every_mapped_zone_is_false(site, monkeypatch):
    monkeypatch.setattr(exposure, "zone_at", lambda lat, lon: (None, True))
    assert all(b["in_fire_zone"] is False for b in exposure.exposure(7)["buildings"])


def test_every_fact_names_its_source_and_nothing_says_chance(site):
    out = exposure.exposure(7)
    assert set(out["sources"]) == {"vegetation", "fire_zone"} and "Vexcel" in out["sources"]["vegetation"] and "CAL FIRE" in out["sources"]["fire_zone"]
    assert not any(w in json.dumps(out).lower() for w in ("probab", "forecast", "percent burned"))


def test_a_property_that_was_never_gathered_raises(site):
    with pytest.raises(exposure.ExposureError):
        exposure.exposure(999)
