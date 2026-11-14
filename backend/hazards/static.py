"""Slow-changing hazard zoning for a point: FEMA flood zone, California Fire
Hazard Severity Zone, distance to past fire perimeters.

Sources
-------
* FEMA National Flood Hazard Layer, flood hazard zones (layer 28), one point
  query per building.
* CAL FIRE / Office of the State Fire Marshal Fire Hazard Severity Zones: the
  Local Responsibility Area map dated 24 March 2025 and the State
  Responsibility Area map in force since 1 April 2024. For the Los Angeles
  metro box both are downloaded once and looked up locally; elsewhere in
  California a point query is used.
* CAL FIRE FRAP historic fire perimeters (1950 onward, 10 acres and larger),
  downloaded once for the Los Angeles metro box. Outside that box
  "km_to_past_fire" is None.

Results are kept per point (rounded to 5 decimals) in one JSON file that is
also held in memory, so cached lookups are a dictionary read.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable

from . import net
from .errors import HazardError
from .util import CALIFORNIA_BOX, LA_BOX, in_box

FEMA_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
CALFIRE = "https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services"
FHSZ_LAYERS = {
    "LRA": f"{CALFIRE}/FHSALRA25_v1_All/FeatureServer/0/query",   # local responsibility, map of 24 Mar 2025
    "SRA": f"{CALFIRE}/FHSZSRA_23_3/FeatureServer/0/query",       # state responsibility, in force 1 Apr 2024
}
PERIMETERS_URL = f"{CALFIRE}/California_Historic_Fire_Perimeters/FeatureServer/2/query"  # 1950 onward
FHSZ_NAMES = {1: "Moderate", 2: "High", 3: "Very High"}
MIN_PAST_FIRE_ACRES = 10  # smaller perimeters (a few acres of brush decades ago) are ignored for distances
_FHSZ_RANK = {"Moderate": 1, "High": 2, "Very High": 3}
RESULT_KEYS = ("fema", "fire_zone", "km_to_past_fire")
_EXTRA_KEYS = ("past_fire", "km_to_fire_before_2025", "fire_before_2025")

_lock = threading.RLock()
_points: dict[str, dict] | None = None
_points_mtime: float | None = None
_points_checked = 0.0
_dirty = False
_la: dict | None = None        # local Los Angeles lookup structures
_la_failed_at = 0.0


def point_key(lat: float, lon: float) -> str:
    return f"{round(float(lat), 5):.5f},{round(float(lon), 5):.5f}"


# ------------------------------------------------------------- point cache

def _points_path():
    return net.cache_file("static", "points.json")


def _load_points() -> dict[str, dict]:
    """In-memory point cache; reloaded if another process rewrote the file."""
    global _points, _points_mtime, _points_checked
    now = time.monotonic()
    if _points is not None and now - _points_checked < 2.0:
        return _points
    _points_checked = now
    path = _points_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _points is None or mtime != _points_mtime:
        disk = net.read_json(path) if mtime is not None else None
        disk = disk if isinstance(disk, dict) else {}
        if _points is None:
            _points = disk
        else:  # keep anything we hold that the other writer did not have
            for key, rec in disk.items():
                _points.setdefault(key, {}).update({k: v for k, v in rec.items() if k not in _points.get(key, {})})
        _points_mtime = mtime
    return _points


def _save_points() -> None:
    global _points_mtime, _dirty, _points_checked
    with _lock:
        if _points is None:
            return
        _points_checked = 0.0
        _load_points()  # merge in another writer's entries before replacing the file
        path = _points_path()
        net.write_json(path, _points)
        _points_mtime = path.stat().st_mtime
        _dirty = False


def _reset_for_tests() -> None:
    global _points, _points_mtime, _points_checked, _dirty, _la, _la_failed_at
    _points, _points_mtime, _points_checked, _dirty, _la, _la_failed_at = None, None, 0.0, False, None, 0.0


# ---------------------------------------------------------------------- FEMA

def map_fema_response(data: dict) -> dict | None:
    """Turn an NFHL flood-zone query response into the Brace shape.

    Returns None when the point is not in any mapped flood hazard area. Raises
    HazardError when the service answered with an error. If several zones
    overlap the point, the riskiest one wins (floodway, then any Special Flood
    Hazard Area, then the 0.2% zone).
    """
    if not isinstance(data, dict) or "error" in data or "features" not in data:
        detail = (data.get("error") or {}).get("message") if isinstance(data, dict) else None
        raise HazardError(f"FEMA flood map service error: {detail or 'unexpected response'}")
    best, best_rank = None, -1
    for feat in data["features"]:
        attr = feat.get("attributes") or {}
        zone = (attr.get("FLD_ZONE") or "").strip()
        if not zone:
            continue
        subtype = (attr.get("ZONE_SUBTY") or "").strip() or None
        high = (attr.get("SFHA_TF") or "").strip().upper() == "T"
        floodway = bool(subtype and "FLOODWAY" in subtype.upper())
        moderate = bool(subtype and subtype.upper().startswith("0.2 PCT"))
        bfe = attr.get("STATIC_BFE")
        bfe = float(bfe) if isinstance(bfe, (int, float)) and bfe > -9000 else None
        if bfe is not None and str(attr.get("LEN_UNIT") or "").strip().lower().startswith("met"):
            bfe = round(bfe * 3.28084, 1)
        rank = 3 if floodway else 2 if high else 1 if moderate else 0
        if rank > best_rank:
            best_rank = rank
            best = {"zone": zone, "subtype": subtype, "high_risk": high, "floodway": floodway,
                    "base_flood_elevation_ft": bfe, "moderate_risk": moderate}
    return best


def fetch_fema(lat: float, lon: float) -> dict | None:
    data = net.get_json(FEMA_URL, {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects", "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,STATIC_BFE,LEN_UNIT",
        "returnGeometry": "false", "f": "json",
    })
    return map_fema_response(data)


# ------------------------------------------------------- CAL FIRE (network)

def _arcgis_geojson(url: str, where: str, out_fields: str, box: tuple[float, float, float, float],
                    offset_deg: float, log: Callable[[str], None] | None = None) -> list[dict]:
    """All features of a layer that touch a lat/lon box, as GeoJSON features (paged)."""
    feats: list[dict] = []
    seen = 0
    while True:
        page = net.get_json(url, {
            "where": where, "geometry": f"{box[2]},{box[0]},{box[3]},{box[1]}",
            "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields, "outSR": "4326", "geometryPrecision": "5",
            "maxAllowableOffset": str(offset_deg), "orderByFields": "OBJECTID",
            "resultOffset": str(seen), "resultRecordCount": "500", "f": "geojson",
        }, timeout=net.BULK_TIMEOUT)
        if not isinstance(page, dict) or not isinstance(page.get("features"), list):
            raise HazardError(f"CAL FIRE service returned an unexpected response: {url}")
        seen += len(page["features"])
        feats += [f for f in page["features"] if f.get("geometry")]
        if log:
            log(f"  {seen} features so far")
        more = (page.get("properties") or {}).get("exceededTransferLimit") or page.get("exceededTransferLimit")
        if not more or not page["features"]:
            return feats


def download_la_fire_data(force: bool = False, log: Callable[[str], None] | None = None) -> None:
    """Download the Los Angeles box of Fire Hazard Severity Zones and past fire perimeters."""
    say = log or (lambda _msg: None)
    zones_path = net.cache_file("calfire", "fhsz_la.json")
    if force or not zones_path.exists():
        feats = []
        for area, url in FHSZ_LAYERS.items():
            say(f"CAL FIRE Fire Hazard Severity Zones ({area})...")
            for f in _arcgis_geojson(url, "FHSZ > 0", "FHSZ,FHSZ_Description,SRA", LA_BOX, 0.00005, log):
                name = FHSZ_NAMES.get((f.get("properties") or {}).get("FHSZ"))
                if name:
                    feats.append({"zone": name, "area": area, "geometry": f["geometry"]})
        if not feats:
            raise HazardError("CAL FIRE returned no Fire Hazard Severity Zones for Los Angeles")
        net.write_json(zones_path, {"box": LA_BOX, "features": feats})
    fires_path = net.cache_file("calfire", "perimeters_la.json")
    if force or not fires_path.exists():
        say("CAL FIRE historic fire perimeters (1950 onward)...")
        feats = []
        for f in _arcgis_geojson(PERIMETERS_URL, "1=1", "FIRE_NAME,YEAR_,GIS_ACRES", LA_BOX, 0.0002, log):
            p = f.get("properties") or {}
            feats.append({"name": (p.get("FIRE_NAME") or "").strip().title() or None, "year": p.get("YEAR_"),
                          "acres": round(p["GIS_ACRES"]) if isinstance(p.get("GIS_ACRES"), (int, float)) else None,
                          "geometry": f["geometry"]})
        if not feats:
            raise HazardError("CAL FIRE returned no fire perimeters for Los Angeles")
        net.write_json(fires_path, {"box": LA_BOX, "features": feats})


def fetch_fire_zone_point(lat: float, lon: float) -> str | None:
    """Fire Hazard Severity Zone by point query (used in California outside the LA box)."""
    best = None
    for url in FHSZ_LAYERS.values():
        data = net.get_json(url, {
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "FHSZ", "returnGeometry": "false", "f": "json",
        })
        if not isinstance(data, dict) or "features" not in data:
            raise HazardError("CAL FIRE Fire Hazard Severity Zone service returned an unexpected response")
        for feat in data["features"]:
            name = FHSZ_NAMES.get((feat.get("attributes") or {}).get("FHSZ"))
            if name and _FHSZ_RANK[name] > _FHSZ_RANK.get(best or "", 0):
                best = name
    return best


# --------------------------------------------------- CAL FIRE (local lookup)

_KM_PER_DEG_LAT = 110.95
_LA_COS = math.cos(math.radians((LA_BOX[0] + LA_BOX[1]) / 2))


def _to_km(geom):
    """Lon/lat geometry -> flat kilometres around Los Angeles (fine for nearest-distance work)."""
    from shapely import transform
    return transform(geom, lambda xy: xy * [111.32 * _LA_COS, _KM_PER_DEG_LAT])


def _load_la(allow_download: bool) -> dict | None:
    """Spatial indexes over the downloaded Los Angeles data, or None if unavailable."""
    global _la, _la_failed_at
    if _la is not None:
        return _la
    from shapely import STRtree
    from shapely.geometry import shape

    with _lock:
        if _la is not None:
            return _la
        zones = net.read_json(net.cache_file("calfire", "fhsz_la.json"))
        fires = net.read_json(net.cache_file("calfire", "perimeters_la.json"))
        if (zones is None or fires is None) and allow_download and time.monotonic() - _la_failed_at > 300:
            try:
                download_la_fire_data()
            except HazardError:
                _la_failed_at = time.monotonic()
                raise
            zones = net.read_json(net.cache_file("calfire", "fhsz_la.json"))
            fires = net.read_json(net.cache_file("calfire", "perimeters_la.json"))
        if zones is None or fires is None:
            return None

        def clean(features: list[dict]) -> tuple[list, list[dict]]:
            geoms, meta = [], []
            for f in features:
                try:
                    g = shape(f["geometry"])
                    g = g if g.is_valid else g.buffer(0)
                except Exception:
                    continue
                if not g.is_empty:
                    geoms.append(g)
                    meta.append({k: v for k, v in f.items() if k != "geometry"})
            return geoms, meta

        zone_geoms, zone_meta = clean(zones["features"])
        fire_geoms, fire_meta = clean([f for f in fires["features"]
                                       if (f.get("acres") or 0) >= MIN_PAST_FIRE_ACRES])
        fire_km = [_to_km(g) for g in fire_geoms]
        old = [i for i, m in enumerate(fire_meta) if isinstance(m.get("year"), int) and m["year"] < 2025]
        _la = {
            "zone_tree": STRtree(zone_geoms), "zone_meta": zone_meta,
            "fire_tree": STRtree(fire_km), "fire_km": fire_km, "fire_meta": fire_meta,
            "old_tree": STRtree([fire_km[i] for i in old]), "old_index": old,
        }
        return _la


def la_fire_lookup(lat: float, lon: float, la: dict) -> dict:
    """Fire zone and past-fire distances for a point inside the Los Angeles box (no network)."""
    from shapely.geometry import Point

    pt = Point(lon, lat)
    zone = None
    for i in la["zone_tree"].query(pt, predicate="intersects"):
        name = la["zone_meta"][int(i)]["zone"]
        if _FHSZ_RANK[name] > _FHSZ_RANK.get(zone or "", 0):
            zone = name
    out: dict = {"fire_zone": zone, "km_to_past_fire": None, "past_fire": None,
                 "km_to_fire_before_2025": None, "fire_before_2025": None}
    pk = _to_km(pt)

    def nearest(tree, index_map) -> tuple[float, dict] | None:
        hits = tree.query(pk, predicate="intersects")
        if len(hits):  # inside one or more perimeters: report the most recent
            ids = [index_map(int(i)) for i in hits]
            best = max(ids, key=lambda i: la["fire_meta"][i].get("year") or 0)
            return 0.0, la["fire_meta"][best]
        i = tree.nearest(pk)
        if i is None:
            return None
        i = index_map(int(i))
        return round(float(pk.distance(la["fire_km"][i])), 2), la["fire_meta"][i]

    hit = nearest(la["fire_tree"], lambda i: i)
    if hit:
        out["km_to_past_fire"], out["past_fire"] = hit[0], dict(hit[1])
    if la["old_index"]:
        hit = nearest(la["old_tree"], lambda i: la["old_index"][i])
        if hit:
            out["km_to_fire_before_2025"], out["fire_before_2025"] = hit[0], dict(hit[1])
    return out


# ---------------------------------------------------------------- public API

def _view(rec: dict) -> dict:
    out = {k: rec.get(k) for k in RESULT_KEYS}
    out.update({k: rec[k] for k in _EXTRA_KEYS if k in rec})
    return out


def _resolve(lat: float, lon: float, *, want_fema: bool, want_fire: bool, network: bool,
             raise_errors: bool) -> tuple[dict, bool]:
    """Fill in whatever is missing for a point. Returns (record, did_any_lookup)."""
    key = point_key(lat, lon)
    with _lock:
        rec = _load_points().get(key) or {}

    def store(values: dict) -> None:
        global _dirty
        with _lock:
            rec.update(values)
            _load_points()[key] = rec
            _dirty = True

    did = False
    if want_fire and "fire_zone" not in rec and in_box(lat, lon, CALIFORNIA_BOX):
        if in_box(lat, lon, LA_BOX):
            try:
                la = _load_la(allow_download=network)
            except HazardError:
                if raise_errors:
                    raise
                la = None
            if la is not None:
                store(la_fire_lookup(lat, lon, la))
                did = True
        elif network:
            try:
                store({"fire_zone": fetch_fire_zone_point(lat, lon)})
                did = True
            except HazardError:
                if raise_errors:
                    raise

    if want_fema and network and "fema" not in rec:
        try:
            store({"fema": fetch_fema(lat, lon)})
            did = True
        except HazardError:
            if raise_errors:
                raise
    return rec, did


def static_risk(lat: float, lon: float, cached_only: bool = False) -> dict:
    """Public hazard zoning for a point.

    {"fema": {"zone", "subtype", "high_risk", "floodway", "base_flood_elevation_ft",
              "moderate_risk"} or None when unknown / unmapped / not yet fetched,
     "fire_zone": "Very High" | "High" | "Moderate" | None,
     "km_to_past_fire": float | None}
    plus, for points in the Los Angeles box, "past_fire" {"name", "year", "acres"}
    (the nearest perimeter of any year), "km_to_fire_before_2025" and
    "fire_before_2025" (the same but ignoring the January 2025 fires, so the
    replay is not graded with hindsight).

    With cached_only=True nothing is fetched: values already cached for the
    point are returned and the rest are None. (Los Angeles fire fields are
    computed from the downloaded CAL FIRE files when those are on disk, which
    needs no network.) Otherwise missing parts are fetched, cached, and a source
    that fails leaves its field None without caching the failure.
    """
    rec, did = _resolve(lat, lon, want_fema=True, want_fire=True, network=not cached_only, raise_errors=False)
    if did and not cached_only:
        _save_points()
    with _lock:
        return _view(rec)


def warm_static(points: list[tuple[float, float]], log: Callable[[str], None] = print) -> int:
    """Fill the static_risk cache for many points, one at a time. Returns how many were looked up.

    Points already cached are skipped. FEMA is only queried outside the Los
    Angeles box and the fire zone only inside California, so Houston points cost
    one FEMA request each and Los Angeles points cost no request at all once the
    CAL FIRE files are downloaded. A failing request is retried with a growing
    pause; after 5 points in a row fail the run stops so the service is left alone.
    """
    todo: list[tuple[float, float, bool, bool]] = []
    seen: set[str] = set()
    with _lock:
        cache = _load_points()
        for lat, lon in points:
            key = point_key(lat, lon)
            if key in seen:
                continue
            seen.add(key)
            rec = cache.get(key, {})
            in_la = in_box(lat, lon, LA_BOX)
            want_fema = not in_la and "fema" not in rec
            want_fire = in_box(lat, lon, CALIFORNIA_BOX) and "fire_zone" not in rec
            if want_fema or want_fire:
                todo.append((float(lat), float(lon), want_fema, want_fire))
    log(f"warm_static: {len(todo)} of {len(seen)} points need a lookup")
    done = failures_in_a_row = 0
    started = time.monotonic()
    for n, (lat, lon, want_fema, want_fire) in enumerate(todo, 1):
        for attempt in range(3):
            try:
                _, did = _resolve(lat, lon, want_fema=want_fema, want_fire=want_fire, network=True, raise_errors=True)
            except HazardError as exc:
                pause = min(60.0, 5.0 * 2 ** attempt)
                log(f"warm_static: {point_key(lat, lon)} failed ({exc}); pausing {pause:.0f}s")
                time.sleep(pause)
                did = None
            else:
                break
        if did is None:
            failures_in_a_row += 1
            if failures_in_a_row >= 5:
                log("warm_static: 5 points in a row failed, stopping early")
                break
            continue
        failures_in_a_row = 0
        done += 1 if did else 0
        if n % 25 == 0:
            _save_points()
        if n % 100 == 0:
            rate = (time.monotonic() - started) / n
            log(f"warm_static: {n}/{len(todo)} done, about {rate * (len(todo) - n) / 60:.1f} min left")
    if _dirty:
        _save_points()
    log(f"warm_static: looked up {done} points")
    return done
