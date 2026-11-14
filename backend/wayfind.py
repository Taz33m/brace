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
    floor_of = {f.get("sequence"): f["id"] for f in m["floors"]}
    return {"model_id": model_id, "name": m.get("name"), "levels": [{"level": lv, "label": f"Level {i + 1}", "floor_id": floor_of.get(lv), "positions": sum(1 for p in positions if p["level"] == lv)}
                                                                     for i, lv in enumerate(levels)],
            "rooms": rooms, "positions": positions, "placed_by": "Matterport's own placement of the scan" if placed else None}


def _distance(a: dict, b: dict) -> float:
    return math.dist((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))


# ---- which links between positions a person, or a wheelchair, can actually take ------------------------
# Two positions that see each other are not always a way: across an atrium they see each other through air.
FLAT_M = 0.08             # a height difference this small is the camera's own wobble: level ground
RAMP = 1 / 12             # the steepest slope a wheelchair is asked to take, rise over run
STEP_M = 0.3              # up to this, with too little run for a ramp, it is a step or a kerb
FLIGHT_M = 2.4            # the most a person climbs between two positions on a stair: one flight
LIFT_AS_M = 15.0          # what waiting for and riding a lift costs, counted as walking metres
CHAIR_WIDTH_IN = 27.0     # a common manual wheelchair, when no size is given
SPARE_IN = 2.0            # room a chair needs beyond its own width to get through a doorway
LEAF_M = 0.05             # width a doorway loses to the door's leaf and stop (an estimate)
INCH = 0.0254


def walls(model_id: str, refresh: bool = False) -> list[dict]:
    """Matterport's wall graph for each floor: wall edges, and the measured openings in them."""
    path = matterport.MP_CACHE / "walls" / f"{model_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = matterport.gql('{ model(id:"%s"){ floors{ id label vertices{ id position{ x y } } edges{ id type thickness vertices{ id } '
                          'openings{ width type relativeCenter } } } } }' % model_id)["model"]["floors"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def _segments(floor: dict) -> list[dict]:
    """A floor's solid walls as line segments, each with the spans along it that are open (doorways)."""
    at = {v["id"]: (v["position"]["x"], v["position"]["y"]) for v in floor.get("vertices") or []}
    out = []
    for e in floor.get("edges") or []:
        ends = [at.get(v["id"]) for v in e.get("vertices") or []]
        if e.get("type") != "wall" or len(ends) != 2 or None in ends:
            continue
        (ax, ay), (bx, by) = ends
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-6:
            continue
        doors = [{"t0": o["relativeCenter"] - o["width"] / 2 / length, "t1": o["relativeCenter"] + o["width"] / 2 / length,
                  "width_m": o["width"]} for o in e.get("openings") or [] if o.get("type") == "doorway" and o.get("width", 0) >= 18 * INCH]
        out.append({"a": (ax, ay), "b": (bx, by), "doors": doors})
    return out


def _crossing(p: tuple, q: tuple, seg: dict) -> float | None:
    """Where along a wall a straight walk from p to q crosses it (0 to 1 along the wall), or None."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p, q, seg["a"], seg["b"]
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-12:
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    return u if 0.02 < t < 0.98 and 0.0 <= u <= 1.0 else None


TURN_IN = 60.0            # the circle a wheelchair needs to turn round in (the ADA figure)
REACH_M = 12.0            # walls further off than this to one side are not counted: the space is open


def _ray(origin: tuple, direction: tuple, segments: list[dict]) -> float | None:
    """How far it is from a point to the first solid wall in a direction. None when nothing is hit within reach."""
    (ox, oy), (dx, dy) = origin, direction
    nearest = None
    for seg in segments:
        (ax, ay), (bx, by) = seg["a"], seg["b"]
        ex, ey = bx - ax, by - ay
        d = dx * ey - dy * ex
        if abs(d) < 1e-12:
            continue
        t = ((ax - ox) * ey - (ay - oy) * ex) / d          # along the ray, metres
        u = ((ax - ox) * dy - (ay - oy) * dx) / d          # along the wall, 0 to 1
        if t <= 0.05 or t > REACH_M or not 0.0 <= u <= 1.0 or any(o["t0"] <= u <= o["t1"] for o in seg["doors"]):
            continue
        nearest = t if nearest is None else min(nearest, t)
    return nearest


def passage(a: dict, b: dict, segments: list[dict]) -> float | None:
    """The narrowest width between walls along a straight walk, measured across it every half metre.
    None when one side or the other is open: an atrium has no width to squeeze through."""
    run = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    if run < 0.5:
        return None
    ux, uy = (b["x"] - a["x"]) / run, (b["y"] - a["y"]) / run
    narrowest = None
    for i in range(1, max(2, int(run / 0.5))):
        at = (a["x"] + ux * i * 0.5, a["y"] + uy * i * 0.5)
        left, right = _ray(at, (-uy, ux), segments), _ray(at, (uy, -ux), segments)
        if left is None or right is None:
            continue
        narrowest = left + right if narrowest is None else min(narrowest, left + right)
    return None if narrowest is None else round(narrowest, 2)


def link(a: dict, b: dict, segments: list[dict] | None = None) -> dict | None:
    """What kind of way it is from one position to one it sees, or None when it is only a line of sight.

    level, slope (a ramp a chair can take), step, or stairs. On level ground a wall in between makes it no
    way at all unless the walk passes through a measured doorway, whose clear width then rides with the link.
    """
    rise, run = b["z"] - a["z"], math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    if abs(rise) <= FLAT_M:
        kind = "level"
    elif abs(rise) <= run * RAMP:
        kind = "slope"
    elif abs(rise) <= STEP_M:
        kind = "step"
    elif abs(rise) <= FLIGHT_M and run >= abs(rise) * 0.8:
        kind = "stairs"
    else:
        return None
    doors = []
    if segments and a.get("level") == b.get("level"):
        for seg in segments:
            u = _crossing((a["x"], a["y"]), (b["x"], b["y"]), seg)
            if u is None:
                continue
            door = next((d for d in seg["doors"] if d["t0"] <= u <= d["t1"]), None)
            if door is None:
                return None                                   # through a wall: they see each other through glass
            doors.append({"width_in": round(door["width_m"] / INCH, 1), "clear_in": round((door["width_m"] - LEAF_M) / INCH, 1)})
    wide = passage(a, b, segments) if segments and a.get("level") == b.get("level") else None
    return {"kind": kind, "metres": round(math.hypot(run, rise), 2), "rise_m": round(rise, 2), "run_m": round(run, 2), "doors": doors, "passage_m": wide}


def ways(where: dict, lifts: list[dict] | None = None, wall_graph: list[dict] | None = None) -> dict[str, dict[str, dict]]:
    """Every real way between positions: {from: {to: link}}. Lifts found by looking are added as ways of their own."""
    at = {p["id"]: p for p in where["positions"]}
    by_level: dict[int, list[dict]] = {}
    for floor in wall_graph or []:
        level = next((lv["level"] for lv in where["levels"] if lv.get("floor_id") == floor["id"]), None)
        if level is not None:
            by_level[level] = _segments(floor)
    out: dict[str, dict[str, dict]] = {p["id"]: {} for p in where["positions"]}
    for p in where["positions"]:
        for n in p["sees"]:
            got = link(p, at[n], by_level.get(p["level"]))
            if got:
                out[p["id"]][n] = got
    for lift in lifts or []:
        lo, hi = lift["ends"]
        for a, b in ((lo, hi), (hi, lo)):
            out[a["position_id"]][b["position_id"]] = {
                "kind": "lift", "metres": round(a["metres_from_position"] + b["metres_from_position"], 1), "rise_m": round(at[b["position_id"]]["z"] - at[a["position_id"]]["z"], 2),
                "run_m": 0.0, "doors": [], "passage_m": None, "lift_at": {"x": a["x"], "y": a["y"]}, "basis": lift["basis"]}
    return out


def _allowed(way: dict, mover: str, chair_in: float) -> bool:
    if mover == "wheelchair":
        if way["kind"] in ("step", "stairs"):
            return False
        if way.get("passage_m") is not None and way["passage_m"] < (chair_in + SPARE_IN) * INCH:
            return False
        return all(d["clear_in"] >= chair_in + SPARE_IN for d in way["doors"])
    return True


_MEASURED: dict[str, tuple[str, dict]] = {}


def measured_ways(where: dict, lifts: list[dict] | None, wall_graph: list[dict] | None) -> dict[str, dict[str, dict]]:
    """`ways` for a building, worked out once: measuring every link against every wall takes seconds, and
    nothing about it changes until a lift is found or the walls are fetched again."""
    stamp = json.dumps([len(where["positions"]), lifts, len(wall_graph or [])], sort_keys=True)
    kept = _MEASURED.get(where["model_id"])
    if kept is None or kept[0] != stamp:
        kept = (stamp, ways(where, lifts, wall_graph))
        _MEASURED[where["model_id"]] = kept
    return kept[1]


def route(where: dict, start_id: str, room_id: str, mover: str = "walking", chair_in: float = CHAIR_WIDTH_IN,
          lifts: list[dict] | None = None, wall_graph: list[dict] | None = None) -> dict | None:
    """The shortest real way from a position to the middle of a room, for someone walking or in a wheelchair.

    Returns None when there is no way of that kind. The route says, leg by leg, what it is (level, slope,
    stairs, lift), how far and how much it rises, and every doorway it passes with its clear width.
    """
    at = {p["id"]: p for p in where["positions"]}
    inside = [p for p in where["positions"] if p["room_id"] == room_id]
    if start_id not in at or not inside:
        return None
    cx, cy = sum(p["x"] for p in inside) / len(inside), sum(p["y"] for p in inside) / len(inside)
    goal = min(inside, key=lambda p: math.hypot(p["x"] - cx, p["y"] - cy))["id"]
    graph = measured_ways(where, lifts, wall_graph)
    best, came, heap = {start_id: 0.0}, {}, [(0.0, start_id)]
    while heap:
        d, a = heapq.heappop(heap)
        if a == goal:
            break
        if d > best.get(a, math.inf):
            continue
        for b, way in graph[a].items():
            if not _allowed(way, mover, chair_in):
                continue
            nd = d + way["metres"] + (LIFT_AS_M if way["kind"] == "lift" else 0.0)
            if nd < best.get(b, math.inf):
                best[b], came[b] = nd, a
                heapq.heappush(heap, (nd, b))
    if goal not in best:
        return None
    path = [goal]
    while path[-1] != start_id:
        path.append(came[path[-1]])
    path.reverse()
    north = _north(where)
    legs = []
    for a, b in zip(path, path[1:]):
        way = graph[a][b]
        toward = _bearing(at[a], at[b])
        if way["kind"] == "lift" and north is not None:
            # A lift is reached by going to its doors, which are beside this position, not by walking to the next one.
            toward = round(math.degrees(math.atan2(way["lift_at"]["x"] - at[a]["x"], way["lift_at"]["y"] - at[a]["y"]) + north) % 360, 1)
        legs.append({"from": a, "to": b, "kind": way["kind"], "metres": way["metres"], "rise_m": way["rise_m"], "bearing": toward,
                     "level_change": (at[b]["level"] or 0) - (at[a]["level"] or 0), "doors": way["doors"], "passage_m": way.get("passage_m")})
    doors = [d for g in legs for d in g["doors"]]
    flights = [g for g in legs if g["kind"] == "stairs"]
    out = {"mover": mover, "positions": path, "legs": legs, "arrived": len(path) == 1,
           "metres": round(sum(g["metres"] for g in legs), 1), "levels_changed": sum(1 for g in legs if g["level_change"]),
           "stairs": {"flights": len(flights), "rise_m": round(sum(abs(g["rise_m"]) for g in flights), 1)} if flights else None,
           "lift": any(g["kind"] == "lift" for g in legs), "slopes": sum(1 for g in legs if g["kind"] == "slope"),
           "doorways": len(doors), "narrowest_doorway_in": min((d["clear_in"] for d in doors), default=None),
           "narrowest_passage_m": min((g["passage_m"] for g in legs if g["passage_m"] is not None), default=None)}
    if mover == "wheelchair":
        out["chair_width_in"] = chair_in
    out["says"] = _says(out)
    return out


def _north(where: dict) -> float | None:
    """The angle, clockwise from the scan's own +y axis, at which compass north lies."""
    placed = [p for p in where["positions"] if p.get("lon") is not None and p.get("lat") is not None]
    if len(placed) < 2:
        return None
    a = placed[0]
    b = max(placed, key=lambda p: math.hypot(p["x"] - a["x"], p["y"] - a["y"]))
    east = (b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    return math.atan2(east, b["lat"] - a["lat"]) - math.atan2(b["x"] - a["x"], b["y"] - a["y"])


def _bearing(a: dict, b: dict) -> float | None:
    """Compass bearing from one position to the next, when the scan is placed on the map."""
    if None in (a.get("lon"), a.get("lat"), b.get("lon"), b.get("lat")):
        return None
    east = (b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    return round(math.degrees(math.atan2(east, b["lat"] - a["lat"])) % 360, 1)


def _says(way: dict) -> str:
    """The route in one or two short sentences, with the measurements that matter to whoever is moving."""
    parts = [f"About {round(way['metres'])} metres"]
    if way["stairs"]:
        n = way["stairs"]["flights"]
        parts.append(f"down {n} flight{'s' if n != 1 else ''} of stairs" if sum(g["rise_m"] for g in way["legs"] if g["kind"] == "stairs") < 0 else f"up {n} flight{'s' if n != 1 else ''} of stairs")
    if way["lift"]:
        parts.append("by the lift")
    line = ", ".join(parts) + "."
    if way["mover"] == "wheelchair":
        line += " No steps on the way."
        if way["narrowest_doorway_in"] is not None:
            line += f" The narrowest doorway is {way['narrowest_doorway_in']:g} inches clear; the chair is {way['chair_width_in']:g}."
        if way["narrowest_passage_m"] is not None:
            tight = way["narrowest_passage_m"]
            line += (f" The narrowest point between walls is {tight:g} metres, against a chair {way['chair_width_in']:g} inches wide"
                     + (", with room to turn round." if tight >= TURN_IN * INCH else ", too tight to turn round in."))
        if way["lift"]:
            line += " The lift was seen from the scan, not ridden: check it is working."
    return line


def find(model_id: str, query: str, start_id: str | None = None, mover: str = "walking", chair_in: float = CHAIR_WIDTH_IN) -> dict:
    """Answer "where is X" for a scanned building: the place, the room it is, where that is on the map, and the way
    there for someone walking or in a wheelchair. For a wheelchair it also says what the walking way used that the
    chair cannot, so the change is plain."""
    from . import wayfind_look
    where = place(model_id)
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
        return {"found": False, "asked": query, "event": happening["event"] if happening else None, "mover": mover,
                "say": (f"{happening['event']} is at {happening['place']}, but I cannot match that to a room in this scan." if happening
                        else "I do not have that on the schedule, and no room in this scan matches it.")}
    inside = [p for p in where["positions"] if p["room_id"] == room["id"]]
    cx, cy = sum(p["x"] for p in inside) / len(inside), sum(p["y"] for p in inside) / len(inside)
    centre = min(inside, key=lambda p: math.hypot(p["x"] - cx, p["y"] - cy))
    start = start_id if start_id and any(p["id"] == start_id for p in where["positions"]) else None
    level = next((lv["label"] for lv in where["levels"] if lv["level"] == room["level"]), None)
    way = on_foot = None
    lifts = wayfind_look.lifts(where)
    try:
        graph = walls(model_id)
    except matterport.MatterportError:
        graph = None
    if start:
        on_foot = route(where, start, room["id"], "walking", chair_in, lifts, graph)
        way = on_foot if mover == "walking" else route(where, start, room["id"], mover, chair_in, lifts, graph)
    said = (f"{happening['event']} is at {happening['place']}. " if happening else "") + f"That is the {room['type']} on {level}, about {room['area_sqft']:,} square feet."
    if start and way:
        said += f" {way['says']}"
    elif start and mover == "wheelchair":
        said += (" I cannot find a step-free way there in this scan." +
                 (f" The only way I can see is {on_foot['stairs']['flights']} flights of stairs." if on_foot and on_foot.get("stairs") else ""))
    elif start:
        said += " I cannot find a way there through this scan."
    changed = None
    if mover == "wheelchair" and on_foot and way and on_foot["positions"] != way["positions"]:
        changed = {"instead_of": ("the stairs" if on_foot.get("stairs") else "the shorter way"), "walking_metres": on_foot["metres"], "wheelchair_metres": way["metres"],
                   "walking_positions": on_foot["positions"], "flights_avoided": (on_foot.get("stairs") or {}).get("flights", 0),
                   "rise_avoided_m": (on_foot.get("stairs") or {}).get("rise_m", 0.0)}
    return {
        "found": True, "asked": query, "event": happening["event"] if happening else None, "place": happening["place"] if happening else room["type"],
        "schedule_source": happening.get("source") if happening else None, "mover": mover, "chair_width_in": chair_in if mover == "wheelchair" else None,
        "room": {"id": room["id"], "type": room["type"], "typed_by": room["typed_by"], "confidence": room["confidence"], "area_sqft": room["area_sqft"],
                 "level": level, "position_id": centre["id"], "lon": centre["lon"], "lat": centre["lat"]},
        "route": way, "changed": changed, "no_way": bool(start and not way), "lifts_found": len(lifts),
        "say": said,
    }
