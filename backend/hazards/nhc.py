"""National Hurricane Center data: forecast advisory text, forecast cone, active storms."""
from __future__ import annotations

import html
import io
import re
import zipfile
from datetime import datetime, timedelta, timezone

from . import net
from .errors import HazardError
from .util import HOUSTON_CENTER, haversine_km, iso, round_geometry

ARCHIVE_ADVISORY_URL = "https://www.nhc.noaa.gov/archive/{year}/{basin}{num:02d}/{storm}.fstadv.{adv:03d}.shtml"
ARCHIVE_CONE_URL = "https://www.nhc.noaa.gov/gis/forecast/archive/{storm}_5day_{adv:03d}.zip"
CURRENT_STORMS_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

_MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
_STORM_TYPES = (
    "POTENTIAL TROPICAL CYCLONE", "POST-TROPICAL CYCLONE", "SUBTROPICAL DEPRESSION", "SUBTROPICAL STORM",
    "TROPICAL DEPRESSION", "TROPICAL STORM", "HURRICANE", "REMNANTS OF",
)
_POS = r"(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])"
_RADII_RE = re.compile(r"^(64|50|34) KT\.{3,}\s*(\d+)NE\s+(\d+)SE\s+(\d+)SW\s+(\d+)NW", re.M)
_VALID_RE = re.compile(r"^(FORECAST|OUTLOOK) VALID (\d{2})/(\d{2})(\d{2})Z(.*)$", re.M)
_WARNING_NAMES = {
    "HWR": "Hurricane Warning", "HWA": "Hurricane Watch",
    "TWR": "Tropical Storm Warning", "TWA": "Tropical Storm Watch",
}


def extract_pre(page: str) -> str:
    """The advisory text out of an NHC web page (it sits in a <pre> block)."""
    m = re.search(r"<pre[^>]*>(.*?)</pre>", page, re.S | re.I)
    return html.unescape(m.group(1) if m else page)


def _latlon(m: re.Match, offset: int = 0) -> tuple[float, float]:
    lat = float(m.group(offset + 1)) * (1 if m.group(offset + 2) == "N" else -1)
    lon = float(m.group(offset + 3)) * (1 if m.group(offset + 4) == "E" else -1)
    return lat, lon


def _resolve_day(issued: datetime, day: int, hour: int, minute: int) -> datetime:
    """A 'DD/HHMMZ' stamp from an advisory, placed in the right month."""
    year, month = issued.year, issued.month
    for _ in range(3):
        try:
            cand = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        except ValueError:
            cand = None
        if cand is not None and cand >= issued - timedelta(days=3):
            return cand
        month += 1
        if month > 12:
            year, month = year + 1, 1
    raise HazardError(f"cannot place day {day:02d} relative to advisory issued {iso(issued)}")


def _radii(block: str) -> dict[str, list[int]]:
    return {m.group(1): [int(m.group(i)) for i in range(2, 6)] for m in _RADII_RE.finditer(block)}


def parse_forecast_advisory(text: str) -> dict:
    """Parse an NHC Forecast/Advisory (TCM) text product.

    Returns {"storm_id", "storm_type", "storm_name", "advisory", "issued",
    "center": [lat, lon], "status", "max_wind_kt", "gust_kt", "pressure_mb",
    "points": [...], "dissipated": ISO | None}. `points` starts with the current
    position and continues with every forecast and outlook position; each is
    {"time", "hours_from_issue", "lat", "lon", "wind_kt", "gust_kt", "status",
    "radii": {"34": [NE, SE, SW, NW], "50": [...], "64": [...]}} with radii in
    nautical miles and only the thresholds the advisory lists.
    """
    text = text.replace("\r", "")
    head = re.search(r"^(?P<title>[A-Z][A-Z \-]+?) (?:SPECIAL )?FORECAST/ADVISORY NUMBER\s+(?P<num>\d+[A-Z]?)", text, re.M)
    stamp = re.search(r"^(\d{2})(\d{2}) UTC \w{3} (\w{3}) (\d{2}) (\d{4})", text, re.M)
    centre = re.search(r"CENTER LOCATED NEAR\s+" + _POS + r"\s+AT\s+(\d{2})/(\d{2})(\d{2})Z", text)
    if not (head and stamp and centre):
        raise HazardError("text is not an NHC forecast advisory (header, issue time or centre missing)")
    title = head.group("title").strip()
    storm_type, storm_name = "", title
    for kind in _STORM_TYPES:
        if title.startswith(kind + " "):
            storm_type, storm_name = kind.title(), title[len(kind):].strip().title()
            break
    if stamp.group(3) not in _MONTHS:
        raise HazardError(f"unknown month in advisory header: {stamp.group(3)}")
    issued = datetime(int(stamp.group(5)), _MONTHS[stamp.group(3)], int(stamp.group(4)),
                      int(stamp.group(1)), int(stamp.group(2)), tzinfo=timezone.utc)
    storm_id = re.search(r"\b([A-Z]{2}\d{6})\b", text)

    first_fc = _VALID_RE.search(text)
    now_block = text[: first_fc.start()] if first_fc else text
    wind = re.search(r"MAX SUSTAINED WINDS\s+(\d+) KT(?: WITH GUSTS TO\s+(\d+) KT)?", now_block)
    if not wind:
        raise HazardError("advisory has no MAX SUSTAINED WINDS line")
    pressure = re.search(r"MINIMUM CENTRAL PRESSURE\s+(\d+) MB", now_block)
    repeat = re.search(r"REPEAT\.\.\.CENTER LOCATED NEAR\s+" + _POS + r"\s+AT\s+\d{2}/\d{4}Z(?:\.\.\.([A-Z /\-]+))?", now_block)
    lat, lon = _latlon(centre)
    centre_time = _resolve_day(issued, int(centre.group(5)), int(centre.group(6)), int(centre.group(7)))
    status = (repeat.group(5) or "").strip() if repeat else ""

    def point(when: datetime, plat: float, plon: float, kt: int, gust: int | None, state: str, block: str) -> dict:
        return {
            "time": iso(when), "hours_from_issue": round((when - issued).total_seconds() / 3600.0, 2),
            "lat": plat, "lon": plon, "wind_kt": kt, "gust_kt": gust, "status": state or None,
            "radii": _radii(block),
        }

    points = [point(centre_time, lat, lon, int(wind.group(1)), int(wind.group(2)) if wind.group(2) else None,
                    status, now_block)]
    dissipated = None
    matches = list(_VALID_RE.finditer(text))
    for i, m in enumerate(matches):
        when = _resolve_day(issued, int(m.group(2)), int(m.group(3)), int(m.group(4)))
        rest = m.group(5)
        pos = re.search(_POS, rest)
        if not pos:
            if "DISSIPATED" in rest:
                dissipated = iso(when)
            continue
        block = text[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(text)]
        mw = re.search(r"MAX WIND\s+(\d+) KT(?:\.\.\.GUSTS\s+(\d+) KT)?", block)
        if not mw:
            continue
        state = rest[pos.end():].strip(". ").strip()
        plat, plon = _latlon(pos)
        points.append(point(when, plat, plon, int(mw.group(1)), int(mw.group(2)) if mw.group(2) else None, state, block))

    return {
        "storm_id": storm_id.group(1) if storm_id else None,
        "storm_type": storm_type, "storm_name": storm_name, "advisory": head.group("num").lstrip("0") or "0",
        "issued": iso(issued), "center": [lat, lon], "status": status or None,
        "max_wind_kt": int(wind.group(1)), "gust_kt": int(wind.group(2)) if wind.group(2) else None,
        "pressure_mb": int(pressure.group(1)) if pressure else None,
        "points": points, "dissipated": dissipated,
    }


def read_cone_zip(data: bytes) -> dict:
    """Forecast cone polygon and coastal watch/warning lines from an NHC 5-day GIS zip.

    Returns {"cone": GeoJSON Polygon | None, "coastal_warnings": [{"type", "line": GeoJSON}]}.
    """
    import shapefile  # pyshp

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HazardError("NHC forecast cone download is not a zip file") from exc
    names = archive.namelist()

    def reader(stem: str):
        return shapefile.Reader(shp=io.BytesIO(archive.read(stem + ".shp")),
                                dbf=io.BytesIO(archive.read(stem + ".dbf")),
                                shx=io.BytesIO(archive.read(stem + ".shx")))

    out: dict = {"cone": None, "coastal_warnings": []}
    try:
        for name in names:
            if name.endswith("_5day_pgn.shp"):
                shapes = reader(name[:-4]).shapes()
                if shapes:
                    out["cone"] = round_geometry(shapes[0].__geo_interface__, 3)
            elif name.endswith("_wwlin.shp"):
                rd = reader(name[:-4])
                fields = [f[0] for f in rd.fields[1:]]
                for sr in rd.shapeRecords():
                    code = str(dict(zip(fields, sr.record)).get("TCWW", "")).strip()
                    out["coastal_warnings"].append({
                        "type": _WARNING_NAMES.get(code, code),
                        "line": round_geometry(sr.shape.__geo_interface__, 3),
                    })
    except Exception as exc:  # pyshp raises several unrelated types on bad input
        raise HazardError(f"could not read NHC forecast cone shapefile: {exc}") from exc
    return out


# ------------------------------------------------------------------ fetching

def fetch_archived_advisory(storm: str, adv: int) -> str:
    """Advisory text for e.g. ("al022024", 27), from the disk cache or the NHC archive."""
    path = net.cache_file("nhc", storm, f"fstadv_{adv:03d}.txt")
    if path.exists():
        return path.read_text(encoding="utf-8")
    url = ARCHIVE_ADVISORY_URL.format(year=storm[4:8], basin=storm[:2], num=int(storm[2:4]), storm=storm, adv=adv)
    text = extract_pre(net.get_text(url))
    if "FORECAST/ADVISORY" not in text:
        raise HazardError(f"NHC archive page is not a forecast advisory: {url}")
    net.write_text(path, text)
    return text


def fetch_archived_cone(storm: str, adv: int) -> bytes:
    path = net.cache_file("nhc", storm, f"5day_{adv:03d}.zip")
    if path.exists():
        return path.read_bytes()
    data = net.get_bytes(ARCHIVE_CONE_URL.format(storm=storm, adv=adv))
    net.write_bytes(path, data)
    return data


def active_storms(*, quick: bool = True) -> list[dict]:
    """Storms NHC lists as active right now (raw entries from CurrentStorms.json)."""
    data = net.get_json(CURRENT_STORMS_URL, timeout=net.QUICK_TIMEOUT if quick else None, retries=0 if quick else 2)
    storms = data.get("activeStorms") if isinstance(data, dict) else None
    if not isinstance(storms, list):
        raise HazardError("NHC CurrentStorms.json has an unexpected shape")
    return storms


def live_step(storm: dict) -> dict | None:
    """One scenario step for an active storm, or None if it has no forecast advisory yet."""
    adv_info = storm.get("forecastAdvisory") or {}
    url = adv_info.get("url")
    if not url:
        return None
    advisory = parse_forecast_advisory(extract_pre(net.get_text(url, timeout=net.QUICK_TIMEOUT, retries=1)))
    cone = {"cone": None, "coastal_warnings": []}
    zip_url = (storm.get("trackCone") or {}).get("zipFile")
    if zip_url:
        try:
            cone = read_cone_zip(net.get_bytes(zip_url, timeout=net.QUICK_TIMEOUT, retries=1))
        except HazardError:
            pass  # a storm without a cone is still worth showing
    return {
        "id": f"adv{advisory['advisory']}", "issued": advisory["issued"], "label": "Latest forecast",
        "advisory": advisory, "cone": cone["cone"], "coastal_warnings": cone["coastal_warnings"],
        "source": {"advisory": url, "cone": zip_url},
    }


def threatens(step: dict, center: tuple[float, float] = HOUSTON_CENTER, within_km: float = 800.0) -> bool:
    """True if the forecast cone covers the city or any forecast position comes within `within_km`."""
    lat, lon = center
    if step.get("cone"):
        from shapely.geometry import Point, shape
        try:
            if shape(step["cone"]).contains(Point(lon, lat)):
                return True
        except Exception:
            pass
    return any(haversine_km(lat, lon, p["lat"], p["lon"]) <= within_km for p in step["advisory"]["points"])
