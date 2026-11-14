"""Spatial candidates are kept separate from verified household bindings."""
from __future__ import annotations

from math import cos, radians
from shapely.geometry import Point, Polygon


def location_ref(location_id: str, label: str, **values) -> dict:
    out = dict(location_id=location_id, label=label, structure_id=None, scan_id=None,
               sweep_id=None, room_id=None, unit_label=None, binding="unmapped",
               longitude=None, latitude=None, bearing_degrees=None)
    unknown = set(values) - set(out)
    if unknown:
        raise ValueError(f"Unknown location fields: {sorted(unknown)}")
    out.update(values)
    return out


def structure_candidate(longitude: float | None, latitude: float | None,
                        structures: list[dict], max_distance_m: float = 15) -> dict | None:
    if longitude is None or latitude is None:
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    kx = 111320 * cos(radians(latitude))
    candidates = []
    for structure in structures:
        try:
            polygon = Polygon(structure["polygon"])
            if polygon.is_empty or not polygon.is_valid:
                continue
            local_polygon = Polygon([((x - longitude) * kx, (y - latitude) * 111320)
                                     for x, y in polygon.exterior.coords])
            distance = local_polygon.distance(Point(0, 0))
            if distance <= max_distance_m:
                candidates.append((distance, str(structure["id"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not candidates:
        return None
    distance, sid = min(candidates)
    return {"structure_id": sid, "distance_m": round(distance, 2),
            "binding": "unverified", "basis": "GPS proximity candidate; requires reviewed alignment"}


def scan_locations(scan: dict, structures: list[dict]) -> list[dict]:
    origin = scan.get("origin") or [None, None]
    candidate = structure_candidate(origin[0], origin[1], structures)
    sid = candidate["structure_id"] if candidate else None
    common = dict(scan_id=scan["id"], structure_id=sid, binding="unverified")
    locations = [location_ref(f"scan:{scan['id']}", scan.get("name") or scan["id"],
                              longitude=origin[0], latitude=origin[1], **common)]
    rooms = {r["id"]: r for r in scan.get("rooms", [])}
    for sweep in scan.get("sweeps", []):
        room_id = sweep.get("room_id")
        room = rooms.get(room_id) or {}
        locations.append(location_ref(f"scan:{scan['id']}:sweep:{sweep['id']}",
                         f"{scan.get('name') or scan['id']} / {room.get('label') or room.get('type') or sweep['id']}",
                         sweep_id=sweep["id"], room_id=room_id,
                         longitude=sweep.get("lon"), latitude=sweep.get("lat"),
                         bearing_degrees=sweep.get("heading"), **common))
    return locations
