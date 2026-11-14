"""Active National Weather Service alerts (api.weather.gov)."""
from __future__ import annotations

from . import net
from .errors import HazardError
from .util import iso, now_utc, parse_iso, to_utc_iso, trim

ALERTS_URL = "https://api.weather.gov/alerts/active"
ALERT_TTL_S = 300
DESCRIPTION_LIMIT = 600
FIRE_EVENTS = ("Red Flag Warning", "Fire Weather Watch")
_HEADERS = {"Accept": "application/geo+json"}


def map_alert(feature: dict) -> dict:
    """One NWS alert feature in the Brace shape. All times are UTC ISO strings.

    "expires" is when this alert message expires; "ends" is when the hazard
    itself is forecast to end (often later, sometimes absent).
    """
    p = feature.get("properties") or {}
    return {
        "event": p.get("event"), "severity": p.get("severity"), "headline": p.get("headline"),
        "onset": to_utc_iso(p.get("onset") or p.get("effective")), "expires": to_utc_iso(p.get("expires")),
        "description": trim(p.get("description"), DESCRIPTION_LIMIT),
        "ends": to_utc_iso(p.get("ends")), "sender": p.get("senderName"), "id": p.get("id"),
    }


def _still_active(alert: dict) -> bool:
    end = alert.get("ends") or alert.get("expires")
    try:
        return not end or parse_iso(end) > now_utc()
    except ValueError:
        return True


def live_alerts(lat: float, lon: float) -> list[dict]:
    """Active NWS alerts at a point right now, most severe sources first as NWS returns them.

    Cached for 5 minutes per point (4 decimals). If NWS cannot be reached, the
    last cached answer is returned with alerts that have since ended removed;
    with no cache at all a HazardError is raised.
    """
    lat4, lon4 = round(float(lat), 4), round(float(lon), 4)
    path = net.cache_file("nws", "alerts", f"{lat4:.4f}_{lon4:.4f}.json")
    cached = net.read_json(path)
    age = net.file_age_s(path)
    if isinstance(cached, dict) and age is not None and age < ALERT_TTL_S:
        return [a for a in cached["alerts"] if _still_active(a)]
    try:
        data = net.get_json(ALERTS_URL, {"point": f"{lat4},{lon4}"}, timeout=net.QUICK_TIMEOUT, retries=1,
                            headers=_HEADERS)
        if not isinstance(data, dict) or not isinstance(data.get("features"), list):
            raise HazardError("NWS alerts service returned an unexpected response")
    except HazardError:
        if isinstance(cached, dict):
            return [a for a in cached["alerts"] if _still_active(a)]
        raise
    alerts = [map_alert(f) for f in data["features"]]
    net.write_json(path, {"fetched_at": iso(now_utc()), "alerts": alerts})
    return alerts


def fire_weather_alerts(state: str = "CA") -> list[dict]:
    """Raw active Red Flag Warning / Fire Weather Watch alert features for a state."""
    data = net.get_json(ALERTS_URL, {"area": state, "event": ",".join(FIRE_EVENTS)}, timeout=net.QUICK_TIMEOUT,
                        retries=0, headers=_HEADERS)
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise HazardError("NWS alerts service returned an unexpected response")
    return [f for f in data["features"] if (f.get("properties") or {}).get("event") in FIRE_EVENTS]


def zone_geometry(zone_url: str) -> dict | None:
    """Geometry and name of an NWS zone (cached on disk): {"name", "geometry"} or None."""
    zone_id = zone_url.rstrip("/").rsplit("/", 1)[-1]
    kind = zone_url.rstrip("/").rsplit("/", 2)[-2]
    path = net.cache_file("nws", "zones", f"{kind}_{zone_id}.json")
    cached = net.read_json(path)
    if isinstance(cached, dict) and cached.get("geometry"):
        return cached
    data = net.get_json(zone_url, timeout=net.QUICK_TIMEOUT, retries=1, headers=_HEADERS)
    geom = data.get("geometry") if isinstance(data, dict) else None
    if not geom:
        return None
    out = {"name": (data.get("properties") or {}).get("name"), "geometry": geom}
    net.write_json(path, out)
    return out
