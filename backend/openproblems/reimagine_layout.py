"""Make a staged room agree between two standpoints of the same scan. A spike, with an honest verdict.

`reimagine_view.py` makes every direction from ONE standpoint agree. A second standpoint is harder: an
image service that is only shown the first staged photo invents the room again. So the furniture is
given a place in the room first:

1. find each piece in the first standpoint's staged photo and anchor it to the floor, as a box in room
   metres (its base line read off the floor, its height read off the picture, its depth ASSUMED by type);
2. draw those boxes back into the first photo to check the anchoring (free);
3. draw the same boxes, as flat coloured blocks, into the real photo of the second standpoint;
4. ask the image service to replace each block with the piece it stands for;
5. measure whether the furniture in the result is where the blocks were.

What came of it (14 November, scan 9odpSsu2KYQ, two standpoints 1.75 m apart, two paid tries): the second
standpoint shows the same pieces in the same arrangement and the room itself is untouched, but the image
service treats a block as roughly where and roughly how big, not as a mould. Plants and the lamp landed
within 0.05 m of their footprints; the sofa and the coffee table came out a tenth to a half larger than
their blocks, which puts their feet 0.2 to 0.4 m off; the rug's corners 0.2 to 0.45 m off. Drawing the
blocks' hidden edges and using stricter words did not tighten it. So: the same room to the eye in two
still pictures, not the same room to a tape measure, and not good enough to walk between standpoints.

Everything this writes is an illustration made from a generated picture. It is never evidence about the
building, and it follows the labelling rules in `reimagine.py` (a record beside every generated file).
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import reimagine as base
from . import reimagine_view as rv

# What cannot be seen from one photo is assumed by the kind of piece, and written into the layout.
# `centred`: the bottom edge found in the photo runs through the middle of the piece (a round pot or
# lamp foot), so the box sits around it; otherwise that edge is the front and the box runs back from it.
KINDS = {
    "sofa": {"depth_m": 0.9, "centred": False, "why": "a two-seat sofa is about 0.9 m deep"},
    "coffee_table": {"depth_m": 0.6, "centred": False, "why": "a coffee table is about 0.6 m deep"},
    "floor_lamp": {"depth_m": 0.4, "centred": True, "why": "a floor lamp's shade is about 0.4 m across"},
    "plant": {"depth_m": None, "centred": True, "why": "a plant is about as deep as it is wide"},
    "other": {"depth_m": 0.5, "centred": True, "why": "an unknown piece is taken to be 0.5 m deep"},
}
# Flat colours that do not occur in a grey room with a wood floor, so a leak into the result can be counted.
COLOURS = [("red", (225, 35, 35)), ("blue", (35, 80, 225)), ("yellow", (245, 205, 0)), ("green", (0, 170, 70)),
           ("magenta", (215, 30, 200)), ("cyan", (0, 200, 215)), ("purple", (120, 50, 200))]
RUG_COLOUR = ("orange", (245, 140, 20))
# Top, then the two kinds of side: just enough shading for a block to read as a solid.
SHADES = (1.0, 0.78, 0.6)

VISION_CALLS_ALLOWED = 6
SECOND_STANDPOINT_GENERATIONS_ALLOWED = 4

FIND_PROMPT = (
    "This picture is {w} by {h} pixels. Pixel x runs from 0 at the left edge to {w1} at the right edge; y runs from 0 at "
    "the top edge to {h1} at the bottom edge. It shows a room staged with furniture. List every piece that stands on the "
    "floor (furniture, lamps, potted plants). Do not list the rug, and do not list small things that sit on top of another "
    "piece. For each piece give: `name`, a short name; `kind`; `look`, a few words on its colour and material, and anything "
    "sitting on it; `box`, the tight pixel box [left, top, right, bottom] around the piece itself, not counting small things "
    "sitting on it; and `floor_left` and `floor_right`, the pixels [x, y] of the two ends of the bottom edge where the side "
    "of the piece nearest the camera meets the floor: for a sofa or a table the bottoms of its two front legs, for a plant "
    "or a lamp the left and right ends of the bottom of its pot or foot (estimate them if something stands in front). "
    "Then give `rug`, the four corners of the rug as pixels [x, y], going around the rug in order, estimating any corner "
    "that is hidden behind furniture. Be as exact as you can: these pixels are used for measuring.")
_POINT = {"type": "array", "items": {"type": "number"}}
FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "pieces": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "kind": {"type": "string", "enum": sorted(KINDS)}, "look": {"type": "string"},
                           "box": _POINT, "floor_left": _POINT, "floor_right": _POINT},
            "required": ["name", "kind", "look", "box", "floor_left", "floor_right"], "additionalProperties": False}},
        "rug": {"type": "array", "items": _POINT},
    },
    "required": ["pieces", "rug"], "additionalProperties": False,
}
BOXES_PROMPT = (
    "This picture is {w} by {h} pixels (x from 0 at the left, y from 0 at the top). For each of these things, give the tight "
    "pixel box [left, top, right, bottom] around the piece itself if it is in the picture, and say `present` false if it is "
    "not there: {names}. Also say in `note`, in one sentence, anything in the picture that looks wrong or unreal.")


def view_of(yaw_deg: float, pitch_deg: float, hfov_deg: float, width: int = 1536, height: int = 1024) -> dict:
    """One wide photo's aim, in the argument names `reimagine_view.project` takes."""
    return {"yaw_deg": yaw_deg, "pitch_deg": pitch_deg, "hfov_deg": hfov_deg, "width": width, "height": height}


# ---- finding the pieces in the staged photo ----------------------------------------------------------------

def changed(real: np.ndarray, staged: np.ndarray, threshold: float = 35.0, clean: int = 9) -> np.ndarray:
    """Which pixels the staging changed: True where any colour channel moved by more than `threshold`
    (0 to 255), after removing specks. A redraw shifts every pixel a little, so small moves do not count."""
    far = np.abs(real.astype(np.float32) - staged.astype(np.float32)).max(axis=-1) > threshold
    if clean > 1:
        far = np.asarray(Image.fromarray((far * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(clean))) > 127
    return far


def _vision_log() -> Path:
    return base.OUT / "vision_calls.json"


def vision_calls() -> int:
    p = _vision_log()
    return len(json.loads(p.read_text())) if p.exists() else 0


def _ask(image: Image.Image, prompt: str, schema: dict, what: str, client=None) -> dict:
    """One look by the vision model, called the way `backend/vision.py` does. Counted, so the cap holds."""
    import anthropic
    from .. import vision
    from ..config import VISION_MODEL
    if vision_calls() >= VISION_CALLS_ALLOWED:
        raise RuntimeError(f"all {VISION_CALLS_ALLOWED} vision calls for this work have been used")
    rows = json.loads(_vision_log().read_text()) if _vision_log().exists() else []
    _vision_log().write_text(json.dumps(rows + [{"at": base._now(), "what": what, "model": VISION_MODEL}], indent=1))
    client = client or anthropic.Anthropic()
    resp = client.messages.create(
        model=VISION_MODEL, max_tokens=2048,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [vision.image_block(image, max_side=max(image.size), quality=90), {"type": "text", "text": prompt}]}],
    )
    if resp.stop_reason == "refusal":
        raise ValueError("the vision model declined")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def find_pieces(staged_photo: str | Path, save_to: str | Path, client=None) -> dict:
    """A pixel box and the two ends of the floor edge for each piece in a staged photo, and the rug's four
    corners, from one look by the vision model. Saved, so the look is paid for once."""
    save_to = Path(save_to)
    if save_to.exists():
        return json.loads(save_to.read_text())
    with Image.open(staged_photo) as im:
        im = im.convert("RGB")
    w, h = im.size
    found = _ask(im, FIND_PROMPT.format(w=w, h=h, w1=w - 1, h1=h - 1), FIND_SCHEMA, f"find pieces in {Path(staged_photo).parent.name}", client)
    found = {"photo": str(staged_photo), "size": [w, h], **found}
    save_to.write_text(json.dumps(found, indent=1))
    return found


def find_boxes(photo: Image.Image, names: list[str], what: str, client=None) -> dict:
    """Where the vision model sees each named piece in a picture (a box, or not present), plus one remark."""
    schema = {"type": "object", "properties": {
        "pieces": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "enum": names}, "present": {"type": "boolean"}, "box": _POINT},
            "required": ["name", "present", "box"], "additionalProperties": False}},
        "note": {"type": "string"}}, "required": ["pieces", "note"], "additionalProperties": False}
    return _ask(photo, BOXES_PROMPT.format(w=photo.width, h=photo.height, names="; ".join(names)), schema, what, client)


# ---- anchoring a piece to the floor ------------------------------------------------------------------------

def _grow(reached, most: float = 1.0) -> float:
    """The smallest amount, from nothing up to `most`, at which `reached(amount)` turns true."""
    if reached(0.0):
        return 0.0
    low, high = 0.0, most
    for _ in range(30):
        mid = (low + high) / 2
        low, high = (low, mid) if reached(mid) else (mid, high)
    return high


def corners(piece: dict) -> list[tuple[float, float, float]]:
    """A box's eight corners (east, north, height): the four on the floor, then the four on top, same order."""
    return [(e, n, 0.0) for e, n in piece["footprint"]] + [(e, n, piece["height_m"]) for e, n in piece["footprint"]]


def _span(footprint: list, tall: float, camera: dict, view: dict) -> tuple[float, float, float] | None:
    """The left-most column, right-most column and top row that a box of this footprint and height reaches in the photo."""
    seen = [p for p in rv.project([(e, n, z) for e, n in footprint for z in (0.0, tall)], camera, **view) if p]
    return (min(p[0] for p in seen), max(p[0] for p in seen), min(p[1] for p in seen)) if seen else None


def _sight(pixel: tuple[float, float], camera: dict, view: dict) -> np.ndarray:
    """The direction (east, north, up) in which a standpoint's wide photo looks through one pixel."""
    forward, right = rv._room_axes(camera)
    focal = (view["width"] / 2) / math.tan(math.radians(view["hfov_deg"]) / 2)
    r = rv._turn(view["yaw_deg"], view["pitch_deg"]) @ np.array([(pixel[0] - view["width"] / 2) / focal, (view["height"] / 2 - pixel[1]) / focal, 1.0])
    return np.array([r[0] * right[0] + r[2] * forward[0], r[0] * right[1] + r[2] * forward[1], r[1]])


def anchor(found: dict, camera: dict, view: dict, depth_m: float | None = None) -> dict | None:
    """One piece found in a staged photo, as a box standing on the floor in room metres.

    The two ends of its floor edge are where the camera's line of sight through those pixels meets the
    floor, which fixes where it stands. The box is then made just wide and tall enough to hold the piece
    as the picture shows it (legs and pots are narrower than what stands on them). Its depth cannot be
    seen from one photo and is assumed by kind.
    Returns None when the floor edge is at or above the horizon, where there is no floor to meet.
    """
    kind = KINDS.get(found["kind"], KINDS["other"])
    x0, top, x1, _ = found["box"]
    eye = np.array([camera["e"], camera["n"]])
    ends = [rv.floor_point(tuple(found[k]), camera, **view) for k in ("floor_left", "floor_right")]
    if any(e is None for e in ends):
        return None

    def depth_of(width: float) -> float:
        return depth_m if depth_m is not None else (kind["depth_m"] if kind["depth_m"] is not None else width)

    if kind["centred"]:
        # A pot or a lamp foot is too short an edge to give a direction, so only its middle is used. The
        # box faces the camera squarely through that spot, and there it is made to hold all four corners
        # of the piece's pixel box. Generated lamps and plants are drawn more upright than a wide photo
        # would show them, so a box fitted only at the floor would let the shade or the leaves stick out.
        middle = (np.array(ends[0]) + np.array(ends[1])) / 2
        foot_row = (found["floor_left"][1] + found["floor_right"][1]) / 2
        away = (middle - eye) / max(float(np.linalg.norm(middle - eye)), 1e-9)
        along = np.array([away[1], -away[0]])               # to the camera's right
        reach, tops = [0.0], []
        for pixel in ((x0, top), (x1, top), (x0, foot_row), (x1, foot_row)):
            line = _sight(pixel, camera, view)
            closing = float(line[:2] @ away)
            if closing <= 1e-6:
                return None                                 # this line of sight never reaches the piece
            spot = np.array([camera["e"], camera["n"], camera["z"]]) + line * (float((middle - eye) @ away) / closing)
            reach.append(float((spot[:2] - middle) @ along))
            tops.append(float(spot[2]))
        a, b, tall = middle + along * min(reach), middle + along * max(reach), max(max(tops[:2]), 0.0)
        depth = depth_of(float(np.linalg.norm(b - a)))
        footprint = [a - away * depth / 2, b - away * depth / 2, b + away * depth / 2, a + away * depth / 2]
    else:
        a0, b0 = np.array(ends[0]), np.array(ends[1])
        if float(np.linalg.norm(b0 - a0)) < 1e-3:
            return None
        along = (b0 - a0) / float(np.linalg.norm(b0 - a0))
        away = np.array([-along[1], along[0]])
        if away @ ((a0 + b0) / 2 - eye) < 0:
            away = -away                                    # the side of the edge facing away from the camera

        def box(more_left: float, more_right: float) -> list:
            a, b = a0 - along * more_left, b0 + along * more_right
            deep = depth_of(float(np.linalg.norm(b - a)))
            return [a, b, b + away * deep, a + away * deep]

        def reaches(more_left: float, more_right: float, tall: float, side: int) -> bool:
            span = _span(box(more_left, more_right), tall, camera, view)
            return span is None or (span[0] <= x0, span[1] >= x1, span[2] <= top)[side]

        # The box is grown from the floor edge, sideways and upwards, until its own picture reaches the
        # sides and top of the piece's pixel box. Width and height lean on each other a little (a taller
        # box also reaches further sideways in a wide photo), so they are settled in turn a few times.
        # The box is only ever grown past the floor edge that was found, never shrunk inside it.
        more_left = more_right = tall = 0.0
        for _ in range(4):
            tall = _grow(lambda h: reaches(more_left, more_right, h, 2), most=3.0)
            more_left = _grow(lambda m: reaches(m, more_right, tall, 0))
            more_right = _grow(lambda m: reaches(more_left, m, tall, 1))
        footprint = box(more_left, more_right)
        depth = depth_of(float(np.linalg.norm(footprint[1] - footprint[0])))
    width = float(np.linalg.norm(footprint[1] - footprint[0]))
    if width < 1e-3:
        return None
    footprint = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in footprint]
    return {
        "name": found["name"], "kind": found["kind"], "look": found.get("look", ""),
        "footprint": footprint, "width_m": round(width, 2), "depth_m": round(float(depth), 2), "height_m": round(float(tall), 2),
        "assumed": f"depth {depth:.2f} m: {kind['why']}" + ("; the box is centred on the foot found, facing the camera squarely" if kind["centred"] else "; the box runs back from the floor edge found, away from the camera"),
        "pixels": {"box": [round(v) for v in found["box"]], "floor_left": [round(v) for v in found["floor_left"]],
                   "floor_right": [round(v) for v in found["floor_right"]]},
    }


def _meet(p1, p2, p3, p4) -> np.ndarray | None:
    """Where the line through p1 and p2 meets the line through p3 and p4, on the floor."""
    d1, d2 = np.array(p2) - np.array(p1), np.array(p4) - np.array(p3)
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / cross
    return np.array(p1) + d1 * t


def anchor_rug(corners_px: list, camera: dict, view: dict) -> dict | None:
    """The rug as a flat four-sided patch on the floor: each corner pixel is carried to the floor on its own.

    When the picture's edge cuts a corner off, the rug comes back with two points on that edge instead of the
    corner. The corner is then put where the two cut sides meet, which is where it is if the sides are straight.
    """
    spots = [rv.floor_point(tuple(c), camera, **view) for c in corners_px]
    if len(spots) < 4 or any(s is None for s in spots):
        return None
    on_edge = [c[0] <= 2 or c[1] <= 2 or c[0] >= view["width"] - 3 or c[1] >= view["height"] - 3 for c in corners_px]
    rebuilt = []
    while len(spots) > 4:
        n = len(spots)
        cut = next((i for i in range(n) if on_edge[i] and on_edge[(i + 1) % n]), None)
        if cut is None:
            return None
        j = (cut + 1) % n
        corner = _meet(spots[cut - 1], spots[cut], spots[(j + 1) % n], spots[j])
        if corner is None:
            return None
        rebuilt.append([round(float(corner[0]), 3), round(float(corner[1]), 3)])
        spots = [(float(corner[0]), float(corner[1])) if i == cut else s for i, s in enumerate(spots) if i != j]
        on_edge = [False if i == cut else e for i, e in enumerate(on_edge) if i != j]
    sides = [round(float(math.dist(spots[i], spots[(i + 1) % 4])), 2) for i in range(4)]
    return {"name": "rug", "kind": "rug", "footprint": [[round(s[0], 3), round(s[1], 3)] for s in spots], "sides_m": sides,
            "corners_beyond_the_picture": rebuilt,
            "pixels": {"corners": [[round(c[0]), round(c[1])] for c in corners_px]}}


def square_up(rug: dict) -> dict:
    """The rug as the rectangle nearest to its four measured corners. A rug IS a rectangle, but corners read
    off a generated picture (some hidden under furniture, one beyond the picture's edge, and the picture not
    true to the camera in the first place) do not make one, and an image service shown a lopsided patch
    draws a proper rug somewhere else. The rectangle lies along the pair of opposite sides that agree best
    about their direction, and each of its sides is put at the average of the two corners on it. The
    measured corners are kept beside it, with how far each one was moved."""
    c = np.array(rug["footprint"], dtype=float)
    sides = [c[(i + 1) % 4] - c[i] for i in range(4)]
    unit = lambda v: v / max(float(np.linalg.norm(v)), 1e-9)
    slant = lambda p, q: abs(float(unit(p)[0] * unit(q)[1] - unit(p)[1] * unit(q)[0]))     # 0 when the two sides are parallel
    # Sides 0 and 2 run opposite ways round the rug, as do 1 and 3; the pair nearer to parallel sets the direction.
    pair = 0 if slant(sides[0], sides[2]) <= slant(sides[1], sides[3]) else 1
    u = unit(sides[pair] - sides[pair + 2])
    v = np.array([-u[1], u[0]])
    cu, cv = c @ u, c @ v
    if pair == 0:      # corners 0,1 lie on one long side and 2,3 on the other; ends are shared by 3,0 and by 1,2
        v_a, v_b, u_a, u_b = (cv[0] + cv[1]) / 2, (cv[2] + cv[3]) / 2, (cu[3] + cu[0]) / 2, (cu[1] + cu[2]) / 2
        square = [u * u_a + v * v_a, u * u_b + v * v_a, u * u_b + v * v_b, u * u_a + v * v_b]
    else:              # corners 1,2 lie on one side and 3,0 on the other; ends are shared by 0,1 and by 2,3
        v_a, v_b, u_a, u_b = (cv[1] + cv[2]) / 2, (cv[3] + cv[0]) / 2, (cu[0] + cu[1]) / 2, (cu[2] + cu[3]) / 2
        square = [u * u_a + v * v_b, u * u_a + v * v_a, u * u_b + v * v_a, u * u_b + v * v_b]
    square = [[round(float(q[0]), 3), round(float(q[1]), 3)] for q in square]
    moved = [round(float(math.dist(square[i], c[i])), 2) for i in range(4)]
    return {**rug, "footprint": square, "sides_m": [round(float(math.dist(square[i], square[(i + 1) % 4])), 2) for i in range(4)],
            "as_measured": rug["footprint"], "squared_up": {"assumed": "a rug is a rectangle", "each_corner_moved_m": moved}}


# ---- does it fit in the room -------------------------------------------------------------------------------

def room_outline(plan: dict, room: str):
    """The floor of one room as a shape, joined up from the measured wall lines."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    found = [r for r in plan["rooms"] if (r.get("name") or "").lower() == room.lower()]
    if not found:
        return None
    lines = unary_union([LineString(w) for r in found for w in r["walls"]])
    shapes = list(polygonize(lines))
    return unary_union(shapes) if shapes else None


def fits(footprint: list, outline, doors: list[dict], clear_m: float = 0.05) -> dict:
    """Whether a footprint lies inside the room's walls and stays off its doors. Reports, never moves anything.

    `outside_by_m` is how far the footprint's worst corner pokes through a wall (0 when inside).
    A door is crossed when the footprint comes within `clear_m` of the door's opening in the wall.
    """
    from shapely.geometry import LineString, Point, Polygon
    shape = Polygon(footprint)
    worst = max((outline.distance(Point(p)) for p in footprint), default=0.0) if outline is not None else None
    crossed, nearest = [], None
    for door in doors:
        gap = shape.distance(LineString(door["ends"]))
        nearest = gap if nearest is None else min(nearest, gap)
        if gap < clear_m:
            crossed.append(f"{door.get('width_m')} m door at {door.get('at')}")
    return {"inside_room": None if worst is None else bool(worst < 1e-6), "outside_by_m": None if worst is None else round(worst, 2),
            "share_outside": None if outline is None else round(float(shape.difference(outline).area / max(shape.area, 1e-9)), 3),
            "crosses_door": crossed, "nearest_door_m": None if nearest is None else round(nearest, 2)}


def build_layout(found: dict, camera: dict, view: dict, plan: dict | None, room: str, source: dict,
                 changed_mask: np.ndarray | None = None, least_changed: float = 0.2, square_rug: bool = False) -> dict:
    """Every piece found in the staged photo anchored to the floor and checked against the room. Nothing that
    fails a check is moved or dropped; the check is written beside the piece for whoever reads the layout.

    `changed_mask` is where the staged photo differs from the real one. Something found whose box barely
    changed was in the room already (a door, the fireplace): it is part of the building, not furniture, and
    is listed under `part_of_the_building` instead of being anchored.

    With `square_rug` the rug is the one thing that IS adjusted, into a rectangle (`square_up`), and it says
    so: the corners as measured stay in the layout beside the rectangle. Off by default: on the one scan it
    was tried on (14 November, with `hidden_edges`), the second standpoint came out no better placed.
    """
    outline = room_outline(plan, room) if plan else None
    doors = [o for o in (plan or {}).get("openings", []) if o["kind"] == "door" and (o.get("room") or "").lower() == room.lower()]
    pieces, missed, building = [], [], []
    for f in found["pieces"]:
        if changed_mask is not None:
            x0, y0, x1, y1 = (int(round(v)) for v in f["box"])
            share = float(changed_mask[max(y0, 0):y1, max(x0, 0):x1].mean()) if y1 > y0 and x1 > x0 else 0.0
            if share < least_changed:
                building.append({"name": f["name"], "changed_share_of_its_box": round(share, 3)})
                continue
        box = anchor(f, camera, view)
        if box is None:
            missed.append(f["name"])
            continue
        colour = COLOURS[len(pieces) % len(COLOURS)]
        pieces.append({**box, "colour": {"name": colour[0], "rgb": list(colour[1])}, "check": fits(box["footprint"], outline, doors)})
    rug = anchor_rug(found.get("rug") or [], camera, view)
    if rug:
        rug = square_up(rug) if square_rug else rug
        rug = {**rug, "colour": {"name": RUG_COLOUR[0], "rgb": list(RUG_COLOUR[1])}, "check": fits(rug["footprint"], outline, doors)}
    return {
        "generated": True, "kind": "layout read from an AI-generated illustration", "label": base.LABEL,
        "note": "Where the furniture of a generated picture would stand if it were in the room. The room's walls and doors are "
                "measured; the furniture is not real. Depths are assumed by kind of piece, as each piece says.",
        "units": "metres east and north of the scan's first placed viewpoint (as backend.openings.layout); heights above the floor",
        "room": room, "source": source, "standpoint": {k: round(v, 3) for k, v in camera.items()}, "view": view,
        "pieces": pieces, "rug": rug, "not_anchored": missed, "part_of_the_building": building, "created_at": base._now(),
    }


# ---- drawing boxes into a standpoint's photo ---------------------------------------------------------------

# A box's five faces that can be seen (never its underside), as corner numbers from `corners`.
_FACES = [(4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]


def _distance(footprint: list, camera: dict) -> float:
    middle = np.mean(np.array(footprint), axis=0)
    return float(math.hypot(middle[0] - camera["e"], middle[1] - camera["n"]))


def draw_order(pieces: list[dict], camera: dict) -> list[dict]:
    """Farthest first, so a nearer block is painted over a farther one, as it would hide it in the room."""
    return sorted(pieces, key=lambda p: -_distance(p["footprint"], camera))


def _faces(piece: dict, camera: dict, view: dict) -> list[tuple[list[tuple[float, float]], float]]:
    """The faces of a box that face the camera, as pixel outlines with a shade, farthest face first."""
    pts = corners(piece)
    px = rv.project(pts, camera, **view)
    eye = np.array([camera["e"], camera["n"], camera["z"]])
    middle = np.mean(np.array(pts), axis=0)
    out = []
    for n, face in enumerate(_FACES):
        if any(px[i] is None for i in face):
            continue                                        # partly behind the camera: left out rather than drawn wrongly
        p = np.array([pts[i] for i in face])
        centre = p.mean(axis=0)
        normal = np.cross(p[1] - p[0], p[2] - p[1])
        if normal @ (centre - middle) < 0:
            normal = -normal
        if normal @ (eye - centre) <= 0:
            continue                                        # this face looks away from the camera
        shade = SHADES[0] if n == 0 else SHADES[1 + n % 2]
        out.append(([px[i] for i in face], shade, float(np.linalg.norm(eye - centre))))
    out.sort(key=lambda f: -f[2])
    return [(outline, shade) for outline, shade, _ in out]


def draw_outlines(photo: np.ndarray, layout: dict, camera: dict, view: dict) -> Image.Image:
    """The boxes as wire frames over a photo, each in its own colour: the free check of the anchoring."""
    im = Image.fromarray(photo.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=18)
    if layout.get("rug"):
        px = rv.project([(e, n, 0.0) for e, n in layout["rug"]["footprint"]], camera, **view)
        if all(px):
            draw.line(px + [px[0]], fill=tuple(layout["rug"]["colour"]["rgb"]), width=3)
    for piece in draw_order(layout["pieces"], camera):
        px = rv.project(corners(piece), camera, **view)
        colour = tuple(piece["colour"]["rgb"])
        for a, b in _EDGES:
            if px[a] and px[b]:
                draw.line([px[a], px[b]], fill=colour, width=3)
        if px[4]:
            draw.text((px[4][0] + 4, px[4][1] - 22), piece["name"], fill=colour, font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    return im


def regions(layout: dict, camera: dict, view: dict, whole: bool = False) -> dict[str, np.ndarray]:
    """For each piece, the pixels of a standpoint's photo where its block shows, after nearer blocks have
    hidden what they hide. The rug's patch is what is left of it once every block is taken away.
    With `whole`, each block's full outline instead, also where a nearer block stands in front of it."""
    size = (view["width"], view["height"])
    out: dict[str, np.ndarray] = {}
    taken = np.zeros((view["height"], view["width"]), dtype=bool)
    for piece in reversed(draw_order(layout["pieces"], camera)):          # nearest first
        mask = Image.new("L", size, 0)
        for outline, _ in _faces(piece, camera, view):
            ImageDraw.Draw(mask).polygon(outline, fill=255)
        seen = (np.asarray(mask) > 0) & ~taken
        out[piece["name"]] = (np.asarray(mask) > 0) if whole else seen
        taken |= seen
    if layout.get("rug"):
        px = rv.project([(e, n, 0.0) for e, n in layout["rug"]["footprint"]], camera, **view)
        mask = Image.new("L", size, 0)
        if all(px):
            ImageDraw.Draw(mask).polygon(px, fill=255)
        out["rug"] = (np.asarray(mask) > 0) & ~taken
    return out


_EDGES = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)]


def draw_guide(photo: np.ndarray, layout: dict, camera: dict, view: dict, hidden_edges: bool = False) -> Image.Image:
    """The real photo of a standpoint with each box painted in as a solid block in its own flat colour, and
    the rug as a flat patch on the floor. This is what tells the image service where everything goes.

    With `hidden_edges`, the edges of every block are also drawn as thin dark lines of its own colour on top
    of everything, so that a block standing behind another still shows where it ends. Off by default: tried
    once (14 November, scan 9odpSsu2KYQ) together with stricter words, and the furniture came out no nearer
    to its blocks. The image service treats blocks as roughly where and roughly how big, not as a mould.
    """
    im = Image.fromarray(photo.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    if layout.get("rug"):
        px = rv.project([(e, n, 0.0) for e, n in layout["rug"]["footprint"]], camera, **view)
        if all(px):
            draw.polygon(px, fill=tuple(layout["rug"]["colour"]["rgb"]))
    for piece in draw_order(layout["pieces"], camera):
        for outline, shade in _faces(piece, camera, view):
            draw.polygon(outline, fill=tuple(int(c * shade) for c in piece["colour"]["rgb"]))
    if hidden_edges:
        for piece in draw_order(layout["pieces"], camera):
            px = rv.project(corners(piece), camera, **view)
            dark = tuple(int(c * 0.4) for c in piece["colour"]["rgb"])
            for i, j in _EDGES:
                if px[i] and px[j]:
                    draw.line([px[i], px[j]], fill=dark, width=2)
    return im


def aim(layout: dict, camera: dict) -> tuple[float, float]:
    """The turn and tilt that point a standpoint's camera at the middle of the furniture, a little above the floor."""
    spots = np.array([p for piece in layout["pieces"] for p in piece["footprint"]])
    middle = spots.mean(axis=0)
    de, dn = middle[0] - camera["e"], middle[1] - camera["n"]
    yaw = (math.degrees(math.atan2(de, dn)) - camera["h"]) % 360
    pitch = -math.degrees(math.atan2(camera["z"] - 0.4, math.hypot(de, dn)))
    return round(yaw, 1), round(max(-35.0, min(0.0, pitch)), 1)


def in_view(layout: dict, camera: dict, view: dict) -> dict:
    """How well a standpoint sees the layout: the share of all box corners that land inside its photo, and how
    close the nearest piece is (a camera standing in the furniture gets a useless picture)."""
    hit = total = 0
    for piece in layout["pieces"]:
        for p in rv.project(corners(piece), camera, **view):
            total += 1
            hit += bool(p and 0 <= p[0] < view["width"] and 0 <= p[1] < view["height"])
    from shapely.geometry import Point, Polygon
    here = Point(camera["e"], camera["n"])
    nearest = min((Polygon(piece["footprint"]).distance(here) for piece in layout["pieces"]), default=0.0)
    on_rug = bool(layout.get("rug") and Polygon(layout["rug"]["footprint"]).contains(here))
    return {"corners_in_view": round(hit / max(total, 1), 3), "nearest_piece_m": round(float(nearest), 2), "stands_on_rug": on_rug}


# ---- judging the result ------------------------------------------------------------------------------------

def overlap(changed_mask: np.ndarray, blocks: dict[str, np.ndarray], ring: int = 40) -> dict:
    """Is each piece where its block was? For each block: how much of it the staging repainted (`filled`),
    and how much of a `ring`-pixel band just outside it was repainted too (`around`). A piece in the right
    place fills its block and leaves the band mostly alone; a piece that moved does the reverse. A thin piece
    (a lamp) fills little of its box however well it is placed. `outside_all` is the share of all changed
    pixels that lie outside every block and the rug: furniture where none was asked for."""
    everything = np.zeros_like(changed_mask, dtype=bool)
    for m in blocks.values():
        everything |= m
    out: dict = {"pieces": {}}
    for name, m in blocks.items():
        area = int(m.sum())
        if not area:
            out["pieces"][name] = {"block_px": 0, "filled": None, "around": None}
            continue
        grown = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * ring + 1))) > 0
        band = grown & ~everything
        out["pieces"][name] = {"block_px": area, "filled": round(float(changed_mask[m].mean()), 3),
                               "around": round(float(changed_mask[band].mean()), 3) if band.any() else None}
    total = int(changed_mask.sum())
    out["changed_px"] = total
    out["outside_all"] = round(float((changed_mask & ~everything).sum() / total), 3) if total else 0.0
    return out


def box_agreement(seen: list[float] | None, block: np.ndarray) -> dict:
    """A box the vision model drew around a piece in the result, against the block's own pixel box: how much
    the two overlap (1 is identical, 0 is apart) and how far apart their middles are, in pixels."""
    ys, xs = np.nonzero(block)
    if seen is None or len(seen) != 4 or not len(xs):
        return {"overlap": None, "centre_off_px": None}
    mine = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    off = math.hypot((seen[0] + seen[2]) / 2 - (mine[0] + mine[2]) / 2, (seen[1] + seen[3]) / 2 - (mine[1] + mine[3]) / 2)
    return {"overlap": round(_box_overlap(list(seen), mine), 3), "centre_off_px": round(float(off)),
            "block_box": [int(v) for v in mine], "seen_box": [round(v) for v in seen]}


def _box_overlap(one: list[float], other: list[float]) -> float:
    """How much two pixel boxes [left, top, right, bottom] share: 1 when identical, 0 when apart."""
    iw, ih = max(0.0, min(one[2], other[2]) - max(one[0], other[0])), max(0.0, min(one[3], other[3]) - max(one[1], other[1]))
    union = (one[2] - one[0]) * (one[3] - one[1]) + (other[2] - other[0]) * (other[3] - other[1]) - iw * ih
    return float(iw * ih / union) if union > 0 else 0.0


def where_it_stands(found_again: dict, layout: dict, camera: dict, view: dict) -> dict:
    """Is the furniture in the second standpoint's result standing where the layout says, in metres?

    `found_again` is the same finder run on the result. Each thing it found is paired with the layout piece
    of the same kind whose block it overlaps most in the picture. The two ends of its floor edge are then
    carried to the floor from the second standpoint and set against the footprint measured from the first:
    `off_m` is how far the worse end lies outside that footprint (0 when the piece's feet are on it). An end
    that lies behind a nearer piece's block was not seen but guessed, so it is left out; a piece with both
    ends hidden has no number. The rug's corners are compared with the nearest corner of the layout's rug,
    which leans on the vision model reading rug corners well; it often does not, so look at the picture too.
    """
    from shapely.geometry import Point, Polygon
    whole = regions(layout, camera, view, whole=True)
    order = [p["name"] for p in draw_order(layout["pieces"], camera)]          # farthest first
    boxes = {}
    for name, mask in whole.items():
        ys, xs = np.nonzero(mask)
        boxes[name] = [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())] if len(xs) else None

    def hidden(pixel, name: str) -> str | None:
        x, y = int(round(pixel[0])), int(round(pixel[1]))
        if not (0 <= x < view["width"] and 0 <= y < view["height"]):
            return "outside the picture"
        for nearer in order[order.index(name) + 1:]:
            if whole[nearer][y, x]:
                return f"behind the {nearer}"
        return None

    pairs = [(_box_overlap(f["box"], boxes[p["name"]]), p["name"], i) for p in layout["pieces"] if boxes.get(p["name"])
             for i, f in enumerate(found_again["pieces"]) if f["kind"] == p["kind"] and len(f["box"]) == 4]
    out: dict = {"pieces": {}}
    used: set[int] = set()
    for share, name, i in sorted(pairs, reverse=True):
        if share < 0.1 or name in out["pieces"] or i in used:
            continue
        used.add(i)
        f = found_again["pieces"][i]
        shape = Polygon(next(p for p in layout["pieces"] if p["name"] == name)["footprint"])
        ends, left_out = [], []
        for k in ("floor_left", "floor_right"):
            why = hidden(f[k], name)
            spot = rv.floor_point(tuple(f[k]), camera, **view)
            if why or spot is None:
                left_out.append(why or "above the horizon")
            else:
                ends.append(spot)
        out["pieces"][name] = {"seen_as": f["name"], "box_overlap": round(share, 2),
                               "off_m": round(max(shape.distance(Point(e)) for e in ends), 2) if ends else None,
                               "ends_measured": len(ends), "ends_left_out": left_out,
                               "floor_edge": [[round(v, 2) for v in e] for e in ends]}
    for piece in layout["pieces"]:
        out["pieces"].setdefault(piece["name"], {"seen_as": None, "off_m": None, "ends_measured": 0})
    out["not_in_the_layout"] = [f["name"] for i, f in enumerate(found_again["pieces"]) if i not in used]
    if layout.get("rug"):
        spots = [rv.floor_point(tuple(c), camera, **view) for c in found_again.get("rug") or []]
        gaps = [round(min(math.dist(s, d) for d in layout["rug"]["footprint"]), 2) for s in spots if s]
        out["rug"] = {"seen_corner_to_nearest_layout_corner_m": gaps, "worst_m": max(gaps)} if gaps else None
    return out


def colour_leak(picture: np.ndarray, layout: dict, within: float = 45.0) -> dict[str, int]:
    """Pixels of a picture that are still close to one of the flat block colours (in any of the shades it was
    painted in). `within` is kept tight: the darkest shade of the yellow block is an olive that a plant's
    leaves come within 55 of, and leaves are not a leak."""
    out = {}
    paints = [(p["name"], p["colour"]["rgb"]) for p in layout["pieces"]] + ([("rug", layout["rug"]["colour"]["rgb"])] if layout.get("rug") else [])
    for name, rgb in paints:
        near = np.zeros(picture.shape[:2], dtype=bool)
        for shade in (SHADES if name != "rug" else SHADES[:1]):    # the rug is a flat patch: one shade only
            near |= np.linalg.norm(picture.astype(np.float32) - np.array(rgb, dtype=np.float32) * shade, axis=-1) < within
        out[name] = int(near.sum())
    return out


def structure_kept(real: np.ndarray, result: np.ndarray, blocks: dict[str, np.ndarray], margin: int = 60) -> dict:
    """How far the result is from the real photo away from the furniture (mean 0 to 255 over all channels).
    The room's walls, doors and windows live there, so this is the number that says the room survived."""
    everything = np.zeros(real.shape[:2], dtype=bool)
    for m in blocks.values():
        everything |= m
    near = np.asarray(Image.fromarray((everything * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * margin + 1))) > 0
    diff = np.abs(real.astype(np.float32) - result.astype(np.float32)).mean(axis=-1)
    top = diff[: diff.shape[0] * 2 // 5]
    return {"away_from_furniture": round(float(diff[~near].mean()), 2), "top_two_fifths": round(float(top.mean()), 2),
            "at_furniture": round(float(diff[near].mean()), 2)}


# ---- staging the second standpoint -------------------------------------------------------------------------

def camera_move(first: dict, first_view: dict, second: dict, second_view: dict) -> str:
    """In words, how the second standpoint's camera stands and is turned compared with the first one's.
    Worked out from the scan's own placement of the two standpoints, so the image service is not left to guess."""
    look = math.radians(first["h"] + first_view["yaw_deg"])
    step = np.array([second["e"] - first["e"], second["n"] - first["n"]])
    sideways = float(step @ np.array([math.cos(look), -math.sin(look)]))
    ahead = float(step @ np.array([math.sin(look), math.cos(look)]))
    turn = ((second["h"] + second_view["yaw_deg"]) - (first["h"] + first_view["yaw_deg"]) + 180) % 360 - 180
    return (f"The camera of the first image stands {abs(sideways):.1f} m to the {'right' if sideways > 0 else 'left'} of the camera of the "
            f"second image and {abs(ahead):.1f} m {'in front of' if ahead > 0 else 'behind'} it, turned {abs(turn):.0f} degrees to the "
            f"{'right' if turn > 0 else 'left'}, so it sees the same furniture from another side. ")


def instruction_for(layout: dict, extra: str = "", hidden_edges: bool = False) -> str:
    """The words sent with the guide picture and the first standpoint's staged photo."""
    if hidden_edges:
        extra = ("Thin dark lines show every edge of every block, also where another block stands in front of it: a "
                 "piece ends where the lines of its own colour end. The feet of each piece stand on the floor at the "
                 "bottom corners of its block, not in front of them or beside them, and no piece is larger than its "
                 "block. The rug has exactly the outline of its patch. Each piece is in the same state as in the second "
                 "image: a lamp that is lit there is lit here. ") + extra
    parts = [f"the {p['colour']['name']} block is the {p['name']} ({p['look']})" if p.get("look") else f"the {p['colour']['name']} block is the {p['name']}"
             for p in layout["pieces"]]
    if layout.get("rug"):
        parts.append(f"the flat {layout['rug']['colour']['name']} patch on the floor is the rug, lying flat under the furniture")
    return (
        "The first image is a photo of an empty room in which solid coloured blocks mark where furniture stands. The second "
        "image shows the same room from another spot, already furnished. Edit the first image: replace each block with the "
        "piece it marks, which is the same piece as in the second image: " + "; ".join(parts) + ". Each piece must have the "
        "same shape, colours and materials as in the second image, but drawn as it is seen from the camera of the first "
        "image, standing on the floor exactly where its block stands and just filling its block: as wide and as tall as "
        "the block and no larger. Every piece keeps the way it faces in the room: a piece that has its back to a wall in "
        "the second image has its back to that same wall here. The blocks are only markers: remove every trace of them and "
        "of their colours, and show the real wall, door and floor wherever a piece does not cover its block. Add nothing "
        "else: no other furniture, no pictures on the walls, no extra plants. Take only the furniture from the second "
        "image, never its walls, windows, door or floor. " + extra + base.KEEP)


def _jpeg(pixels) -> bytes:
    im = pixels if isinstance(pixels, Image.Image) else Image.fromarray(np.asarray(pixels).clip(0, 255).astype(np.uint8))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=92)
    return buf.getvalue()


def second_standpoint_generations() -> int:
    """Paid generations already spent on this method, from the shared ledger."""
    return sum(1 for e in base._ledger() if e.get("counted") and e.get("method") == "layout")


def stage_second(model_id: str, sweep_id: str, view: dict, layout: dict, camera: dict, first_staged: str | Path, *,
                 extra: str = "", attempt: str = "", hidden_edges: bool = False, service=None) -> dict:
    """Stage a second standpoint from a layout: paint the blocks into its real photo, ask the image service to
    turn them into the first standpoint's furniture, undo any frame nudge and lay the result back onto this
    standpoint's panorama. One paid call unless the same request was made before.

    Returns {"ok", "cached", "folder", "photo", "guide", "record", "reason"}.
    """
    width, height = view["width"], view["height"]
    cube = rv.load_cube(model_id, sweep_id)
    real = rv.wide_view(cube, view["yaw_deg"], view["pitch_deg"], view["hfov_deg"], width, height)
    guide = draw_guide(real, layout, camera, view, hidden_edges)
    guide_bytes, first_bytes = _jpeg(guide), Path(first_staged).read_bytes()
    instruction = instruction_for(layout, extra, hidden_edges)
    size = f"{width}x{height}"
    key = base._sha(json.dumps([model_id, sweep_id, view, instruction, base._sha(guide_bytes), base._sha(first_bytes),
                                base.MODEL, base.QUALITY, size, attempt]).encode())[:8]
    folder = base.OUT / model_id / f"{sweep_id}_view{round(view['yaw_deg'])}_layout_{key}"
    record_path = folder / "record.json"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        return {"ok": True, "cached": True, "folder": str(folder), "photo": record["output"]["photo"], "guide": record["guide"]["path"],
                "record": record, "reason": None}

    state, spent = base.budget(), second_standpoint_generations()
    if state["left"] <= 0 or spent >= SECOND_STANDPOINT_GENERATIONS_ALLOWED:
        return {"ok": False, "cached": False, "reason": {"kind": "budget", **state, "second_standpoint_used": spent,
                                                         "second_standpoint_limit": SECOND_STANDPOINT_GENERATIONS_ALLOWED}}
    what = {"model_id": model_id, "sweep_id": sweep_id, "view_yaw": view["yaw_deg"], "purpose": "listing", "method": "layout"}
    try:
        result = service([guide_bytes, first_bytes], instruction) if service else base.openai_edit([guide_bytes, first_bytes], instruction, size)
    except base.ServiceRefused as e:
        base._log({**what, "counted": False, "outcome": "refused", "status": e.status, "code": e.code})
        return {"ok": False, "cached": False, "reason": {"kind": "service_refused", "status": e.status, "code": e.code, "message": e.message}}
    except base.ServiceError as e:
        base._log({**what, "counted": True, "outcome": "unclear", "error": str(e)})
        return {"ok": False, "cached": False, "reason": {"kind": "service_error", "message": str(e)}}
    base._log({**what, "counted": True, "outcome": "generated", "file": folder.name})

    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(result["image"])) as im:
        redrawn = np.asarray(im.convert("RGB").resize((width, height), Image.LANCZOS), dtype=np.float32)
    settled, shift = rv.settle(real, redrawn)
    staged = rv.lay_back(cube, settled, view["yaw_deg"], view["pitch_deg"], view["hfov_deg"])

    Image.fromarray(real.clip(0, 255).astype(np.uint8)).save(folder / "real_view.jpg", quality=92)
    guide.save(folder / "guide.jpg", quality=92)
    Image.fromarray(redrawn.clip(0, 255).astype(np.uint8)).save(folder / "staged_view.jpg", quality=92)
    Image.fromarray(settled.clip(0, 255).astype(np.uint8)).save(folder / "staged_view_settled.jpg", quality=92)
    faces = {}
    for face, pixels in staged.items():
        path = folder / f"face_{face}.jpg"
        Image.fromarray(pixels.clip(0, 255).astype(np.uint8)).save(path, quality=92)
        faces[str(face)] = str(path)

    record = {
        "generated": True, "kind": "illustration", "label": base.LABEL, "purpose": "listing", "instruction": instruction,
        "method": "furniture of an earlier staged standpoint anchored to the floor as boxes, the boxes painted as coloured blocks "
                  "into this standpoint's real photo, the blocks replaced by the image service, the result laid back onto the panorama",
        "source": {"real": True, "type": "matterport panorama, six faces", "model_id": model_id, "sweep_id": sweep_id,
                   "view": {"yaw_deg_clockwise_from_face_1": view["yaw_deg"], "pitch_deg": view["pitch_deg"],
                            "horizontal_field_deg": view["hfov_deg"], "size": size}},
        "guide": {"generated": True, "path": str(folder / "guide.jpg"), "sha256": base._sha(guide_bytes),
                  "hidden_edges_drawn": hidden_edges,
                  "note": "The real photo with coloured blocks painted in. A working picture, not a photo of the building."},
        "reference": {"generated": True, "path": str(first_staged), "sha256": base._sha(first_bytes),
                      "note": "An earlier result of this module family, sent as a second image for its furniture only."},
        "layout": layout,
        "service": {k: v for k, v in result.items() if k != "image"},
        "created_at": base._now(),
        "frame_shift_undone_px": {"right": shift[0], "down": shift[1]},
        "seams_between_side_views": {"real": rv._seams(cube), "staged": rv._seams(staged),
                                     "note": "Mean 0 to 255 difference across each edge two neighbouring views share. Staged should match real."},
        "output": {"photo": str(folder / "staged_view.jpg"), "photo_settled": str(folder / "staged_view_settled.jpg"), "faces": faces},
    }
    record_path.write_text(json.dumps(record, indent=1))
    return {"ok": True, "cached": False, "folder": str(folder), "photo": record["output"]["photo"], "guide": str(folder / "guide.jpg"),
            "record": record, "reason": None}


def judge(folder: str | Path, layout: dict, camera: dict, view: dict) -> dict:
    """The measured half of the verdict on a staged second standpoint: per piece, did the furniture land where
    its block was; did block colour stay in the picture; did the room away from the furniture stay as it was.
    The other half is looking at the picture, which no number here replaces."""
    folder = Path(folder)
    load = lambda name: np.asarray(Image.open(folder / name).convert("RGB"), dtype=np.float32)
    real, result = load("real_view.jpg"), load("staged_view_settled.jpg")
    blocks = regions(layout, camera, view)
    leak_result, leak_real = colour_leak(result, layout), colour_leak(real, layout)
    return {"overlap": overlap(changed(real, result), blocks),
            "block_colour_px": {name: {"result": leak_result[name], "real_photo": leak_real[name]} for name in leak_result},
            "structure": structure_kept(real, result, blocks)}


def side_by_side(first_folder: str | Path, second_folder: str | Path, save_to: str | Path, note: str = "") -> Path:
    """One sheet for people: the two standpoints side by side, real photos above, staged below, labelled as generated."""
    first, second = Path(first_folder), Path(second_folder)
    w, h, band = 900, 600, 44
    sheet = Image.new("RGB", (w * 2, h * 2 + band * 3), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    cell = lambda p: Image.open(p).convert("RGB").resize((w, h), Image.LANCZOS)
    draw.text((12, 12), "Real scan, first standpoint", fill=(255, 255, 255), font=font)
    draw.text((w + 12, 12), "Real scan, second standpoint (same room, about 1.8 m away)", fill=(255, 255, 255), font=font)
    sheet.paste(cell(first / "real_view.jpg"), (0, band))
    sheet.paste(cell(second / "real_view.jpg"), (w, band))
    draw.text((12, band + h + 12), "AI-generated illustration: first standpoint, staged freely", fill=(255, 210, 120), font=font)
    draw.text((w + 12, band + h + 12), "AI-generated illustration: second standpoint, staged from the layout", fill=(255, 210, 120), font=font)
    sheet.paste(cell(first / "staged_view.jpg"), (0, band * 2 + h))
    sheet.paste(cell(second / "staged_view.jpg"), (w, band * 2 + h))
    draw.text((12, band * 2 + h * 2 + 12), f"{base.LABEL} {note}".strip(), fill=(255, 210, 120), font=font)
    save_to = Path(save_to)
    sheet.save(save_to, quality=90)
    return save_to
