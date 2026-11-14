"""Small shared helpers: UTC time strings, distances, GeoJSON rounding."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

NM_TO_KM = 1.852
KT_TO_MPH = 1.15078

# Rough metro boxes (lat_min, lat_max, lon_min, lon_max).
HOUSTON_BOX = (28.8, 30.6, -96.3, -94.5)
LA_BOX = (33.5, 34.9, -119.1, -117.4)
CALIFORNIA_BOX = (32.4, 42.1, -124.6, -114.0)
HOUSTON_CENTER = (29.7604, -95.3698)
LA_CENTER = (34.0522, -118.2437)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """ISO 8601 in UTC with a trailing Z, to the second."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> datetime:
    """Parse any ISO 8601 string (Z or numeric offset) into an aware UTC datetime."""
    dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_utc_iso(text: str | None) -> str | None:
    """Normalise an ISO string with any offset to UTC; None stays None."""
    if not text:
        return None
    try:
        return iso(parse_iso(text))
    except ValueError:
        return None


def hours_between(start_iso: str, end_iso: str) -> float:
    return (parse_iso(end_iso) - parse_iso(start_iso)).total_seconds() / 3600.0


def in_box(lat: float, lon: float, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def round_coords(obj: Any, ndigits: int = 4) -> Any:
    """Round every number inside a GeoJSON coordinates structure."""
    if isinstance(obj, (list, tuple)):
        return [round_coords(v, ndigits) for v in obj]
    if isinstance(obj, float):
        return round(obj, ndigits)
    return obj


def round_geometry(geom: dict | None, ndigits: int = 4) -> dict | None:
    """Copy of a GeoJSON geometry with rounded coordinates (lon, lat order kept)."""
    if not geom:
        return None
    return {"type": geom["type"], "coordinates": round_coords(geom["coordinates"], ndigits)}


def trim(text: str | None, limit: int) -> str:
    """Collapse whitespace and cut at a word boundary."""
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:") + "..."
