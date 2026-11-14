"""Offline tests for backend.hazards.

Source text (NHC advisories, NWS fire weather products) is real and lives in
tests/test_hazards_samples.py. Geometry used to exercise point-in-polygon code
(squares, a hand-made cone) is test scaffolding and is labelled as such.
Any attempt to reach the network fails the test.
"""
from __future__ import annotations

import io
import json
import math
import time
import zipfile

import httpx
import pytest
from shapely.geometry import Point, shape

from backend import hazards
from backend.hazards import alerts, fireweather, net, nhc, registry, static, wind
from backend.hazards.errors import HazardError
from tests import test_hazards_samples as samples

REAL_GET = net.get
DOWNTOWN_HOUSTON = (29.7604, -95.3698)
MATAGORDA = (28.69, -95.97)
PALISADES = (34.045, -118.526)
DOWNTOWN_LA = (34.0522, -118.2437)


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    """Fresh cache folder, no network, no real sleeping."""
    def no_network(*args, **kwargs):
        raise AssertionError(f"network call in a test: {args[:1]}")

    monkeypatch.setattr(net, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(net, "get", no_network)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    static._reset_for_tests()
    registry._reset_for_tests()
    yield
    static._reset_for_tests()
    registry._reset_for_tests()


def square(lat: float, lon: float, half: float = 0.05) -> dict:
    """Test scaffolding: a small square GeoJSON polygon around a point."""
    return {"type": "Polygon", "coordinates": [[
        [lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
        [lon - half, lat + half], [lon - half, lat - half]]]}


def offset(lat: float, lon: float, east_nm: float, north_nm: float) -> tuple[float, float]:
    """A point a given number of nautical miles east / north of another."""
    new_lat = lat + north_nm / 60.0
    return new_lat, lon + east_nm / (60.0 * math.cos(math.radians((lat + new_lat) / 2)))


def track_point(hours: float, lat: float, lon: float, kt: int, **radii: list[int]) -> dict:
    return {"hours_from_issue": hours, "lat": lat, "lon": lon, "wind_kt": kt,
            "radii": {k.lstrip("r"): v for k, v in radii.items()}}


# ------------------------------------------------------- NHC advisory parsing

def test_parse_forecast_advisory_reads_a_real_beryl_advisory():
    adv = nhc.parse_forecast_advisory(samples.ADVISORY_39)
    assert adv["storm_id"] == "AL022024"
    assert (adv["storm_type"], adv["storm_name"], adv["advisory"]) == ("Hurricane", "Beryl", "39")
    assert adv["issued"] == "2024-07-08T09:00:00Z"
    assert adv["center"] == [28.6, -96.0]
    assert adv["status"] == "ON COAST"
    assert (adv["max_wind_kt"], adv["gust_kt"], adv["pressure_mb"]) == (70, 85, 979)
    assert adv["dissipated"] == "2024-07-12T06:00:00Z"

    now, next_point = adv["points"][0], adv["points"][1]
    assert len(adv["points"]) == 7
    assert now["hours_from_issue"] == 0.0
    assert now["radii"] == {"64": [40, 40, 0, 0], "50": [60, 60, 30, 30], "34": [100, 100, 60, 80]}
    assert next_point["time"] == "2024-07-08T18:00:00Z" and next_point["hours_from_issue"] == 9.0
    assert (next_point["lat"], next_point["lon"], next_point["wind_kt"], next_point["gust_kt"]) == (30.4, -95.8, 55, 65)
    assert next_point["status"] == "INLAND"
    assert next_point["radii"] == {"50": [30, 30, 0, 0], "34": [50, 90, 30, 30]}
    assert adv["points"][3]["radii"] == {}                      # 25 kt: no wind radii listed
    assert adv["points"][-1]["status"] == "POST-TROP/INLAND"


def test_parse_forecast_advisory_handles_outlook_points_and_tropical_storm_title():
    adv = nhc.parse_forecast_advisory(samples.ADVISORY_35)
    assert (adv["storm_type"], adv["max_wind_kt"]) == ("Tropical Storm", 50)
    assert "64" not in adv["points"][0]["radii"]
    assert adv["points"][2]["radii"]["64"] == [20, 20, 0, 0]      # 08/0600Z, 75 kt
    assert adv["points"][-1]["time"] == "2024-07-12T06:00:00Z"     # the day-5 OUTLOOK point is kept
    assert adv["points"][-1]["hours_from_issue"] == 117.0


def test_parse_forecast_advisory_rejects_other_text():
    with pytest.raises(HazardError):
        nhc.parse_forecast_advisory("<html>404 not found</html>")


def test_advisory_day_stamps_roll_into_the_next_month():
    from datetime import datetime, timezone
    issued = datetime(2024, 7, 30, 21, 0, tzinfo=timezone.utc)
    assert nhc._resolve_day(issued, 1, 6, 0) == datetime(2024, 8, 1, 6, 0, tzinfo=timezone.utc)
    assert nhc._resolve_day(issued, 30, 21, 0) == issued


def make_cone_zip(ring: list[tuple[float, float]]) -> bytes:
    """Test scaffolding: an NHC-style 5-day zip holding one cone polygon."""
    import shapefile

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    writer.field("STORMNAME", "C", 20)
    writer.poly([ring])
    writer.record("Beryl")
    writer.close()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for ext, buf in (("shp", shp), ("shx", shx), ("dbf", dbf)):
            archive.writestr(f"al022024-039_5day_pgn.{ext}", buf.getvalue())
    return out.getvalue()


# Counter-clockwise, as NHC writes it; covers the Texas coast from Matagorda to Houston.
CONE_RING = [(-97.0, 28.0), (-94.9, 28.0), (-94.9, 31.0), (-97.0, 31.0), (-97.0, 28.0)]


def test_read_cone_zip_returns_a_polygon_whatever_the_ring_direction():
    for ring in (CONE_RING, CONE_RING[::-1]):
        cone = nhc.read_cone_zip(make_cone_zip(ring))["cone"]
        assert cone["type"] == "Polygon"
        assert shape(cone).contains(Point(DOWNTOWN_HOUSTON[1], DOWNTOWN_HOUSTON[0]))
    with pytest.raises(HazardError):
        nhc.read_cone_zip(b"not a zip")


# ------------------------------------------------------------ wind exposure

STILL = [  # a storm that does not move, with different radii in every quadrant
    track_point(0, 25.0, -90.0, 80, r64=[40, 30, 20, 10], r50=[80, 60, 40, 20], r34=[120, 90, 60, 30]),
    track_point(6, 25.0, -90.0, 80, r64=[40, 30, 20, 10], r50=[80, 60, 40, 20], r34=[120, 90, 60, 30]),
]


def exposure_at(points: list[dict], east_nm: float, north_nm: float) -> dict:
    lat, lon = offset(points[0]["lat"], points[0]["lon"], east_nm, north_nm)
    return wind.point_exposure(wind.build_samples(points), lat, lon)


def test_wind_bands_follow_the_quadrant_radii():
    ne = exposure_at(STILL, 20, 20)            # 28.3 nm out, NE 64 kt radius is 40
    assert ne["wind_band"] == "hurricane" and ne["peak_wind_kt"] == 68
    assert ne["wind_basis"] == "inside the forecast 64 kt wind radius"
    assert ne["hours_until_tropical_storm_wind"] == 0.0

    sw = exposure_at(STILL, -21.2132, -21.2132)  # 30 nm out, SW radii 20 / 40 / 60: halfway from 64 to 50 kt
    assert sw["wind_band"] == "strong tropical storm" and sw["peak_wind_kt"] in (56, 57)

    nw = exposure_at(STILL, -17.6777, 17.6777)   # 25 nm out, NW radii 10 / 20 / 30
    assert nw["wind_band"] == "tropical storm" and nw["peak_wind_kt"] in (41, 42)
    assert nw["peak_wind_mph"] == round(nw["peak_wind_kt"] * 1.15078)

    far = exposure_at(STILL, -42.4264, 42.4264)  # 60 nm out to the NW, beyond the 30 nm radius
    assert far["wind_band"] == "below tropical storm" and far["peak_wind_kt"] == 24  # 34 * sqrt(30 / 60)
    assert far["hours_until_tropical_storm_wind"] is None
    assert "extrapolation" in far["wind_basis"]
    assert far["closest_approach_km"] == pytest.approx(60 * 1.852, abs=0.5)


def test_a_zero_radius_in_a_quadrant_keeps_the_estimate_below_that_threshold():
    landfall = [track_point(h, 28.6, -96.0, 70, r64=[40, 40, 0, 0], r50=[60, 60, 30, 30], r34=[100, 100, 60, 80])
                for h in (0, 6)]
    just_sw = exposure_at(landfall, -2, -2)
    assert just_sw["wind_band"] == "strong tropical storm" and just_sw["peak_wind_kt"] < 64
    assert exposure_at(landfall, 2, 2)["wind_band"] == "hurricane"


def test_missing_radii_for_a_threshold_the_storm_exceeds_do_not_cap_the_estimate():
    # NHC gives no 64 kt radii beyond 48 hours even for a forecast hurricane.
    day3 = [track_point(h, 26.0, -97.1, 75, r50=[40, 35, 20, 30], r34=[100, 70, 60, 80]) for h in (0, 6)]
    near = exposure_at(day3, 1.5, 1.5)
    assert near["wind_band"] == "hurricane" and near["peak_wind_kt"] <= 75
    assert exposure_at(day3, 25, 25)["wind_band"] == "strong tropical storm"


def test_arrival_time_closest_approach_and_track_side():
    north = [track_point(0, 25.0, -90.0, 45, r34=[60, 60, 60, 60]),      # 120 nm in 12 h = 10 kt due north
             track_point(12, 27.0, -90.0, 45, r34=[60, 60, 60, 60])]
    s = wind.build_samples(north)
    ahead = wind.point_exposure(s, 27.0, -90.0)
    assert ahead["hours_until_tropical_storm_wind"] == pytest.approx(6.0, abs=0.2)
    assert ahead["peak_wind_kt"] == 45 and ahead["wind_band"] == "tropical storm"
    assert ahead["closest_approach_km"] == pytest.approx(0.0, abs=0.5)
    assert ahead["hours_until_closest_approach"] == 12.0
    assert wind.point_exposure(s, 26.0, -89.5)["track_side"] == "right"   # east of a northbound storm
    assert wind.point_exposure(s, 26.0, -90.5)["track_side"] == "left"
    assert wind.point_exposure(s, 26.0, -89.5)["closest_approach_km"] == pytest.approx(0.5 * 60 * math.cos(math.radians(26)) * 1.852, abs=1.0)


def test_real_beryl_advisories_give_sensible_houston_numbers():
    at_landfall = wind.build_samples(nhc.parse_forecast_advisory(samples.ADVISORY_39)["points"])
    houston = wind.point_exposure(at_landfall, *DOWNTOWN_HOUSTON)
    assert houston["wind_band"] == "strong tropical storm" and 50 <= houston["peak_wind_kt"] < 64
    assert houston["track_side"] == "right" and houston["hours_until_tropical_storm_wind"] == 0.0
    assert 30 < houston["closest_approach_km"] < 70
    assert wind.point_exposure(at_landfall, *MATAGORDA)["wind_band"] == "hurricane"

    day_before = wind.build_samples(nhc.parse_forecast_advisory(samples.ADVISORY_35)["points"])
    houston = wind.point_exposure(day_before, *DOWNTOWN_HOUSTON)
    assert houston["wind_band"] == "tropical storm"
    assert 18 < houston["hours_until_tropical_storm_wind"] < 26


def test_swath_polygons_cover_what_the_radii_cover():
    s = wind.build_samples(nhc.parse_forecast_advisory(samples.ADVISORY_39)["points"])
    swath = wind.swath_polygons(s)
    houston = Point(DOWNTOWN_HOUSTON[1], DOWNTOWN_HOUSTON[0])
    assert shape(swath[34]).contains(houston) and shape(swath[50]).contains(houston)
    assert not shape(swath[64]).contains(houston)
    assert shape(swath[64]).contains(Point(MATAGORDA[1], MATAGORDA[0]))
    weak = wind.build_samples([track_point(0, 35.0, -92.1, 25), track_point(12, 37.5, -89.0, 20)])
    assert wind.swath_polygons(weak) == {34: None, 50: None, 64: None}


# --------------------------------------------------- fire weather products

def test_expand_ugc_and_vtec():
    assert fireweather.expand_ugc("CAZ288-358-369>371-062245-") == ["CAZ288", "CAZ358", "CAZ369", "CAZ370", "CAZ371"]
    assert fireweather.expand_ugc("CAZ381>383-NVZ001-090200-") == ["CAZ381", "CAZ382", "CAZ383", "NVZ001"]
    new, already = fireweather.parse_vtec(
        "/O.NEW.KLOX.FW.W.0001.250107T1800Z-250110T0200Z/\n/O.CON.KLOX.FW.W.0001.000000T0000Z-250110T0200Z/")
    assert new == {"action": "NEW", "office": "KLOX", "phenomenon": "FW", "significance": "W", "etn": 1,
                   "start": "2025-01-07T18:00:00Z", "end": "2025-01-10T02:00:00Z"}
    assert already["start"] is None and already["action"] == "CON"


def test_parse_wind_text():
    w = fireweather.parse_wind("Most Likely Outcome-Strong/damaging north to northeast wind event with sustained "
                               "winds of 35 to 55 mph and widespread damaging wind gusts of 50 to 80 mph. Isolated "
                               "gusts of 80 to 100 mph in most favored areas likely.")
    assert (w["gust_mph"], w["gust_range_mph"], w["peak_gust_mph"], w["direction"]) == (80, [50, 80], 100, "north to northeast")
    w = fireweather.parse_wind("Northeast 20 to 30 mph with gusts 45 to 55 mph, strongest in the northern foothills.")
    assert (w["gust_mph"], w["direction"]) == (55, "northeast")
    assert fireweather.parse_wind("Northeast 20 to 35 mph with damaging gusts to 70 mph.")["gust_mph"] == 70
    assert fireweather.parse_wind("Humidity 5 to 10 percent.") is None


def test_parse_rfw_product_reads_a_real_red_flag_warning():
    product = fireweather.parse_rfw_product(samples.RFW_JAN5_2240Z)
    assert product["issued"] == "2025-01-05T22:40:00Z"            # 240 PM PST Sun Jan 5 2025
    assert product["headline"].startswith("WIDESPREAD DAMAGING NORTH TO NORTHEAST WINDS")
    assert product["pds"] is False
    warned, watch_only = product["segments"]
    assert warned["ugcs"] == ["CAZ288", "CAZ358", "CAZ362", "CAZ369", "CAZ370", "CAZ371", "CAZ372", "CAZ373",
                              "CAZ374", "CAZ376", "CAZ378", "CAZ548"]
    assert [(v["action"], v["significance"]) for v in warned["vtec"]] == [("NEW", "W"), ("EXT", "A")]
    assert warned["headline"].startswith("RED FLAG WARNING IN EFFECT FROM 10 AM TUESDAY TO 6 PM PST THURSDAY")
    assert (warned["wind"]["gust_mph"], warned["wind"]["peak_gust_mph"]) == (80, 100)
    assert watch_only["ugcs"] == ["CAZ287", "CAZ366", "CAZ367", "CAZ368"]
    assert watch_only["wind"]["gust_mph"] == 60
    with pytest.raises(HazardError):
        fireweather.parse_rfw_product("nothing to see", issued="2025-01-05T22:40:00Z")


def january_steps() -> list[dict]:
    texts = (samples.RFW_JAN5_2240Z, samples.RFW_JAN6_1955Z, samples.RFW_JAN6_2324Z, samples.RFW_JAN7_2237Z)
    return fireweather.replay([fireweather.parse_rfw_product(t) for t in texts])


def zone(step: dict, ugc: str, sig: str = "W") -> dict | None:
    return next((z for z in step["zones"] if z["ugc"] == ugc and z["sig"] == sig), None)


def test_replay_rebuilds_the_warning_as_it_stood_after_each_product():
    first, second, third, fourth = january_steps()
    assert [s["issued"] for s in (first, second, third, fourth)] == [
        "2025-01-05T22:40:00Z", "2025-01-06T19:55:00Z", "2025-01-06T23:24:00Z", "2025-01-07T22:37:00Z"]

    # 5 Jan: Malibu Coast warned from 10 AM Tuesday; downtown LA only under a watch.
    malibu = zone(first, "CAZ362")
    assert (malibu["start"], malibu["end"], malibu["gust_mph"]) == ("2025-01-07T18:00:00Z", "2025-01-10T02:00:00Z", 80)
    assert zone(first, "CAZ368") is None and zone(first, "CAZ368", "A")["start"] == "2025-01-08T02:00:00Z"

    # 6 Jan morning: the watch for the coast is upgraded, and the main warning starts earlier.
    assert zone(second, "CAZ368", "A") is None
    downtown = zone(second, "CAZ368")
    assert (downtown["start"], downtown["end"], downtown["gust_mph"]) == ("2025-01-08T00:00:00Z", "2025-01-09T02:00:00Z", 60)
    assert zone(second, "CAZ362")["start"] == "2025-01-07T12:00:00Z"
    assert not second["pds"]

    # 6 Jan afternoon: "particularly dangerous situation" declared; downtown timing changes.
    assert third["pds"] and zone(third, "CAZ362")["pds"] and zone(third, "CAZ368")["pds"]
    assert (zone(third, "CAZ368")["start"], zone(third, "CAZ368")["end"]) == ("2025-01-07T20:00:00Z", "2025-01-09T00:00:00Z")

    # 7 Jan: VTEC start 000000T0000Z means "already in effect": the earlier start is kept, and so is PDS.
    assert zone(fourth, "CAZ362")["start"] == "2025-01-07T12:00:00Z"
    assert zone(fourth, "CAZ362")["pds"] and fourth["pds"]


def test_zone_exposure_and_step_labels():
    first, _second, _third, fourth = january_steps()
    e = fireweather.zone_exposure(first["issued"], [z for z in first["zones"] if z["ugc"] == "CAZ362"])
    assert (e["in_warning"], e["hours_until_warning"], e["warning_hours"]) == (True, 43.3, 56.0)
    e = fireweather.zone_exposure(first["issued"], [z for z in first["zones"] if z["ugc"] == "CAZ368"])
    assert (e["in_warning"], e["in_watch"], e["hours_until_warning"], e["warning_hours"]) == (False, True, None, None)
    e = fireweather.zone_exposure(fourth["issued"], [z for z in fourth["zones"] if z["ugc"] == "CAZ362"])
    assert (e["hours_until_warning"], e["warning_hours"], e["pds"]) == (0.0, 51.4, True)
    assert fireweather.zone_exposure(first["issued"], []) == {
        "kind": "wildfire", "in_warning": False, "hours_until_warning": None, "warning_hours": None,
        "in_watch": False, "zone": None, "zone_name": None, "gust_mph": None, "pds": False}
    assert fireweather.warning_label(first["issued"], first["zones"], first["pds"]) == "43 hours before the Red Flag Warning starts"
    assert fireweather.warning_label(fourth["issued"], fourth["zones"], fourth["pds"]) == \
        "Red Flag Warning in effect (particularly dangerous situation)"
    assert fireweather.step_wind(first["zones"])["gust_mph"] == 80


# ------------------------------------------------- scenarios through the API

@pytest.fixture
def replays(monkeypatch):
    """Both replays built from the real sample text, with scaffolding geometry and no network."""
    monkeypatch.setitem(registry.BERYL, "advisories", [35, 39])
    monkeypatch.setattr(nhc, "fetch_archived_advisory",
                        lambda storm, adv: {35: samples.ADVISORY_35, 39: samples.ADVISORY_39}[adv])
    monkeypatch.setattr(nhc, "fetch_archived_cone", lambda storm, adv: make_cone_zip(CONE_RING))

    def iem(kind: str, significance: str) -> dict:
        if kind == "geo":
            return {"features": [{"id": "CAZ362", "geometry": square(*PALISADES)},
                                 {"id": "CAZ368", "geometry": square(*DOWNTOWN_LA)}]}
        texts = [(samples.RFW_JAN5_2240Z, "2025-01-05T22:40:00Z"), (samples.RFW_JAN6_1955Z, "2025-01-06T19:55:00Z"),
                 (samples.RFW_JAN6_2324Z, "2025-01-06T23:24:00Z"), (samples.RFW_JAN7_2237Z, "2025-01-07T22:37:00Z")]
        products = [{"text": text, "valid": valid} for text, valid in texts]
        return {"event_exists": True, "report": products[0], "svs": products[1:],
                "ugcs": [{"ugc": "CAZ362", "name": "Malibu Coast"},
                         {"ugc": "CAZ368", "name": "Los Angeles County Inland Coast including Downtown Los Angeles"}]}

    monkeypatch.setattr(registry, "_iem", iem)
    monkeypatch.setattr(registry, "_january_2025_fires", lambda: [])


def test_scenarios_lists_both_replays_with_steps(replays, monkeypatch):
    listed = hazards.scenarios(include_live=False)
    assert [s["id"] for s in listed] == ["beryl-2024", "la-red-flag-jan-2025"]
    beryl, la = listed
    assert (beryl["kind"], beryl["city"], beryl["live"]) == ("hurricane", "Houston", False)
    assert beryl["steps"] == [
        {"id": "adv35", "issued": "2024-07-07T09:00:00Z", "label": "24 hours before landfall"},
        {"id": "adv39", "issued": "2024-07-08T09:00:00Z", "label": "Landfall near Matagorda, Texas"}]
    assert (la["kind"], la["city"]) == ("wildfire", "Los Angeles")
    assert [s["id"] for s in la["steps"]] == ["20250105T2240Z", "20250106T1955Z", "20250106T2324Z", "20250107T2237Z"]
    assert la["steps"][0]["label"] == "43 hours before the Red Flag Warning starts"
    assert (net.CACHE_ROOT / "scenarios" / "beryl-2024.json").exists()   # built once, then read from disk

    registry._reset_for_tests()
    for name in ("fetch_archived_advisory", "fetch_archived_cone"):
        monkeypatch.setattr(nhc, name, lambda *a: pytest.fail("rebuilt instead of reading the cached scenario"))
    assert len(hazards.scenarios(include_live=False)) == 2


def test_hurricane_scenario_and_exposure_shapes(replays):
    view = hazards.scenario("beryl-2024")
    assert (view["kind"], view["step_id"], view["issued"]) == ("hurricane", "adv39", "2024-07-08T09:00:00Z")
    assert view["center"] == [28.6, -96.0] and view["max_wind_kt"] == 70
    assert view["track"][1] == {"time": "2024-07-08T18:00:00Z", "lat": 30.4, "lon": -95.8, "wind_kt": 55,
                                "hours_from_issue": 9.0, "gust_kt": 65, "status": "INLAND",
                                "radii_nm": {"50": [30, 30, 0, 0], "34": [50, 90, 30, 30]}}
    assert view["cone"]["type"] == "Polygon"
    assert [f["kt"] for f in view["wind_fields"]] == [34, 50, 64]
    assert view["landfall"]["time"] == "2024-07-08T09:00:00Z" and view["landfall"]["lat"] == 28.6
    json.dumps(view)                                                      # everything is plain JSON

    e = hazards.exposure("beryl-2024", *DOWNTOWN_HOUSTON)
    assert set(e) >= {"kind", "peak_wind_kt", "peak_wind_mph", "wind_band", "hours_until_tropical_storm_wind",
                      "closest_approach_km", "track_side", "in_cone"}
    assert (e["kind"], e["wind_band"], e["track_side"], e["in_cone"]) == ("hurricane", "strong tropical storm", "right", True)
    earlier = hazards.exposure("beryl-2024", *DOWNTOWN_HOUSTON, step_id="adv35")
    assert earlier["wind_band"] == "tropical storm" and earlier["hours_until_tropical_storm_wind"] > 18
    assert hazards.exposure("beryl-2024", 32.78, -96.80)["in_cone"] is False   # Dallas, outside the test cone

    with pytest.raises(HazardError):
        hazards.scenario("beryl-2024", "adv99")
    with pytest.raises(HazardError):
        hazards.exposure("no-such-scenario", *DOWNTOWN_HOUSTON)


def test_wildfire_scenario_and_point_in_polygon_exposure(replays):
    sid = "la-red-flag-jan-2025"
    first = hazards.scenario(sid, "20250105T2240Z")
    assert first["kind"] == "wildfire" and first["issued"] == "2025-01-05T22:40:00Z"
    assert len(first["warning_polygons"]) == 1 and first["warning_zones"][0]["ugc"] == "CAZ362"
    assert {z["ugc"] for z in first["watch_zones"]} == {"CAZ362", "CAZ368"}
    assert first["warning_text"].startswith("WIDESPREAD DAMAGING NORTH TO NORTHEAST WINDS")
    assert (first["wind"]["gust_mph"], first["wind"]["direction"]) == (80, "north to northeast")
    assert first["fire_perimeters"] == []

    palisades = hazards.exposure(sid, *PALISADES, step_id="20250105T2240Z")
    assert palisades == {"kind": "wildfire", "in_warning": True, "hours_until_warning": 43.3, "warning_hours": 56.0,
                         "in_watch": True, "zone": "CAZ362", "zone_name": "Malibu Coast", "gust_mph": 80, "pds": False}
    downtown = hazards.exposure(sid, *DOWNTOWN_LA, step_id="20250105T2240Z")
    assert (downtown["in_warning"], downtown["in_watch"], downtown["hours_until_warning"]) == (False, True, None)
    nowhere = hazards.exposure(sid, 36.0, -120.0, step_id="20250105T2240Z")          # outside every zone
    assert (nowhere["in_warning"], nowhere["in_watch"], nowhere["zone"]) == (False, False, None)

    latest = hazards.scenario(sid)                                                    # default is the last step
    assert latest["step_id"] == "20250107T2237Z" and latest["pds"] is True
    assert len(latest["warning_polygons"]) == 2
    downtown = hazards.exposure(sid, *DOWNTOWN_LA)
    assert (downtown["in_warning"], downtown["hours_until_warning"], downtown["warning_hours"]) == (True, 0.0, 25.4)


def test_scenarios_leaves_out_a_replay_that_cannot_be_built(monkeypatch):
    def down(*args, **kwargs):
        raise HazardError("offline")
    monkeypatch.setattr(net, "get", down)
    assert hazards.scenarios(include_live=False) == []
    with pytest.raises(HazardError):
        hazards.scenario("beryl-2024")


# ---------------------------------------------------------- live scenarios

def test_live_hurricane_near_houston_becomes_a_scenario(replays, monkeypatch):
    storm = {"id": "al022024", "name": "Beryl", "forecastAdvisory": {"url": "https://nhc.invalid/MIATCMAT2.shtml"},
             "trackCone": {"zipFile": "https://nhc.invalid/cone.zip"}}
    monkeypatch.setattr(nhc, "active_storms", lambda **kw: [storm, {"id": "ep012024"}])
    monkeypatch.setattr(net, "get_text", lambda url, *a, **kw: f"<html><pre>{samples.ADVISORY_39}</pre></html>")
    monkeypatch.setattr(net, "get_bytes", lambda url, *a, **kw: make_cone_zip(CONE_RING))
    monkeypatch.setattr(alerts, "fire_weather_alerts", lambda state="CA": [])

    live = [s for s in hazards.scenarios() if s["live"]]
    assert [(s["id"], s["kind"], s["city"], s["name"]) for s in live] == [("live-al022024", "hurricane", "Houston", "Hurricane Beryl")]
    assert live[0]["steps"] == [{"id": "adv39", "issued": "2024-07-08T09:00:00Z", "label": "Latest forecast"}]
    assert hazards.exposure("live-al022024", *DOWNTOWN_HOUSTON)["wind_band"] == "strong tropical storm"
    assert hazards.scenario("live-al022024")["landfall"] is None
    status = hazards.live_status()
    assert status["houston"]["active"] is True and status["los_angeles"]["active"] is False


def test_live_storm_far_from_houston_is_not_listed(replays, monkeypatch):
    far = samples.ADVISORY_39
    for lat in ("28.6N", "28.2N", "30.4N", "32.7N", "35.0N", "37.5N", "40.0N", "42.0N"):
        far = far.replace(lat, "12.0N")                       # scaffolding: park every position in the deep tropics
    for lon in ("96.0W", "95.9W", "95.8W", "94.4W", "92.1W", "89.0W", "85.8W", "83.0W"):
        far = far.replace(lon, "40.0W")
    monkeypatch.setattr(nhc, "active_storms", lambda **kw: [{"id": "al022024", "forecastAdvisory": {"url": "https://nhc.invalid/x"}}])
    monkeypatch.setattr(net, "get_text", lambda url, *a, **kw: f"<pre>{far}</pre>")
    monkeypatch.setattr(alerts, "fire_weather_alerts", lambda state="CA": [])
    assert [s for s in hazards.scenarios() if s["live"]] == []
    assert "none is forecast near Houston" in hazards.live_status()["houston"]["summary"]


def test_live_red_flag_warning_becomes_a_scenario(replays, monkeypatch):
    alert = {"properties": {  # scaffolding in the shape api.weather.gov returns
        "event": "Red Flag Warning", "sent": "2026-11-14T02:00:00-08:00", "onset": "2026-11-14T10:00:00-08:00",
        "ends": "2026-11-15T18:00:00-08:00", "expires": "2026-11-14T12:00:00-08:00",
        "headline": "Red Flag Warning issued November 14 at 2:00AM PST until November 15 at 6:00PM PST by NWS Los Angeles/Oxnard CA",
        "description": "* WINDS...Northeast 20 to 30 mph with gusts to 55 mph.\n\n* RELATIVE HUMIDITY...8 to 15 percent.",
        "affectedZones": ["https://api.weather.gov/zones/fire/CAZ362", "https://api.weather.gov/zones/fire/CAZ999"]}}
    zones = {"CAZ362": {"name": "Malibu Coast", "geometry": square(*PALISADES)},
             "CAZ999": {"name": "Far away", "geometry": square(40.0, -122.0)}}
    monkeypatch.setattr(nhc, "active_storms", lambda **kw: [])
    monkeypatch.setattr(alerts, "fire_weather_alerts", lambda state="CA": [alert])
    monkeypatch.setattr(alerts, "zone_geometry", lambda url: zones[url.rsplit("/", 1)[-1]])

    live = [s for s in hazards.scenarios() if s["live"]]
    assert [(s["id"], s["kind"], s["city"]) for s in live] == [("live-la-fire-weather", "wildfire", "Los Angeles")]
    assert live[0]["steps"] == [{"id": "now", "issued": "2026-11-14T10:00:00Z", "label": "Live now"}]
    view = hazards.scenario("live-la-fire-weather")
    assert len(view["warning_polygons"]) == 1 and view["wind"] == {
        "gust_mph": 55, "peak_gust_mph": 55, "direction": "northeast",
        "text": "Northeast 20 to 30 mph with gusts to 55 mph."}
    e = hazards.exposure("live-la-fire-weather", *PALISADES)
    assert (e["in_warning"], e["hours_until_warning"], e["warning_hours"], e["gust_mph"]) == (True, 8.0, 32.0, 55)
    assert hazards.exposure("live-la-fire-weather", *DOWNTOWN_LA)["in_warning"] is False
    assert "no active tropical cyclones" in hazards.live_status()["houston"]["summary"]


def test_live_check_failure_is_soft(replays, monkeypatch):
    def down(*args, **kwargs):
        raise HazardError("api.weather.gov request failed (ConnectTimeout)")
    monkeypatch.setattr(nhc, "active_storms", down)
    monkeypatch.setattr(alerts, "fire_weather_alerts", down)
    assert [s["id"] for s in hazards.scenarios()] == ["beryl-2024", "la-red-flag-jan-2025"]
    status = hazards.live_status()
    assert status["houston"]["unavailable"] and status["los_angeles"]["unavailable"]
    with pytest.raises(HazardError):
        hazards.scenario("live-al022024")


# ------------------------------------------------------------- static risk

FEMA_FLOODWAY = {  # real response for 17202 Imperial Valley Dr, Houston (-95.404, 29.951), fields list trimmed
    "displayFieldName": "FLD_AR_ID",
    "features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": "FLOODWAY", "SFHA_TF": "T", "STATIC_BFE": -9999.0}}]}
FEMA_500_YEAR = {"features": [{"attributes": {
    "FLD_ZONE": "X", "ZONE_SUBTY": "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", "SFHA_TF": "F", "STATIC_BFE": -9999.0}}]}
FEMA_COASTAL = {"features": [{"attributes": {"FLD_ZONE": "AE", "ZONE_SUBTY": None, "SFHA_TF": "T", "STATIC_BFE": 12.0}}]}


def test_fema_response_mapping():
    assert static.map_fema_response(FEMA_FLOODWAY) == {
        "zone": "AE", "subtype": "FLOODWAY", "high_risk": True, "floodway": True,
        "base_flood_elevation_ft": None, "moderate_risk": False}
    assert static.map_fema_response(FEMA_500_YEAR) == {
        "zone": "X", "subtype": "0.2 PCT ANNUAL CHANCE FLOOD HAZARD", "high_risk": False, "floodway": False,
        "base_flood_elevation_ft": None, "moderate_risk": True}
    coastal = static.map_fema_response(FEMA_COASTAL)
    assert (coastal["zone"], coastal["subtype"], coastal["high_risk"], coastal["base_flood_elevation_ft"]) == ("AE", None, True, 12.0)
    assert static.map_fema_response({"features": []}) is None
    both = {"features": FEMA_500_YEAR["features"] + FEMA_FLOODWAY["features"]}
    assert static.map_fema_response(both)["floodway"] is True            # the riskiest overlapping zone wins
    metres = {"features": [{"attributes": {"FLD_ZONE": "AE", "SFHA_TF": "T", "STATIC_BFE": 3.0, "LEN_UNIT": "Meters"}}]}
    assert static.map_fema_response(metres)["base_flood_elevation_ft"] == 9.8
    with pytest.raises(HazardError):
        static.map_fema_response({"error": {"code": 500, "message": "Error performing query operation"}})


def test_static_risk_cached_only_never_fetches():
    assert hazards.static_risk(*DOWNTOWN_HOUSTON, cached_only=True) == {"fema": None, "fire_zone": None, "km_to_past_fire": None}
    assert hazards.static_risk(*PALISADES, cached_only=True) == {"fema": None, "fire_zone": None, "km_to_past_fire": None}
    assert not (net.CACHE_ROOT / "static" / "points.json").exists()


def test_static_risk_fetches_once_then_serves_from_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(net, "get_json", lambda url, params=None, **kw: calls.append(params["geometry"]) or FEMA_FLOODWAY)
    lat, lon = 29.951, -95.404
    first = hazards.static_risk(lat, lon)
    assert first["fema"]["floodway"] is True and first["fire_zone"] is None and first["km_to_past_fire"] is None
    assert calls == ["-95.404,29.951"]
    assert hazards.static_risk(lat, lon) == first and len(calls) == 1
    assert hazards.static_risk(lat + 0.000004, lon, cached_only=True) == first      # same point to 5 decimals

    static._reset_for_tests()                                                         # a new process reads the file
    monkeypatch.setattr(net, "get_json", lambda *a, **kw: pytest.fail("should come from disk"))
    assert hazards.static_risk(lat, lon, cached_only=True) == first


def test_static_risk_failure_is_soft_and_not_cached(monkeypatch):
    def down(*args, **kwargs):
        raise HazardError("hazards.fema.gov request failed (HTTP 503)")
    monkeypatch.setattr(net, "get_json", down)
    assert hazards.static_risk(*DOWNTOWN_HOUSTON) == {"fema": None, "fire_zone": None, "km_to_past_fire": None}
    monkeypatch.setattr(net, "get_json", lambda *a, **kw: FEMA_500_YEAR)
    assert hazards.static_risk(*DOWNTOWN_HOUSTON)["fema"]["moderate_risk"] is True     # retried, not remembered as unknown


def fake_la_index() -> dict:
    """Test scaffolding: one 'Very High' square at Pacific Palisades and two fire perimeters near it."""
    from shapely import STRtree

    zones = [shape(square(*PALISADES, half=0.02))]
    fires = [static._to_km(shape(square(34.045, -118.426, half=0.01))),               # about 8 km east, 1993
             static._to_km(shape(square(*PALISADES, half=0.03)))]                     # covers the point, 2025
    meta = [{"name": "Old", "year": 1993, "acres": 500}, {"name": "Palisades", "year": 2025, "acres": 23449}]
    return {"zone_tree": STRtree(zones), "zone_meta": [{"zone": "Very High", "area": "LRA"}],
            "fire_tree": STRtree(fires), "fire_km": fires, "fire_meta": meta,
            "old_tree": STRtree(fires[:1]), "old_index": [0]}


def test_los_angeles_fire_lookup_is_local(monkeypatch):
    monkeypatch.setattr(static, "_load_la", lambda allow_download: fake_la_index())
    risk = hazards.static_risk(*PALISADES, cached_only=True)                          # no network needed
    assert risk["fire_zone"] == "Very High" and risk["fema"] is None
    assert risk["km_to_past_fire"] == 0.0 and risk["past_fire"]["name"] == "Palisades"
    assert risk["fire_before_2025"]["name"] == "Old" and 7.0 < risk["km_to_fire_before_2025"] < 9.0
    outside = hazards.static_risk(34.045, -118.30, cached_only=True)
    assert outside["fire_zone"] is None and outside["km_to_past_fire"] > 5


def test_warm_static_skips_cached_points_and_irrelevant_lookups(monkeypatch):
    fema_calls = []
    monkeypatch.setattr(static, "fetch_fema", lambda lat, lon: fema_calls.append((lat, lon)) or {"zone": "X"})
    monkeypatch.setattr(static, "fetch_fire_zone_point", lambda lat, lon: pytest.fail("no point query expected"))
    monkeypatch.setattr(static, "_load_la", lambda allow_download: fake_la_index())
    points = [DOWNTOWN_HOUSTON, (29.3013, -94.7977), DOWNTOWN_HOUSTON, PALISADES]
    log: list[str] = []
    assert hazards.warm_static(points, log=log.append) == 3                           # the duplicate is skipped
    assert fema_calls == [DOWNTOWN_HOUSTON, (29.3013, -94.7977)]                      # no FEMA call for Los Angeles
    assert hazards.static_risk(*PALISADES, cached_only=True)["fire_zone"] == "Very High"
    assert hazards.static_risk(*DOWNTOWN_HOUSTON, cached_only=True)["fema"] == {"zone": "X"}
    assert hazards.warm_static(points, log=log.append) == 0 and len(fema_calls) == 2  # all cached now
    assert json.loads((net.CACHE_ROOT / "static" / "points.json").read_text()).keys() == {
        "29.76040,-95.36980", "29.30130,-94.79770", "34.04500,-118.52600"}
    assert any("3 of 3 points need a lookup" in line for line in log)


def test_warm_static_backs_off_and_stops_when_the_service_is_down(monkeypatch):
    attempts, pauses = [], []

    def down(lat, lon):
        attempts.append((lat, lon))
        raise HazardError("hazards.fema.gov request failed (HTTP 503)")
    monkeypatch.setattr(static, "fetch_fema", down)
    monkeypatch.setattr(time, "sleep", pauses.append)
    points = [(29.70 + i / 100, -95.40) for i in range(12)]
    assert hazards.warm_static(points, log=lambda _m: None) == 0
    assert len(attempts) == 15                                  # 3 tries each for 5 points, then it gives up
    assert pauses[:3] == [5.0, 10.0, 20.0]
    assert hazards.static_risk(*points[0], cached_only=True)["fema"] is None


# -------------------------------------------------------------- live alerts

NWS_ALERT = {"properties": {  # real alert from api.weather.gov on 14 Nov 2026, description shortened
    "id": "urn:oid:2.49.0.1.840.0.a511b79eef9e40c20b5e31f137aae53f00caeaed.003.1",
    "event": "High Surf Advisory", "severity": "Minor",
    "headline": "High Surf Advisory issued November 13 at 5:35PM PST until November 17 at 3:00PM PST by NWS Los Angeles/Oxnard CA",
    "effective": "2026-11-13T17:35:00-08:00", "onset": "2026-11-13T17:35:00-08:00",
    "expires": "2099-11-14T09:00:00-08:00", "ends": "2099-11-17T15:00:00-08:00",
    "senderName": "NWS Los Angeles/Oxnard CA",
    "description": "* WHAT...For the High Surf Advisory, large breaking waves of 5 to 8 feet Friday,\nincreasing to 8 to 12 feet Saturday."}}


def test_live_alerts_maps_fields_and_falls_back_to_cache(monkeypatch):
    seen = []
    monkeypatch.setattr(net, "get_json", lambda url, params=None, **kw: seen.append(params) or {"features": [NWS_ALERT]})
    got = hazards.live_alerts(*PALISADES)
    assert seen == [{"point": "34.045,-118.526"}]
    assert got == [{
        "event": "High Surf Advisory", "severity": "Minor", "headline": NWS_ALERT["properties"]["headline"],
        "onset": "2026-11-14T01:35:00Z", "expires": "2099-11-14T17:00:00Z",
        "description": "* WHAT...For the High Surf Advisory, large breaking waves of 5 to 8 feet Friday, increasing to 8 to 12 feet Saturday.",
        "ends": "2099-11-17T23:00:00Z", "sender": "NWS Los Angeles/Oxnard CA", "id": NWS_ALERT["properties"]["id"]}]
    assert hazards.live_alerts(*PALISADES) == got and len(seen) == 1                  # inside the 5 minute cache

    def down(*args, **kwargs):
        raise HazardError("api.weather.gov request failed (ConnectError)")
    monkeypatch.setattr(net, "get_json", down)
    monkeypatch.setattr(net, "file_age_s", lambda path: 3600.0)                       # cache now stale, service down
    assert hazards.live_alerts(*PALISADES) == got
    with pytest.raises(HazardError):
        hazards.live_alerts(*DOWNTOWN_HOUSTON)                                         # nothing cached for this point


def test_alert_description_is_trimmed():
    long_alert = {"properties": dict(NWS_ALERT["properties"], description="wind " * 400)}
    text = alerts.map_alert(long_alert)["description"]
    assert len(text) <= alerts.DESCRIPTION_LIMIT + 3 and text.endswith("...")


# ------------------------------------------------------------ polite HTTP

def test_get_backs_off_on_503_and_gives_up_cleanly(monkeypatch):
    replies = [503, 429, 200]
    pauses = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "brace-hackathon"
        return httpx.Response(replies.pop(0), json={"ok": True})

    monkeypatch.setattr(net, "_client", httpx.Client(transport=httpx.MockTransport(handler),
                                                     headers={"User-Agent": net.USER_AGENT}))
    monkeypatch.setattr(time, "sleep", pauses.append)
    monkeypatch.setattr(net, "get", REAL_GET)
    assert net.get_json("https://example.invalid/data") == {"ok": True}
    assert [p for p in pauses if p >= 1] == [1.5, 3.0]

    replies[:] = [500, 500, 500]
    with pytest.raises(HazardError, match="HTTP 500"):
        net.get("https://example.invalid/data")
    replies[:] = [404]
    with pytest.raises(HazardError, match="HTTP 404"):
        net.get("https://example.invalid/data")
    assert replies == []                                                               # a 404 is not retried
