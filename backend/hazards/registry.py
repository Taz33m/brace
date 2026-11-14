"""The scenarios the app can show: two replays built from archived forecasts,
plus whatever NHC and NWS show right now for Houston and Los Angeles.

Replays are built once from the network (scripts/fetch_hazards.py, or lazily on
first use) and stored under data/hazards/scenarios/. After that everything here
is a read from memory. Live scenarios are refreshed at most every 10 minutes
and the last snapshot is kept on disk.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from . import alerts, fireweather, net, nhc, wind
from .errors import HazardError
from .util import (HOUSTON_CENTER, LA_BOX, hours_between, iso, now_utc, parse_iso, round_geometry, to_utc_iso,
                   trim)

logger = logging.getLogger(__name__)

BERYL = {
    "id": "beryl-2024",
    "storm": "al022024",
    # Advisories 6-12 hours apart: 72, 60, 48, 36, 24, 12 and 6 hours before the Texas landfall, then landfall.
    "advisories": [27, 29, 31, 33, 35, 37, 38, 39],
    "landfall_advisory": 39,
    "landfall_place": "near Matagorda, Texas",
    "name": "Hurricane Beryl",
    "city": "Houston",
    "summary": "Replay of the real National Hurricane Center forecasts for Hurricane Beryl, from 72 hours out "
               "to its Texas landfall near Matagorda early on 8 July 2024.",
}
LA_REPLAY = {
    "id": "la-red-flag-jan-2025",
    "wfo": "LOX", "year": 2025, "etn": 1,
    # Products issued up to the afternoon of 7 January (Pacific time), when the windstorm began.
    "last_product": "2025-01-08T08:00:00Z",
    "fires_from": "2025-01-07", "fires_before": "2025-01-12",
    "name": "Santa Ana windstorm and Red Flag Warning, 7-8 January 2025",
    "city": "Los Angeles",
    "summary": "Replay of the real National Weather Service Red Flag Warnings issued for the Los Angeles area "
               "ahead of the 7-8 January 2025 Santa Ana windstorm.",
}
LIVE_WILDFIRE_ID = "live-la-fire-weather"
IEM_EVENT_URL = "https://mesonet.agron.iastate.edu/json/vtec_event.py"
IEM_EVENT_GEO_URL = "https://mesonet.agron.iastate.edu/geojson/vtec_event.py"
CALFIRE_PERIMETERS_ALL = ("https://services1.arcgis.com/jUJYIo9tSA7EHvfZ/arcgis/rest/services/"
                          "California_Historic_Fire_Perimeters/FeatureServer/0/query")
HINDSIGHT_NOTE = ("Final perimeter of a fire that started after these warnings were issued. Shown for context "
                  "only; it was not known at the time and is not used to score exposure.")
LIVE_TTL_S = 600
LIVE_RETRY_S = 120
LIVE_STALE_S = 3 * 3600

_lock = threading.RLock()
_loaded: dict[str, dict] = {}
_contexts: dict[tuple, "_Context"] = {}
_live: dict | None = None
_live_checked = 0.0


def _reset_for_tests() -> None:
    global _live, _live_checked
    _loaded.clear()
    _contexts.clear()
    _live, _live_checked = None, 0.0


# ------------------------------------------------------------ replay builds

def build_beryl(log: Callable[[str], None] | None = None) -> dict:
    """Fetch (or read from cache) the Beryl advisories and cones and assemble the replay."""
    say = log or (lambda _m: None)
    cfg = BERYL
    steps = []
    for adv in cfg["advisories"]:
        say(f"NHC {cfg['storm']} advisory {adv}...")
        parsed = nhc.parse_forecast_advisory(nhc.fetch_archived_advisory(cfg["storm"], adv))
        cone = nhc.read_cone_zip(nhc.fetch_archived_cone(cfg["storm"], adv))
        steps.append({
            "id": f"adv{adv}", "issued": parsed["issued"], "advisory": parsed,
            "cone": cone["cone"], "coastal_warnings": cone["coastal_warnings"],
            "source": {
                "advisory": nhc.ARCHIVE_ADVISORY_URL.format(year=cfg["storm"][4:8], basin=cfg["storm"][:2],
                                                            num=int(cfg["storm"][2:4]), storm=cfg["storm"], adv=adv),
                "cone": nhc.ARCHIVE_CONE_URL.format(storm=cfg["storm"], adv=adv),
            },
        })
    at_coast = next(s["advisory"] for s in steps if s["id"] == f"adv{cfg['landfall_advisory']}")
    if "COAST" not in (at_coast.get("status") or ""):
        raise HazardError(f"advisory {cfg['landfall_advisory']} does not place the centre on the coast")
    landfall = {
        "time": at_coast["points"][0]["time"], "lat": at_coast["center"][0], "lon": at_coast["center"][1],
        "place": cfg["landfall_place"],
        "source": f"NHC advisory {cfg['landfall_advisory']}: centre on the coast at this time (observed, not forecast)",
    }
    for s in steps:
        lead = round(hours_between(s["issued"], landfall["time"]))
        s["label"] = f"{lead} hours before landfall" if lead > 0 else f"Landfall {cfg['landfall_place']}"
    return {"id": cfg["id"], "kind": "hurricane", "name": cfg["name"], "city": cfg["city"], "live": False,
            "summary": cfg["summary"], "landfall": landfall, "steps": steps, "built_at": iso(now_utc())}


def _iem(kind: str, significance: str) -> dict:
    cfg = LA_REPLAY
    ext = "geojson" if kind == "geo" else "json"
    path = net.cache_file("iem", f"{cfg['wfo'].lower()}_{cfg['year']}_fw_{significance.lower()}_{cfg['etn']}.{ext}")
    cached = net.read_json(path)
    if isinstance(cached, dict):
        return cached
    data = net.get_json(IEM_EVENT_GEO_URL if kind == "geo" else IEM_EVENT_URL, {
        "wfo": cfg["wfo"], "year": cfg["year"], "phenomena": "FW", "significance": significance, "etn": cfg["etn"],
    }, timeout=net.BULK_TIMEOUT)
    if not isinstance(data, dict):
        raise HazardError("Iowa Environmental Mesonet returned an unexpected response")
    net.write_json(path, data)
    return data


def _january_2025_fires() -> list[dict]:
    """Final perimeters of the fires that started in the Los Angeles box during the event."""
    cfg = LA_REPLAY
    path = net.cache_file("calfire", "january_2025_fires.json")
    data = net.read_json(path)
    if not isinstance(data, dict):
        data = net.get_json(CALFIRE_PERIMETERS_ALL, {
            "where": f"ALARM_DATE >= DATE '{cfg['fires_from']}' AND ALARM_DATE < DATE '{cfg['fires_before']}'",
            "geometry": f"{LA_BOX[2]},{LA_BOX[0]},{LA_BOX[3]},{LA_BOX[1]}", "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "outSR": "4326", "geometryPrecision": "5",
            "maxAllowableOffset": "0.0001", "outFields": "FIRE_NAME,ALARM_DATE,CONT_DATE,GIS_ACRES",
            "orderByFields": "GIS_ACRES DESC", "f": "geojson",
        }, timeout=net.BULK_TIMEOUT)
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise HazardError("CAL FIRE fire perimeter service returned an unexpected response")
        net.write_json(path, data)
    fires = []
    for f in data["features"]:
        p = f.get("properties") or {}
        if not f.get("geometry") or not p.get("FIRE_NAME"):
            continue
        alarm = p.get("ALARM_DATE")
        fires.append({
            "name": f"{p['FIRE_NAME'].strip().title()} Fire", "polygon": round_geometry(f["geometry"], 4),
            "alarm_date": time.strftime("%Y-%m-%d", time.gmtime(alarm / 1000)) if isinstance(alarm, (int, float)) else None,
            "acres": round(p["GIS_ACRES"]) if isinstance(p.get("GIS_ACRES"), (int, float)) else None,
            "hindsight": True, "note": HINDSIGHT_NOTE,
        })
    return fires


def build_la_replay(log: Callable[[str], None] | None = None) -> dict:
    """Rebuild the January 2025 Red Flag Warning step by step from the archived NWS products."""
    say = log or (lambda _m: None)
    cfg = LA_REPLAY
    say("Iowa Environmental Mesonet: NWS Los Angeles Red Flag Warning products, January 2025...")
    event = _iem("json", "W")
    if not event.get("event_exists") or not event.get("report"):
        raise HazardError("Iowa Environmental Mesonet has no record of the January 2025 Red Flag Warning")
    raw = [event["report"]] + list(event.get("svs") or [])
    products = [fireweather.parse_rfw_product(p["text"], to_utc_iso(p.get("valid"))) for p in raw]
    names = {u["ugc"]: u.get("name") for u in event.get("ugcs") or []}

    geoms: dict[str, dict] = {}
    for significance in ("A", "W"):  # warning geometry wins where both exist
        try:
            geo = _iem("geo", significance)
        except HazardError:
            if significance == "W":
                raise
            continue
        for feat in geo.get("features") or []:
            if feat.get("id") and feat.get("geometry"):
                geoms[feat["id"]] = round_geometry(feat["geometry"], 4)

    steps = []
    for snap in fireweather.replay(products):
        if snap["issued"] > cfg["last_product"]:
            continue
        zones = [dict(z, name=names.get(z["ugc"])) for z in snap["zones"] if z["ugc"] in geoms]
        steps.append({
            "id": parse_iso(snap["issued"]).strftime("%Y%m%dT%H%MZ"), "issued": snap["issued"],
            "label": fireweather.warning_label(snap["issued"], zones, snap["pds"]),
            "warning_text": trim(snap["headline"], 320), "pds": snap["pds"], "zones": zones,
            "wind": fireweather.step_wind(zones),
        })
    if not steps:
        raise HazardError("no Red Flag Warning products found before the cut-off time")
    used = {z["ugc"] for s in steps for z in s["zones"]}
    say("CAL FIRE: perimeters of the fires that followed...")
    try:
        fires = _january_2025_fires()
    except HazardError as exc:
        say(f"  fire perimeters unavailable ({exc}); continuing without them")
        fires = []
    return {"id": cfg["id"], "kind": "wildfire", "name": cfg["name"], "city": cfg["city"], "live": False,
            "summary": cfg["summary"], "steps": steps,
            "zones": {u: {"name": names.get(u), "geometry": geoms[u]} for u in sorted(used)},
            "fire_perimeters": fires, "built_at": iso(now_utc()),
            "source": {"warnings": "NWS Los Angeles/Oxnard RFW products via the Iowa Environmental Mesonet VTEC archive",
                       "fire_perimeters": "CAL FIRE FRAP California Historic Fire Perimeters"}}


_BUILDERS: dict[str, Callable[..., dict]] = {BERYL["id"]: build_beryl, LA_REPLAY["id"]: build_la_replay}


def _replay(scenario_id: str, *, rebuild: bool = False, log: Callable[[str], None] | None = None) -> dict:
    with _lock:
        if not rebuild and scenario_id in _loaded:
            return _loaded[scenario_id]
        path = net.cache_file("scenarios", f"{scenario_id}.json")
        data = None if rebuild else net.read_json(path)
        if not isinstance(data, dict) or not data.get("steps"):
            data = _BUILDERS[scenario_id](log)
            net.write_json(path, data)
        _loaded[scenario_id] = data
        for key in [k for k in _contexts if k[0] == scenario_id]:
            del _contexts[key]
        return data


# ----------------------------------------------------------------- live data

def _live_hurricanes() -> tuple[list[dict], dict]:
    storms = nhc.active_storms()
    atlantic = [s for s in storms if str(s.get("id", "")).lower().startswith("al")]
    found, skipped = [], 0
    for storm in atlantic:
        try:
            step = nhc.live_step(storm)
        except HazardError as exc:
            logger.warning("live storm %s skipped: %s", storm.get("id"), exc)
            skipped += 1
            continue
        if not step or not nhc.threatens(step, HOUSTON_CENTER):
            continue
        adv = step["advisory"]
        name = f"{adv['storm_type']} {adv['storm_name']}".strip()
        found.append({
            "id": f"live-{str(storm['id']).lower()}", "kind": "hurricane", "name": name, "city": "Houston",
            "live": True, "landfall": None, "steps": [step],
            "summary": f"Live National Hurricane Center forecast for {name}, advisory {adv['advisory']}.",
        })
    if found:
        text = f"{len(found)} active storm(s) forecast near Houston: " + ", ".join(s["name"] for s in found) + "."
    elif atlantic:
        text = f"NHC lists {len(atlantic)} active Atlantic storm(s); none is forecast near Houston."
    else:
        text = "NHC lists no active tropical cyclones in the Atlantic basin."
    if skipped:
        text += f" {skipped} storm(s) could not be read."
    return found, {"active": bool(found), "summary": text}


def _live_wildfire() -> tuple[list[dict], dict]:
    from shapely.geometry import box, shape

    metro = box(LA_BOX[2], LA_BOX[0], LA_BOX[3], LA_BOX[1])
    zones: dict[str, dict] = {}
    records: dict[tuple[str, str], dict] = {}
    sent_times, headlines, pds = [], [], False
    for feat in alerts.fire_weather_alerts("CA"):
        p = feat.get("properties") or {}
        sig = "W" if p.get("event") == "Red Flag Warning" else "A"
        desc = p.get("description") or ""
        gusts = fireweather.parse_wind(fireweather.wind_bullet(desc)) or {}
        is_pds = fireweather.PDS_PHRASE in f"{p.get('headline') or ''} {desc}".upper()
        sent = to_utc_iso(p.get("sent")) or iso(now_utc())
        hit = False
        for url in p.get("affectedZones") or []:
            ugc = url.rstrip("/").rsplit("/", 1)[-1]
            if ugc not in zones:
                try:
                    zone = alerts.zone_geometry(url)
                except HazardError:
                    zone = None
                if not zone or not shape(zone["geometry"]).intersects(metro):
                    continue
                zones[ugc] = {"name": zone.get("name"), "geometry": round_geometry(zone["geometry"], 4)}
            prev = records.get((ugc, sig))
            if prev and prev["_sent"] >= sent:
                continue
            hit = True
            records[(ugc, sig)] = {
                "ugc": ugc, "sig": sig, "name": zones[ugc]["name"],
                "start": to_utc_iso(p.get("onset") or p.get("effective")) or sent,
                "end": to_utc_iso(p.get("ends") or p.get("expires")),
                "gust_mph": gusts.get("gust_mph"), "peak_gust_mph": gusts.get("peak_gust_mph"),
                "direction": gusts.get("direction"), "wind_text": gusts.get("text"),
                "pds": is_pds and sig == "W", "headline": p.get("headline"), "_sent": sent,
            }
        if hit:
            sent_times.append(sent)
            pds = pds or (is_pds and sig == "W")
            if sig == "W" and p.get("headline"):
                headlines.append(p["headline"])
    zone_recs = sorted(({k: v for k, v in r.items() if k != "_sent"} for r in records.values()),
                       key=lambda z: (z["sig"] != "W", z["ugc"]))
    if not zone_recs:
        return [], {"active": False,
                    "summary": "NWS has no Red Flag Warning or Fire Weather Watch in effect for the Los Angeles area."}
    issued = max(sent_times)
    warned = [z for z in zone_recs if z["sig"] == "W"]
    kind = "Red Flag Warning" if warned else "Fire Weather Watch"
    step = {"id": "now", "issued": issued, "label": "Live now", "pds": pds, "zones": zone_recs,
            "warning_text": trim(headlines[0] if headlines else zone_recs[0].get("headline"), 320),
            "wind": fireweather.step_wind(zone_recs)}
    text = f"NWS {kind} in effect or scheduled for {len(warned or zone_recs)} fire weather zone(s) around Los Angeles."
    scenario = {"id": LIVE_WILDFIRE_ID, "kind": "wildfire", "name": f"{kind}, Los Angeles area", "city": "Los Angeles",
                "live": True, "summary": text, "steps": [step],
                "zones": {u: zones[u] for u in sorted({z["ugc"] for z in zone_recs})}, "fire_perimeters": [],
                "source": {"warnings": "NWS active alerts (api.weather.gov)"}}
    return [scenario], {"active": True, "summary": text}


def live_snapshot(refresh: bool = False) -> dict:
    """What NHC / NWS show now: {"fetched_at", "scenarios": [...], "status": {"houston", "los_angeles"}}.

    Never raises. Each status is {"active", "summary", "as_of"}; a source that
    cannot be reached keeps its last good answer (marked "stale": True) for up
    to 3 hours and after that reads {"active": False, "unavailable": True}.
    """
    global _live, _live_checked
    with _lock:
        path = net.cache_file("live", "snapshot.json")
        if _live is None:
            disk = net.read_json(path)
            if isinstance(disk, dict) and "scenarios" in disk:
                _live = disk
                age = net.file_age_s(path) or 0.0
                _live_checked = time.monotonic() - age
        ttl = LIVE_RETRY_S if _live and _live.get("errors") else LIVE_TTL_S
        if _live is not None and not refresh and time.monotonic() - _live_checked < ttl:
            return _live

        previous = _live or {}
        scenarios_out: list[dict] = []
        status: dict[str, dict] = {}
        errors: list[str] = []
        for place, kind, source, fetch in (
                ("houston", "hurricane", "the National Hurricane Center", _live_hurricanes),
                ("los_angeles", "wildfire", "the National Weather Service", _live_wildfire)):
            try:
                found, state = fetch()
                state["as_of"] = iso(now_utc())
            except HazardError as exc:
                errors.append(str(exc))
                old = (previous.get("status") or {}).get(place) or {}
                fresh_enough = bool(old.get("as_of")) and \
                    (now_utc() - parse_iso(old["as_of"])).total_seconds() < LIVE_STALE_S
                if fresh_enough:  # keep showing the last good answer, marked stale, for up to 3 hours
                    found = [s for s in previous.get("scenarios", []) if s["kind"] == kind]
                    state = dict(old, stale=True)
                else:
                    found, state = [], {"active": False, "unavailable": True, "error": str(exc),
                                        "summary": f"Live check unavailable: could not reach {source}."}
            except Exception as exc:  # never let a surprise in a live feed take the app down
                logger.exception("live %s check failed", kind)
                errors.append(f"{type(exc).__name__}: {exc}")
                found, state = [], {"active": False, "unavailable": True, "error": f"{type(exc).__name__}: {exc}",
                                    "summary": "Live check failed unexpectedly."}
            scenarios_out += found
            status[place] = state
        _live = {"fetched_at": iso(now_utc()), "scenarios": scenarios_out, "status": status, "errors": errors}
        _live_checked = time.monotonic()
        for key in [k for k in _contexts if k[0].startswith("live-")]:
            del _contexts[key]
        try:
            net.write_json(path, _live)
        except OSError:
            pass
        return _live


def live_status() -> dict:
    """Plain summary of the live check for each metro (see live_snapshot)."""
    snap = live_snapshot()
    return {"checked_at": snap["fetched_at"], **snap["status"]}


# ------------------------------------------------------------ step contexts

class _Context:
    def exposure(self, lat: float, lon: float) -> dict:
        raise NotImplementedError

    def view(self) -> dict:
        raise NotImplementedError


class _HurricaneContext(_Context):
    def __init__(self, scen: dict, step: dict):
        import shapely
        from shapely.geometry import shape

        self.scen, self.step = scen, step
        self.samples = wind.build_samples(step["advisory"]["points"])
        self.cone = None
        if step.get("cone"):
            try:
                self.cone = shape(step["cone"])
                shapely.prepare(self.cone)
            except Exception:
                self.cone = None
        self._contains = shapely.contains_xy
        self._view: dict | None = None

    def exposure(self, lat: float, lon: float) -> dict:
        e = wind.point_exposure(self.samples, lat, lon)
        return {
            "kind": "hurricane", "peak_wind_kt": e["peak_wind_kt"], "peak_wind_mph": e["peak_wind_mph"],
            "wind_band": e["wind_band"], "hours_until_tropical_storm_wind": e["hours_until_tropical_storm_wind"],
            "closest_approach_km": e["closest_approach_km"], "track_side": e["track_side"],
            "in_cone": bool(self.cone is not None and self._contains(self.cone, lon, lat)),
            "hours_until_peak_wind": e["hours_until_peak_wind"],
            "hours_until_closest_approach": e["hours_until_closest_approach"], "wind_basis": e["wind_basis"],
        }

    def view(self) -> dict:
        if self._view is None:
            adv = self.step["advisory"]
            swaths = wind.swath_polygons(self.samples)
            self._view = {
                "id": self.scen["id"], "step_id": self.step["id"], "kind": "hurricane", "name": self.scen["name"],
                "city": self.scen["city"], "live": self.scen["live"], "issued": self.step["issued"],
                "label": self.step.get("label"), "advisory": adv["advisory"], "status": adv["storm_type"],
                "center": list(adv["center"]), "max_wind_kt": adv["max_wind_kt"], "gust_kt": adv.get("gust_kt"),
                "track": [{"time": p["time"], "lat": p["lat"], "lon": p["lon"], "wind_kt": p["wind_kt"],
                           "hours_from_issue": p["hours_from_issue"], "gust_kt": p.get("gust_kt"),
                           "status": p.get("status"), "radii_nm": p.get("radii") or {}} for p in adv["points"]],
                "cone": self.step.get("cone"),
                "wind_fields": [{"kt": kt, "polygon": swaths[kt]} for kt in wind.THRESHOLDS if swaths.get(kt)],
                "landfall": self.scen.get("landfall"),
                "coastal_warnings": self.step.get("coastal_warnings") or [],
                "source": self.step.get("source"),
            }
        return self._view


class _WildfireContext(_Context):
    def __init__(self, scen: dict, step: dict):
        from shapely import STRtree
        from shapely.geometry import shape

        self.scen, self.step = scen, step
        self.by_ugc: dict[str, list[dict]] = {}
        for z in step["zones"]:
            self.by_ugc.setdefault(z["ugc"], []).append(z)
        self.ugcs = [u for u in self.by_ugc if u in scen["zones"]]
        geoms = []
        for u in self.ugcs:
            g = shape(scen["zones"][u]["geometry"])
            geoms.append(g if g.is_valid else g.buffer(0))
        self.tree = STRtree(geoms)
        self._view: dict | None = None

    def exposure(self, lat: float, lon: float) -> dict:
        from shapely.geometry import Point

        here: list[dict] = []
        for i in self.tree.query(Point(lon, lat), predicate="intersects"):
            here += self.by_ugc[self.ugcs[int(i)]]
        return fireweather.zone_exposure(self.step["issued"], here)

    def view(self) -> dict:
        if self._view is None:
            def pick(sig: str) -> tuple[list[dict], list[dict]]:
                zones = [z for z in self.step["zones"] if z["sig"] == sig and z["ugc"] in self.scen["zones"]]
                keys = ("ugc", "name", "start", "end", "gust_mph", "peak_gust_mph", "direction", "pds")
                return ([self.scen["zones"][z["ugc"]]["geometry"] for z in zones],
                        [{k: z.get(k) for k in keys} for z in zones])

            warn_geoms, warn_zones = pick("W")
            watch_geoms, watch_zones = pick("A")
            self._view = {
                "id": self.scen["id"], "step_id": self.step["id"], "kind": "wildfire", "name": self.scen["name"],
                "city": self.scen["city"], "live": self.scen["live"], "issued": self.step["issued"],
                "label": self.step.get("label"),
                "warning_polygons": warn_geoms, "warning_zones": warn_zones,
                "warning_text": self.step.get("warning_text") or "", "pds": bool(self.step.get("pds")),
                "wind": self.step.get("wind"),
                "watch_polygons": watch_geoms, "watch_zones": watch_zones,
                "fire_perimeters": self.scen.get("fire_perimeters") or [],
                "source": self.scen.get("source"),
            }
        return self._view


def _scenario_data(scenario_id: str) -> dict:
    if scenario_id in _BUILDERS:
        return _replay(scenario_id)
    if scenario_id.startswith("live-"):
        for scen in live_snapshot()["scenarios"]:
            if scen["id"] == scenario_id:
                return scen
        raise HazardError(f"live scenario {scenario_id!r} is no longer active")
    raise HazardError(f"unknown scenario {scenario_id!r}")


def _context(scenario_id: str, step_id: str | None) -> _Context:
    key = (scenario_id, step_id)
    if scenario_id.startswith("live-"):
        live_snapshot()  # cheap inside its refresh window; drops stale contexts when it does refresh
    ctx = _contexts.get(key)
    if ctx is not None:
        return ctx
    with _lock:
        scen = _scenario_data(scenario_id)
        ctx = _contexts.get(key)  # a live refresh inside _scenario_data may have cleared the table
        if ctx is not None:
            return ctx
        if step_id is None:
            step = scen["steps"][-1]
        else:
            step = next((s for s in scen["steps"] if s["id"] == step_id), None)
            if step is None:
                raise HazardError(f"scenario {scenario_id!r} has no step {step_id!r}")
        ctx = _contexts.get((scenario_id, step["id"]))
        if ctx is None:
            ctx = (_HurricaneContext if scen["kind"] == "hurricane" else _WildfireContext)(scen, step)
            _contexts[(scenario_id, step["id"])] = ctx
        _contexts[key] = ctx
        return ctx


# ---------------------------------------------------------------- public API

def scenarios(include_live: bool = True) -> list[dict]:
    """Every scenario the app can show (replays first, then anything live).

    Each entry: {"id", "kind", "name", "city", "live", "summary", "steps":
    [{"id", "issued", "label"}]}. A replay that has never been downloaded and
    cannot be fetched now is left out (and logged) rather than raising.
    """
    out = []
    sources: list[dict] = []
    for scenario_id in _BUILDERS:
        try:
            sources.append(_replay(scenario_id))
        except HazardError as exc:
            logger.warning("scenario %s unavailable: %s", scenario_id, exc)
    if include_live:
        sources += live_snapshot()["scenarios"]
    for scen in sources:
        out.append({
            "id": scen["id"], "kind": scen["kind"], "name": scen["name"], "city": scen["city"],
            "live": bool(scen["live"]), "summary": scen["summary"],
            "steps": [{"id": s["id"], "issued": s["issued"], "label": s.get("label") or ""} for s in scen["steps"]],
        })
    return out


def scenario(scenario_id: str, step_id: str | None = None) -> dict:
    """Everything the map needs for one scenario step (default: the last step).

    Geometry is GeoJSON, so polygon coordinates are [lon, lat]; "center" and
    the track points use lat / lon as named. Raises HazardError for an unknown
    scenario or step.
    """
    return _context(scenario_id, step_id).view()


def exposure(scenario_id: str, lat: float, lon: float, step_id: str | None = None) -> dict:
    """How one forecast step affects one point. No network once the scenario is loaded.

    Hurricane: see backend.hazards.wind for the method and its limits.
    Wildfire: whether the point's fire weather zone is under a Red Flag Warning
    as of that step, how long until it starts and how long it runs.
    """
    return _context(scenario_id, step_id).exposure(float(lat), float(lon))


def refresh(log: Callable[[str], None] = print, rebuild: bool = False) -> dict:
    """Download everything the package caches (replays, CAL FIRE files, live snapshot).

    Safe to re-run: downloads already on disk are reused. rebuild=True
    re-derives the replay files from those downloads. Returns a short report {"scenarios": [...ids], "problems": [...]}.
    """
    from . import static

    problems: list[str] = []
    built: list[str] = []
    for scenario_id in _BUILDERS:
        try:
            _replay(scenario_id, rebuild=rebuild, log=log)
            built.append(scenario_id)
        except HazardError as exc:
            problems.append(f"{scenario_id}: {exc}")
            log(f"FAILED {scenario_id}: {exc}")
    try:
        static.download_la_fire_data(log=log)
    except HazardError as exc:
        problems.append(f"CAL FIRE Los Angeles data: {exc}")
        log(f"FAILED CAL FIRE Los Angeles data: {exc}")
    snap = live_snapshot(refresh=True)
    problems += snap.get("errors") or []
    for place, state in snap["status"].items():
        log(f"live {place}: {state['summary']}")
    return {"scenarios": built + [s["id"] for s in snap["scenarios"]], "problems": problems}
