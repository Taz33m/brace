"""Looking for the ways between levels that a scan does not walk through: lifts.

A scan's positions follow where the camera was carried. That includes the stairs and never the inside
of a lift. So a step-free way between levels has to be found by looking: every position's view is
shown once to the vision model, which says whether lift doors are in sight, in which direction and how
near. Sightings that agree from several positions give a place for the lift on each level, and a lift
seen at the same spot on two levels is a way between them.

This is the panorama-search problem doing a job: nothing in the wall data says where a lift is.
A lift found this way was seen, not ridden. Whoever relies on it is told so.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import matterport, vision
from .config import CACHE_DIR, VISION_MODEL

OUT = CACHE_DIR / "open" / "wayfind"
MAX_LOOKS = 80                     # paid looks this module may make for one building
NEAR_M = {"near": 2.5, "middle": 6.0, "far": 14.0}
SAME_LIFT_M = 6.0                  # sightings this close together on one level are the same lift
SAME_SHAFT_M = 6.0                 # a lift on two levels is one shaft when its two places are this close in plan

PROMPT = (
    "This strip shows four views from one spot inside a building, side by side. Panel 1 is on the left; each panel to the "
    "right is turned a further 90 degrees clockwise. Look for lift doors (elevator doors): closed or open sliding doors in "
    "a wall with a call button or a floor indicator beside or above them. A plain door, a glass door, a stair door or a "
    "cupboard is not a lift. If you can see lift doors, give the panel they are in (1 to 4), how far across that panel "
    "their middle is (0 at its left edge, 1 at its right edge), and how near they are: `near` (within about 3 metres), "
    "`middle` (3 to 10 metres) or `far`. If you are not sure they are lift doors, say they are not seen. Also say "
    "whether a staircase is in view.")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lift_seen", "stairs_seen"], "properties": {
    "lift_seen": {"type": "boolean"}, "panel": {"type": "integer", "enum": [1, 2, 3, 4]}, "across": {"type": "number"},
    "how_near": {"type": "string", "enum": ["near", "middle", "far"]}, "what_marks_it": {"type": "string"}, "stairs_seen": {"type": "boolean"}}}


def _path(model_id: str) -> Path:
    return OUT / model_id / "looks.json"


def looks(model_id: str) -> dict[str, dict]:
    try:
        return json.loads(_path(model_id).read_text())
    except (OSError, ValueError):
        return {}


def look_around(model_id: str, position_ids: list[str], client=None, workers: int = 6) -> dict[str, dict]:
    """Show each position's view to the vision model once and keep what it said. Positions already looked at are not looked at again."""
    known = looks(model_id)
    todo = [p for p in position_ids if p not in known]
    if not todo:
        return known
    if len(known) + len(todo) > MAX_LOOKS:
        todo = todo[:max(0, MAX_LOOKS - len(known))]
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    matterport.download_faces(model_id, todo, list(matterport.SIDE_FACES))

    def one(position_id: str) -> tuple[str, dict | None]:
        try:
            resp = client.messages.create(
                model=VISION_MODEL, max_tokens=400, output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": [vision.image_block(vision.strip(model_id, position_id), max_side=2048), {"type": "text", "text": PROMPT}]}])
            if resp.stop_reason == "refusal":
                return position_id, None
            return position_id, json.loads(next(b.text for b in resp.content if b.type == "text"))
        except Exception:
            return position_id, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for position_id, said in pool.map(one, todo):
            if said is not None:
                known[position_id] = said
    _path(model_id).parent.mkdir(parents=True, exist_ok=True)
    _path(model_id).write_text(json.dumps(known, indent=1))
    return known


def lifts(where: dict, seen: dict[str, dict] | None = None) -> list[dict]:
    """Lifts that join two levels, from where positions on each level saw lift doors.

    Each sighting is a direction and a rough distance from a position whose place and heading are known,
    which puts a point on the plan. Points close together on one level are one lift; a lift on two levels
    at about the same spot in plan is one shaft. Returned with the position nearest it on each level.
    """
    seen = looks(where["model_id"]) if seen is None else seen
    at = {p["id"]: p for p in where["positions"]}
    spots: dict[int, list[dict]] = {}
    for position_id, said in seen.items():
        p = at.get(position_id)
        if not p or not said.get("lift_seen") or p.get("heading") is None or said.get("panel") is None:
            continue
        # The position's heading is a compass bearing; the model's x runs east and y north once placed, so use the bearing on the map
        # and carry the point back into the model's own metres through two placed positions.
        bearing = (p["heading"] + 90 * (said["panel"] - 1) + (min(1.0, max(0.0, said.get("across", 0.5))) - 0.5) * 90) % 360
        reach = NEAR_M.get(said.get("how_near") or "middle", 6.0)
        spots.setdefault(p["level"], []).append({"from": position_id, "bearing": bearing, "reach": reach, "near": said.get("how_near"), "why": said.get("what_marks_it")})
    north = _north_in_model(where)
    if north is None:
        return []
    found: dict[int, list[dict]] = {}
    for level, sightings in spots.items():
        groups: list[dict] = []
        for s in sightings:
            p = at[s["from"]]
            turn = math.radians(s["bearing"]) - north           # the bearing as an angle in the model's own frame, clockwise from its +y
            x, y = p["x"] + s["reach"] * math.sin(turn), p["y"] + s["reach"] * math.cos(turn)
            weight = {"near": 3.0, "middle": 1.5, "far": 0.5}.get(s["near"] or "middle", 1.0)
            g = next((g for g in groups if math.hypot(g["x"] - x, g["y"] - y) <= SAME_LIFT_M), None)
            if g is None:
                groups.append({"x": x, "y": y, "w": weight, "seen_from": [s["from"]], "marks": [s["why"]] if s["why"] else []})
            else:
                g["x"], g["y"] = (g["x"] * g["w"] + x * weight) / (g["w"] + weight), (g["y"] * g["w"] + y * weight) / (g["w"] + weight)
                g["w"] += weight
                g["seen_from"].append(s["from"])
                if s["why"]:
                    g["marks"].append(s["why"])
        found[level] = groups
    out = []
    levels = sorted(found)
    for i, lower in enumerate(levels):
        for upper in levels[i + 1:]:
            for a in found[lower]:
                b = min(found[upper], key=lambda g: math.hypot(g["x"] - a["x"], g["y"] - a["y"]), default=None)
                if b is None or math.hypot(b["x"] - a["x"], b["y"] - a["y"]) > SAME_SHAFT_M:
                    continue
                ends = []
                for level, g in ((lower, a), (upper, b)):
                    on = [p for p in where["positions"] if p["level"] == level]
                    nearest = min(on, key=lambda p: math.hypot(p["x"] - g["x"], p["y"] - g["y"]))
                    ends.append({"level": level, "position_id": nearest["id"], "metres_from_position": round(math.hypot(nearest["x"] - g["x"], nearest["y"] - g["y"]), 1),
                                 "x": round(g["x"], 1), "y": round(g["y"], 1), "seen_from": len(g["seen_from"]), "marks": g["marks"][:2]})
                out.append({"levels": [lower, upper], "ends": ends, "sightings": len(a["seen_from"]) + len(b["seen_from"]),
                            "basis": "lift doors seen from scan positions on both levels; the scan does not go inside the lift"})
    return out


def _north_in_model(where: dict) -> float | None:
    """The angle, clockwise from the model's +y axis, at which compass north lies. From two placed positions."""
    placed = [p for p in where["positions"] if p.get("lon") is not None and p.get("lat") is not None]
    if len(placed) < 2:
        return None
    a = placed[0]
    b = max(placed, key=lambda p: math.hypot(p["x"] - a["x"], p["y"] - a["y"]))
    east = (b["lon"] - a["lon"]) * math.cos(math.radians(a["lat"]))
    compass = math.atan2(east, b["lat"] - a["lat"])                       # bearing of a -> b on the map
    model = math.atan2(b["x"] - a["x"], b["y"] - a["y"])                  # the same direction, clockwise from the model's +y
    return compass - model
