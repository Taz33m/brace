"""Which windows and outside doors of a scanned space face something on the site.

The scan's wall graph lists every opening with its measured width and height. The scan's viewpoints are
already placed on the site, so the same placement turns each opening into a point on the aerial and a
compass direction it faces. Put next to an outside action from the plan (a tree, a row of roof units),
that gives a measured fact from the inside and the outside together: "the bedroom window, 1.3 m wide,
faces it from about 28 m".

Everything here is measured or derived from measurements. Nothing is estimated from a picture.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from .matterport import MP_CACHE, gql

M_PER_DEG = 111_320.0
# An opening "faces" a point when the point lies within this many degrees of straight out from it.
FACING_WITHIN_DEG = 60.0
# Rooms the scan labels this way are outdoors, so a door onto one is an outside door.
OUTDOOR_ROOMS = {"patio", "balcony", "deck", "porch", "terrace"}

_QUERY = """{ model(id:"%s"){ rooms{ id label classifications{label}
  boundary{ edges{ id type vertices{ position{x y} }
    openings{ id type width height lowerElevation relativeCenter label } } } } } }"""


def fetch(model_id: str, refresh: bool = False) -> list[dict]:
    """The scan's rooms with their walls and the openings in each wall, as Matterport measured them."""
    path = MP_CACHE / "openings" / f"{model_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    rooms = gql(_QUERY % model_id)["model"]["rooms"] or []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rooms))
    return rooms


def _fit(sweeps: list[dict]) -> tuple[np.ndarray, float, float, float] | None:
    """How to turn the scan's own coordinates into metres east and north of its first placed viewpoint.

    Fitted from the viewpoints, which carry both. Returns the fit, its worst error in metres, and the
    reference longitude and latitude; or None when there are too few viewpoints or the fit is not a
    plain turn-and-shift (which would mean the two sets of coordinates do not belong together).
    """
    placed = [w for w in sweeps if w.get("lon") is not None and w.get("lat") is not None
              and (w.get("model_position") or {}).get("x") is not None and (w.get("model_position") or {}).get("y") is not None]
    if len(placed) < 3:
        return None
    lon0, lat0 = placed[0]["lon"], placed[0]["lat"]
    kx = M_PER_DEG * math.cos(math.radians(lat0))
    here = np.array([[w["model_position"]["x"], w["model_position"]["y"], 1.0] for w in placed])
    there = np.array([[(w["lon"] - lon0) * kx, (w["lat"] - lat0) * M_PER_DEG] for w in placed])
    fit, _, rank, _ = np.linalg.lstsq(here, there, rcond=None)
    if rank < 3:
        return None  # the viewpoints sit on one line, which fixes no direction
    stretch = np.linalg.svd(fit[:2].T, compute_uv=False)
    worst = float(np.sqrt(((here @ fit - there) ** 2).sum(axis=1)).max())
    if abs(stretch[0] - 1) > 0.05 or abs(stretch[1] - 1) > 0.05 or worst > 0.5:
        return None
    return fit, worst, lon0, lat0


def _name(room: dict) -> str:
    labels = [c.get("label") for c in room.get("classifications") or [] if c.get("label")]
    return (room.get("label") or (labels[0] if labels else "") or "").strip()


def layout(scan: dict, rooms: list[dict]) -> dict | None:
    """The scanned space as a plan in metres (east, north), with every opening placed, sized and given a facing.

    An opening that appears in only one room's walls is on the outside of the scanned space; one shared by
    two rooms is between them. A door onto a patio or balcony counts as outside.
    """
    fitted = _fit(scan.get("sweeps") or [])
    if fitted is None:
        return None
    fit, worst, lon0, lat0 = fitted
    kx = M_PER_DEG * math.cos(math.radians(lat0))

    def place(x: float, y: float) -> tuple[float, float]:
        e, n = np.array([x, y, 1.0]) @ fit
        return float(e), float(n)

    outdoor = {r["id"] for r in rooms if _name(r).lower() in OUTDOOR_ROOMS}
    seen: dict[str, list[dict]] = {}
    plan_rooms = []
    for room in rooms:
        edges = ((room.get("boundary") or {}).get("edges")) or []
        corners = [place(v["position"]["x"], v["position"]["y"]) for e in edges for v in e.get("vertices") or []]
        if len(corners) < 3:
            continue
        middle = (sum(c[0] for c in corners) / len(corners), sum(c[1] for c in corners) / len(corners))
        walls = []
        for e in edges:
            v = e.get("vertices") or []
            if len(v) != 2:
                continue
            a, b = place(v[0]["position"]["x"], v[0]["position"]["y"]), place(v[1]["position"]["x"], v[1]["position"]["y"])
            walls.append([[round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]])
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length < 1e-6:
                continue
            along = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            for o in e.get("openings") or []:
                if o.get("width") is None or o.get("relativeCenter") is None:
                    continue
                t = float(o["relativeCenter"])
                at = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                # Straight out of this room through the wall: the side of the wall away from the room's middle.
                out = (-along[1], along[0])
                if out[0] * (at[0] - middle[0]) + out[1] * (at[1] - middle[1]) < 0:
                    out = (along[1], -along[0])
                half = float(o["width"]) / 2
                seen.setdefault(o["id"], []).append({
                    "id": o["id"], "kind": "window" if o.get("type") == "window" else "door",
                    "room": _name(room) or None, "room_id": room["id"],
                    "width_m": round(float(o["width"]), 2), "height_m": None if o.get("height") is None else round(float(o["height"]), 2),
                    "sill_m": None if o.get("lowerElevation") is None else round(float(o["lowerElevation"]), 2),
                    "at": [round(at[0], 3), round(at[1], 3)],
                    "ends": [[round(at[0] - along[0] * half, 3), round(at[1] - along[1] * half, 3)],
                             [round(at[0] + along[0] * half, 3), round(at[1] + along[1] * half, 3)]],
                    "faces_deg": round(math.degrees(math.atan2(out[0], out[1])) % 360, 1),
                    "lon": lon0 + at[0] / kx, "lat": lat0 + at[1] / M_PER_DEG,
                })
        plan_rooms.append({"id": room["id"], "name": _name(room) or None, "walls": walls, "outdoor": room["id"] in outdoor})

    openings = []
    for sides in seen.values():
        indoors = [s for s in sides if s["room_id"] not in outdoor]
        if len(sides) == 1:
            one, outside = sides[0], sides[0]["room_id"] not in outdoor
        elif len(indoors) == 1:
            one, outside = indoors[0], True       # a door between a room and the patio: outside, seen from the room
        else:
            one, outside = sides[0], False
        openings.append({**{k: v for k, v in one.items() if k != "room_id"}, "outside": outside})
    return {"scan_id": scan.get("id"), "scan_name": scan.get("name"), "origin": {"lon": lon0, "lat": lat0}, "placement_error_m": round(worst, 3),
            "rooms": plan_rooms, "openings": openings}


def facing(plan: dict, lon: float, lat: float) -> dict:
    """Where a point on the site lies from the scanned space, and which of its outside openings face it."""
    kx = M_PER_DEG * math.cos(math.radians(plan["origin"]["lat"]))
    east, north = (lon - plan["origin"]["lon"]) * kx, (lat - plan["origin"]["lat"]) * M_PER_DEG
    found = []
    for o in plan["openings"]:
        if not o["outside"]:
            continue
        de, dn = east - o["at"][0], north - o["at"][1]
        metres = math.hypot(de, dn)
        if metres < 0.5:
            continue
        off = abs((math.degrees(math.atan2(de, dn)) - o["faces_deg"] + 180) % 360 - 180)
        if off <= FACING_WITHIN_DEG:
            found.append({"id": o["id"], "kind": o["kind"], "room": o["room"], "width_m": o["width_m"], "height_m": o["height_m"],
                          "metres": round(metres, 1), "off_deg": round(off)})
    found.sort(key=lambda f: (-(f["width_m"] * (f["height_m"] or 1)), f["metres"]))
    return {"target": {"east": round(east, 2), "north": round(north, 2)}, "facing": found}


def sentence(scan_name: str | None, found: list[dict]) -> str:
    """The measured fact in words. It speaks only for the one scanned space, which is all that was measured."""
    where = scan_name or "the scanned space"
    if not found:
        return f"No window or outside door in {where} faces it."
    first = found[0]
    size = f"{first['width_m']:.1f} m wide" + (f" by {first['height_m']:.1f} m" if first["height_m"] else "")
    what = f"{(first['room'] + ' ') if first['room'] else ''}{first['kind']}".strip()
    more = len(found) - 1
    also = f" {more} other opening{'s' if more != 1 else ''} in this unit face{'s' if more == 1 else ''} it too." if more else ""
    return f"In {where}, the {what.lower()}, {size}, faces it from about {round(first['metres'])} m.{also}"


def for_plan(site_data: dict, plan: dict, within_m: float = 80.0) -> dict[str, Any]:
    """For each outside action in a plan: the nearest placed scan and what in it faces the action, plus each such scan's plan."""
    scans = [s for s in site_data.get("scans") or [] if any(w.get("lon") is not None for w in s.get("sweeps") or [])]
    plans: dict[str, dict | None] = {}
    actions: dict[str, Any] = {}
    for action in plan.get("actions") or []:
        spot = action.get("site")
        if not spot or action.get("interior"):
            continue
        kx = M_PER_DEG * math.cos(math.radians(spot["lat"]))
        best: tuple[float, dict] | None = None
        for scan in scans:
            near = min(math.hypot((w["lon"] - spot["lon"]) * kx, (w["lat"] - spot["lat"]) * M_PER_DEG)
                       for w in scan["sweeps"] if w.get("lon") is not None and w.get("lat") is not None)
            if best is None or near < best[0]:
                best = (near, scan)
        if best is None or best[0] > within_m:
            continue
        scan = best[1]
        if scan["id"] not in plans:
            plans[scan["id"]] = layout(scan, fetch(scan["id"]))
        drawn = plans[scan["id"]]
        if drawn is None:
            continue
        result = facing(drawn, spot["lon"], spot["lat"])
        metres = math.hypot(result["target"]["east"], result["target"]["north"])
        actions[action["id"]] = {**result, "scan_id": scan["id"], "metres": round(metres, 1),
                                 "bearing_deg": round(math.degrees(math.atan2(result["target"]["east"], result["target"]["north"])) % 360, 1),
                                 "line": sentence(drawn.get("scan_name"), result["facing"])}
    # Each scanned space is drawn once however many actions it is the nearest scan to.
    return {"plans": {k: v for k, v in plans.items() if v is not None}, "actions": actions}
