from backend import screen

OFFICE = {"construction": "Steel", "year_built": 1980, "units": None, "tenant_count": 17, "gba_sqft": 213000}
GARDEN = {"construction": "WoodFrame", "year_built": 1972, "units": 265, "tenant_count": 0, "gba_sqft": 240000}


def texts(kind, b, facts, static):
    return [s["text"] for s in screen.signals(kind, b, facts, static)]


def test_site_facts_summarises_structures_and_ignores_sheds():
    attrs = {"structures": [
        {"footprint.area": 20000, "roof-characteristics.condition": 4.0, "roof-objects.ac-unit.count": 7, "roof-characteristics.material.class": "shingle",
         "roof-characteristics.tree-cover.percent": 26.0, "defensible-space.zone1-tree": 8.0},
        {"footprint.area": 9000, "roof-characteristics.condition": 1.0, "roof-defects.tarp.detected": True, "roof-objects.ac-unit.count": 14,
         "roof-characteristics.material.class": "membrane", "roof-defects.discoloration.types.water-pooling.detected": True},
        {"footprint.area": 300, "roof-characteristics.condition": 1.0, "roof-defects.structural-damage.detected": True},  # a shed
    ]}
    f = screen._site_facts(attrs)
    assert f["structures"] == 2 and f["worst_roof"] == 1.0 and f["rooftop_units"] == 21
    assert f["serious_defects"] == ["tarp"] and f["ponding"] and f["roof_tree_cover"] == 26.0
    assert f["materials"] == ["membrane", "shingle"]


def test_hurricane_signals_order_and_wording():
    facts = {"worst_roof": 2.0, "serious_defects": ["tarp"], "rooftop_units": 12, "roof_tree_cover": 0, "skylights": 3, "ponding": True}
    static = {"fema": {"zone": "AE", "high_risk": True, "floodway": False, "subtype": None}}
    got = texts("hurricane", OFFICE, facts, static)
    assert got[:3] == ["in a high-risk flood zone (AE)", "roof condition 2 of 5", "tarp on the roof"]
    assert "12 rooftop units" in got and "3 skylights" in got and "built 1980, before modern wind codes" in got
    assert "wood-frame construction" not in got
    assert texts("hurricane", GARDEN, {}, {"fema": {"zone": "AE", "high_risk": True, "floodway": True, "subtype": "FLOODWAY"}})[0] == "in the regulatory floodway"


def test_wildfire_signals_use_vegetation_and_zone():
    facts = {"trees_within_5ft": 24.0, "roof_tree_cover": 12.0, "trees_5_to_30ft": 40.0, "materials": ["shingle"]}
    got = texts("wildfire", GARDEN, facts, {"fire_zone": "Very High", "km_to_past_fire": 1.2})
    assert got[0] == "very high fire hazard severity zone"
    assert "vegetation within 5 ft of the walls (24% cover)" in got and "wood-frame construction" in got
    assert "1.2 km from a past fire perimeter" in got
    assert not any("flood" in t for t in got)


def test_missing_data_gives_no_signals_rather_than_errors():
    assert screen.signals("hurricane", {}, None, None) == []
    assert screen.signals("wildfire", {}, None, {"fire_zone": None, "km_to_past_fire": None}) == []


def test_hours_left_and_exposure_weight():
    hur = {"kind": "hurricane", "wind_band": "strong tropical storm", "hours_until_tropical_storm_wind": 22.5}
    fire = {"kind": "wildfire", "in_warning": True, "hours_until_warning": 9.0}
    assert screen.hours_left(hur) == 22.5 and screen.hours_left(fire) == 9.0
    assert screen._exposure_weight(hur) == 2.0 and screen._exposure_weight({"kind": "hurricane", "wind_band": "below tropical storm"}) == 0.0
    assert screen._exposure_weight({"kind": "wildfire", "in_warning": False}) == 0.0
    assert screen._people(GARDEN) > screen._people({"units": 10})
