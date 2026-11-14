"""A small synthetic site so tests need no network, API keys or kit data."""
from __future__ import annotations

import json

import pytest
from PIL import Image

from backend import building as building_mod

LAT0, LON0 = 29.75, -95.40
M = 111_320.0
KX = M * 0.8682  # cos(29.75 deg)


def ll(x: float, y: float) -> list[float]:
    """Local metres (east, north) to [lon, lat]."""
    return [LON0 + x / KX, LAT0 + y / M]


def rect(x0, y0, x1, y1):
    return [ll(x0, y0), ll(x1, y0), ll(x1, y1), ll(x0, y1), ll(x0, y0)]


def structure(sid, poly, **kw):
    cx = sum(p[0] for p in poly[:4]) / 4
    cy = sum(p[1] for p in poly[:4]) / 4
    return {"id": sid, "primary": sid == "S1", "footprint_sqft": 20000, "roof_material": "membrane", "roof_shape": "flat",
            "roof_condition": 2.0, "roof_defects": ["water-pooling"], "roof_objects": {"ac-unit": 6},
            "roof_tree_cover_percent": 0.0, "trees_within_5ft_percent": 5.0, "trees_5_to_30ft_percent": 10.0,
            "trees_30_to_100ft_percent": 10.0, "polygon": poly, "centroid": [cx, cy], **kw}


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(building_mod, "BUILDINGS_DIR", tmp_path)
    d = tmp_path / "7"
    d.mkdir()
    Image.new("RGB", (800, 600), (70, 80, 70)).save(d / "aerial.jpg")
    w, s = ll(-80, -60)
    e, n = ll(80, 60)
    data = {
        "version": building_mod.BUNDLE_VERSION, "id": 7,
        "record": {"id": 7, "name": "Test Plaza", "address": "1 Test Street", "city": "Houston", "state": "TX", "zip": "77000",
                   "lat": LAT0, "lon": LON0, "type": "Office", "type_label": "Office", "style": None, "year_built": 1985,
                   "renovated": None, "stories": 4, "gba_sqft": 80000, "units": None, "construction": "Masonry",
                   "sprinklers": True, "contacts": {"manager": "Acme Property Management"}, "model_ids": ["SCAN1"], "tenant_count": 2},
        "tenants": [{"name": "Northwind Dental", "employees": 12, "suite": "100"}, {"name": "Harbor Legal", "employees": 30, "suite": "300"}],
        "site": {"parcel": rect(-75, -55, 75, 55), "tree_cover_percent": 12.0, "hardscape_percent": 40.0, "vehicles_seen": 20,
                 "pool": False, "roof_analysis_date": "2025-06-01", "structure_count": 2},
        "structures": [structure("S1", rect(-60, -30, 0, 30)), structure("S2", rect(20, -20, 60, 20), roof_objects={})],
        "aerial": {"bounds": [w, s, e, n], "width": 800, "height": 600, "captured": "Fri Jan 02 18:43:55 UTC 2026",
                   "obliques": [], "grid": {"cols": 8, "rows": 6, "cell_m": 20}},
        "scans": [{"id": "SCAN1", "name": "Suite 100", "kind": "suite", "level": 1, "structure": "S1", "scanned": "2026-11-01",
                   "area_sqft": 2400, "origin": ll(-30, 0), "altitude_m": 0.0, "sdk_yaw_offset": 0.0,
                   "sweeps": [{"id": "w1", "lon": ll(-30, 0)[0], "lat": ll(-30, 0)[1], "heading": 90.0},
                              {"id": "w2", "lon": ll(-25, 5)[0], "lat": ll(-25, 5)[1], "heading": 0.0}]}],
        "frame": {"lat0": LAT0, "lon0": LON0},
    }
    (d / "building.json").write_text(json.dumps(data))
    return building_mod.Site(data)


@pytest.fixture
def threat():
    return {"scenario_id": "test-storm", "step_id": "t36", "kind": "hurricane", "name": "Hurricane Test", "label": "36 hours before landfall",
            "forecast_issued": "2024-07-06T21:00:00Z", "replay": True, "hours_left": 30.0,
            "at_this_site": {"kind": "hurricane", "peak_wind_kt": 70, "peak_wind_mph": 81, "wind_band": "hurricane",
                             "hours_until_tropical_storm_wind": 30.0, "closest_approach_km": 20, "track_side": "right", "in_cone": True},
            "standing_risk": {"fema": {"zone": "AE", "subtype": None, "high_risk": True, "floodway": False, "base_flood_elevation_ft": None},
                              "fire_zone": None, "km_to_past_fire": None}}
