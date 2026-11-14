"""Finding a place inside a scanned building, and the way to it.

"Where is the push-up challenge?" has three parts, and each rests on something different:
  1. What is on where: a schedule someone gave us (data/events/events.json). The scan does not know this.
  2. Which room that is: the room types Brace gave the scan's unlabelled rooms (the commercial-spaces
     problem), matched to the place's name. A forum is the scan's atrium.
  3. How to get there: the scan's own positions and which of them see each other. The shortest walk
     through that graph, from where you stand, is the route.

Where each position sits on the map comes from Matterport's own placement of the scan. Nothing here
calls a model. A place the schedule does not name, or a room the scan cannot match, is said to be unknown.
"""
from __future__ import annotations

import heapq
import json
import math
import re
from pathlib import Path

from . import building, geo, matterport
from .config import CACHE_DIR, DATA_DIR

EVENTS_FILE = DATA_DIR / "events" / "events.json"
ROOM_TYPES = CACHE_DIR / "open" / "commercial"

# What people call a kind of room, against the types Brace assigns. First match wins.
SAME_KIND: dict[str, set[str]] = {
    "atrium": {"forum", "atrium", "hall", "commons", "concourse", "lobby"},
    "meeting room": {"meeting", "conference", "seminar", "boardroom"},
    "classroom": {"classroom", "lecture", "class"},
    "office": {"office"},
    "restroom": {"restroom", "bathroom", "toilet", "washroom"},
    "kitchen": {"kitchen", "cafe", "pantry"},
    "corridor": {"corridor", "hallway"},
    "stairwell": {"stairs", "stair", "stairwell"},
}
_FILLER = {"the", "a", "an", "is", "where", "wheres", "at", "in", "of", "to", "and", "s", "me", "take", "find", "show", "how", "do", "i", "get"}


def _words(text: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower().replace("-", "")) if w not in _FILLER}


def events() -> list[dict]:
    try:
        return json.loads(EVENTS_FILE.read_text())
    except (OSError, ValueError):
        return []


def place(model_id: str) -> dict:
    """One scanned building as a walkable place: its levels, its typed rooms, and every scan position
    with where it is on the map, which way its first face looks, and which positions it sees."""
    m = matterport.fetch_model(model_id)
    origin = (m.get("geo") or {}).get("origin")
    frame = geo.LocalFrame(lat0=origin[1], lon0=origin[0]) if origin else None
    placed = {s["id"]: s for s in (building._scan(model_id, frame, m) or {}).get("sweeps", [])} if frame else {}
    floors = {f["id"]: f for f in m["floors"]}
    typed = {}
    try:
        typed = {r["room_id"]: r for r in json.loads((ROOM_TYPES / f"{model_id}.json").read_text()).get("rooms") or []}
    except (OSError, ValueError):
        pass
    positions = []
    for s in m["sweeps"]:
        if not s.get("has_pano", True):
            continue
        p = placed.get(s["id"]) or {}
        positions.append({"id": s["id"], "x": s["x"], "y": s["y"], "z": s["z"], "room_id": s.get("room_id"),
                          "level": (floors.get(s.get("floor_id")) or {}).get("sequence"), "lon": p.get("lon"), "lat": p.get("lat"),
                          "heading": p.get("heading"), "sees": [n for n in s.get("neighbors") or []]})
    here = {p["id"] for p in positions}
    for p in positions:
        p["sees"] = [n for n in p["sees"] if n in here]
    rooms = []
    for r in m["rooms"]:
        inside = [p for p in positions if p["room_id"] == r["id"]]
        if not inside:
            continue
        ours = (typed.get(r["id"]) or {}).get("ours") or {}
        named = (r.get("type") or "").strip().lower() not in ("", "void", "other", "hallway", "unlabelled", "unlabeled", "unknown")
        rooms.append({"id": r["id"], "level": (floors.get(r.get("floor_id")) or {}).get("sequence"), "matterport_type": r.get("type") or None,
                      "type": (r["type"].lower() if named else ours.get("type")), "typed_by": "Matterport" if named else ("Brace" if ours.get("type") else None),
                      "confidence": None if named else ours.get("confidence"), "area_sqft": round(r.get("area_sqft") or 0),
                      "positions": len(inside), "polygon": r.get("polygon")})
    levels = sorted({p["level"] for p in positions if p["level"] is not None})
    return {"model_id": model_id, "name": m.get("name"), "levels": [{"level": lv, "label": f"Level {i + 1}", "positions": sum(1 for p in positions if p["level"] == lv)}
                                                                     for i, lv in enumerate(levels)],
            "rooms": rooms, "positions": positions, "placed_by": "Matterport's own placement of the scan" if placed else None}


def _distance(a: dict, b: dict) -> float:
    return math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))


def route(where: dict, start_id: str, room_id: str) -> dict | None:
    """The shortest walk from one scan position to a room, through positions that see each other."""
    at = {p["id"]: p for p in where["positions"]}
    if start_id not in at:
        return None
    goals = {p["id"] for p in where["positions"] if p["room_id"] == room_id}
    if not goals:
        return None
    best, came, heap = {start_id: 0.0}, {}, [(0.0, start_id)]
    end = None
    while heap:
        d, a = heapq.heappop(heap)
        if d > best.get(a, math.inf):
            continue
        if a in goals and a != start_id:
            end = a
            break
        for b in at[a]["sees"]:
            nd = d + _distance(at[a], at[b])
            if nd < best.get(b, math.inf):
                best[b], came[b] = nd, a
                heapq.heappush(heap, (nd, b))
    if end is None:
        return {"positions": [start_id], "metres": 0.0, "legs": [], "arrived": start_id in goals} if start_id in goals else None
    # Keep walking to the middle of the room: the nearest position in it is only its doorway.
    inside = [at[g] for g in goals]
    cx, cy = sum(p["x"] for p in inside) / len(inside), sum(p["y"] for p in inside) / len(inside)
    middle = min(inside, key=lambda p: math.hypot(p["x"] - cx, p["y"] - cy))["id"]
    path = [end]
    while path[-1] != start_id:
        path.append(came[path[-1]])
    path.reverse()
    if middle != end:
        tail = _within(at, goals, end, middle)
        path += tail[1:] if tail else []
    legs, total = [], 0.0
    for a, b in zip(path, path[1:]):
        d = _distance(at[a], at[b])
        total += d
        dx, dy = at[b]["x"] - at[a]["x"], at[b]["y"] - at[a]["y"]
        legs.append({"from": a, "to": b, "metres": round(d, 1), "level_change": (at[b]["level"] or 0) - (at[a]["level"] or 0),
                     "bearing": _bearing(at[a], at[b]), "model_angle_deg": round(math.degrees(math.atan2(dy, dx)), 1)})
    return {"positions": path, "metres": round(total, 1), "legs": legs, "arrived": False,
            "levels_changed": sum(1 for g in legs if g["level_change"]), "says": _says(legs, total)}


def _within(at: dict, allowed: set[str], start: str, end: str) -> list[str] | None:
    """The shortest walk between two positions without leaving a set of positions."""
    best, came, heap = {start: 0.0}, {}, [(0.0, start)]
    while heap:
        d, a = heapq.heappop(heap)
        if a == end:
            path = [end]
            while path[-1] != start:
                path.append(came[path[-1]])
            return path[::-1]
        for b in at[a]["sees"]:
            if b not in allowed:
                continue
            nd = d + _distance(at[a], at[b])
            if nd < best.get(b, math.inf):
                best[b], came[b] = nd, a
                heapq.heappush(heap, (nd, b))
    return None


def _bearing(a: dict, b: dict) -> float | None:
    """Compass bearing from one position to the next, when the scan is placed on the map."""
    if None in (a.get("lon"), a.get("lat"), b.get("lon"), b.get("lat")):
        return None
    east = (b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    return round(math.degrees(math.atan2(east, b["lat"] - a["lat"])) % 360, 1)


def _says(legs: list[dict], total: float) -> str:
    down = sum(1 for g in legs if g["level_change"] < 0)
    up = sum(1 for g in legs if g["level_change"] > 0)
    change = f", {'down' if down else 'up'} one level" if (down or up) == 1 and not (down and up) else (", changing level" if down or up else "")
    return f"About {round(total)} metres{change}."


def find(model_id: str, query: str, start_id: str | None = None) -> dict:
    """Answer "where is X" for a scanned building: the place, the room it is, where that is on the map, and the way."""
    where = place(model_id)
    asked = _words(query)
    # "push up", "push-up" and "pushup" are one thing said three ways: compare with spaces and marks taken out.
    squash = lambda text: re.sub(r"[^a-z0-9]", "", (text or "").lower())
    happening = next((e for e in events() if e.get("model_id") == model_id and
                      any(len(squash(name)) >= 5 and squash(name) in squash(query) for name in [e["event"], *e.get("also_called", [])])), None)
    name = happening["place"] if happening else query
    wanted = _words(name)
    kind = next((k for k, said in SAME_KIND.items() if wanted & said), None)
    rooms = [r for r in where["rooms"] if r["type"] and (r["type"] == kind or _words(r["type"]) & wanted)]
    room = max(rooms, key=lambda r: r["area_sqft"]) if rooms else None
    if room is None:
        return {"found": False, "asked": query, "event": happening["event"] if happening else None,
                "say": (f"{happening['event']} is at {happening['place']}, but I cannot match that to a room in this scan." if happening
                        else "I do not have that on the schedule, and no room in this scan matches it.")}
    inside = [p for p in where["positions"] if p["room_id"] == room["id"]]
    cx, cy = sum(p["x"] for p in inside) / len(inside), sum(p["y"] for p in inside) / len(inside)
    centre = min(inside, key=lambda p: math.hypot(p["x"] - cx, p["y"] - cy))
    start = start_id if start_id and any(p["id"] == start_id for p in where["positions"]) else None
    way = route(where, start, room["id"]) if start else None
    level = next((lv["label"] for lv in where["levels"] if lv["level"] == room["level"]), None)
    return {
        "found": True, "asked": query, "event": happening["event"] if happening else None, "place": happening["place"] if happening else room["type"],
        "schedule_source": happening.get("source") if happening else None,
        "room": {"id": room["id"], "type": room["type"], "typed_by": room["typed_by"], "confidence": room["confidence"], "area_sqft": room["area_sqft"],
                 "level": level, "position_id": centre["id"], "lon": centre["lon"], "lat": centre["lat"]},
        "route": way,
        "say": (f"{happening['event']} is at {happening['place']}. " if happening else "") +
               f"That is the {room['type']} on {level}, about {room['area_sqft']:,} square feet." + (f" {way['says']}" if way and way.get("says") else ""),
    }
