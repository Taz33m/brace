"""Furnish a room so that every direction from one standpoint agrees.

Staging the four side views of a panorama one at a time gives four different rooms. Here the panorama
is first turned into ONE ordinary wide photo aimed at the part of the room to be furnished, that single
photo is staged, and the result is laid back onto the panorama. Every view from that standpoint then
shows the same furniture in the same place, because all of them are cut from the same picture.

What this does not do: agree between two standpoints. That needs the furniture to exist in 3D.

The output is an illustration and never evidence; it follows the labelling rules in `reimagine.py`.
"""
from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .. import matterport
from . import reimagine as base

FACE_SIDE = 1024
VIEW_SIZE = "1536x1024"
# How much of the staged photo's edge is blended into the real panorama, so there is no visible join.
FEATHER = 0.09

INSTRUCTIONS = {
    "listing": (
        "Stage this same room for a rental listing with simple modern furniture: a sofa, a coffee table, a rug, "
        "a floor lamp and one or two plants. Keep every piece of furniture completely inside the picture, well "
        "away from all four edges, and do not block doors or the fireplace. Do not hang anything on the walls. " + base.KEEP),
    "storm_ready": base.INSTRUCTIONS["storm_ready"],
}


# ---- the panorama as directions ---------------------------------------------------------------------------
# Directions are (right, up, forward) as seen when facing along cube face 1. Faces 2, 3 and 4 each turn a
# further quarter clockwise; face 0 is up, with its bottom edge on the top of face 1; face 5 is down, with
# its top edge on the bottom of face 1. Each entry is (forward, right, up) for that face.
_AXES = {
    1: ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    2: ((1, 0, 0), (0, 0, -1), (0, 1, 0)),
    3: ((0, 0, -1), (-1, 0, 0), (0, 1, 0)),
    4: ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    0: ((0, 1, 0), (1, 0, 0), (0, 0, -1)),
    5: ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
}


def load_cube(model_id: str, sweep_id: str, side: int = FACE_SIDE) -> dict[int, np.ndarray]:
    """The six real faces of one scan position's panorama."""
    cube = {}
    for face in range(6):
        with Image.open(matterport.face_image(model_id, sweep_id, face)) as im:
            cube[face] = np.asarray(im.convert("RGB").resize((side, side), Image.LANCZOS), dtype=np.float32)
    return cube


def _turn(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    """Rotation taking a camera's own (right, up, forward) to the panorama's, for a camera turned `yaw`
    clockwise from face 1 and tilted `pitch` up."""
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    tilt = np.array([[1, 0, 0], [0, math.cos(p), math.sin(p)], [0, -math.sin(p), math.cos(p)]])
    spin = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    return spin @ tilt


def _sample(cube: dict[int, np.ndarray], dirs: np.ndarray) -> np.ndarray:
    """The colour the panorama shows in each direction (nearest pixel of the face that direction lands on)."""
    side = next(iter(cube.values())).shape[0]
    out = np.zeros(dirs.shape[:-1] + (3,), dtype=np.float32)
    best = np.full(dirs.shape[:-1], -np.inf, dtype=np.float32)
    for face, (fwd, right, up) in _AXES.items():
        depth = dirs @ np.array(fwd, dtype=np.float32)
        take = depth > best
        best = np.where(take, depth, best)
        safe = np.where(depth > 1e-6, depth, 1.0)
        u = (dirs @ np.array(right, dtype=np.float32)) / safe
        v = (dirs @ np.array(up, dtype=np.float32)) / safe
        px = np.clip(((u + 1) / 2 * side).astype(np.int32), 0, side - 1)
        py = np.clip(((1 - v) / 2 * side).astype(np.int32), 0, side - 1)
        out[take] = cube[face][py[take], px[take]]
    return out


def wide_view(cube: dict[int, np.ndarray], yaw_deg: float, pitch_deg: float, hfov_deg: float, width: int, height: int) -> np.ndarray:
    """One ordinary photo cut from the panorama: what a camera with this aim and field of view would see."""
    focal = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    xs, ys = np.meshgrid(np.arange(width) + 0.5 - width / 2, height / 2 - (np.arange(height) + 0.5))
    rays = np.stack([xs / focal, ys / focal, np.ones_like(xs)], axis=-1).astype(np.float32)
    return _sample(cube, rays @ _turn(yaw_deg, pitch_deg).T.astype(np.float32))


def lay_back(cube: dict[int, np.ndarray], photo: np.ndarray, yaw_deg: float, pitch_deg: float, hfov_deg: float) -> dict[int, np.ndarray]:
    """Put a (staged) wide photo back onto the panorama. Inside the photo the panorama takes its pixels,
    fading to the real panorama over the photo's outer edge; outside it the panorama is left as it was."""
    height, width = photo.shape[:2]
    focal = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    back = _turn(yaw_deg, pitch_deg).T.astype(np.float32)      # panorama direction -> the camera's own
    side = next(iter(cube.values())).shape[0]
    grid = (np.arange(side) + 0.5) / side * 2 - 1
    us, vs = np.meshgrid(grid, -grid)
    staged = {}
    for face, (fwd, right, up) in _AXES.items():
        dirs = (np.array(fwd, dtype=np.float32) + us[..., None] * np.array(right, dtype=np.float32)
                + vs[..., None] * np.array(up, dtype=np.float32))
        cam = dirs @ back.T
        ahead = cam[..., 2] > 1e-3
        z = np.where(ahead, cam[..., 2], 1.0)
        x = cam[..., 0] / z * focal + width / 2
        y = height / 2 - cam[..., 1] / z * focal
        inside = ahead & (x >= 0) & (x < width) & (y >= 0) & (y < height)
        # 1 well inside the photo, 0 at its edge.
        edge = np.minimum(np.minimum(x, width - x) / (width * FEATHER), np.minimum(y, height - y) / (height * FEATHER))
        weight = np.where(inside, np.clip(edge, 0, 1), 0.0).astype(np.float32)
        weight = weight * weight * (3 - 2 * weight)
        xi, yi = np.clip(x.astype(np.int32), 0, width - 1), np.clip(y.astype(np.int32), 0, height - 1)
        staged[face] = cube[face] * (1 - weight[..., None]) + photo[yi, xi] * weight[..., None]
    return staged


def settle(real: np.ndarray, redrawn: np.ndarray, reach: int = 48) -> tuple[np.ndarray, tuple[int, int]]:
    """Image services redraw the whole frame and tend to nudge it a few pixels. Find the shift that best
    lines the top of the frame (ceiling and upper walls, which staging leaves alone) back up, and undo it."""
    step = 4
    grey = lambda a: a[: a.shape[0] * 2 // 5 : step, ::step].mean(axis=-1)
    a, b = grey(real), grey(redrawn)
    r = reach // step
    best, shift = None, (0, 0)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            ya, yb = max(0, dy), max(0, -dy)
            xa, xb = max(0, dx), max(0, -dx)
            h, w = a.shape[0] - abs(dy), a.shape[1] - abs(dx)
            score = float(np.abs(a[ya:ya + h, xa:xa + w] - b[yb:yb + h, xb:xb + w]).mean())
            if best is None or score < best:
                best, shift = score, (dx * step, dy * step)
    dx, dy = shift
    return np.roll(np.roll(redrawn, dy, axis=0), dx, axis=1), shift


def _strip(faces: dict[int, np.ndarray], side: int = 512) -> Image.Image:
    """The four side views in order, left to right, as one picture."""
    sheet = Image.new("RGB", (side * 4, side))
    for i, face in enumerate(matterport.SIDE_FACES):
        sheet.paste(Image.fromarray(faces[face].clip(0, 255).astype(np.uint8)).resize((side, side), Image.LANCZOS), (i * side, 0))
    return sheet


def _seams(faces: dict[int, np.ndarray], band: int = 4) -> list[float]:
    """Mean difference (0 to 255) across each of the four edges where neighbouring side views meet."""
    order = list(matterport.SIDE_FACES)
    return [round(float(np.abs(faces[a][:, -band:].mean(axis=1) - faces[order[(i + 1) % 4]][:, :band].mean(axis=1)).mean()), 2)
            for i, a in enumerate(order)]


def stage_view(model_id: str, sweep_id: str, yaw_deg: float, purpose: str, *, pitch_deg: float = -8.0, hfov_deg: float = 100.0,
               service=None) -> dict:
    """Stage one wide photo cut from a real panorama and lay it back, so all views from that spot agree.

    Returns {"ok", "cached", "photo", "faces" (face number -> path), "sheet", "record", "reason"}.
    """
    if purpose not in INSTRUCTIONS:
        raise ValueError(f"purpose must be one of {sorted(INSTRUCTIONS)}")
    width, height = (int(n) for n in VIEW_SIZE.split("x"))
    cube = load_cube(model_id, sweep_id)
    real = wide_view(cube, yaw_deg, pitch_deg, hfov_deg, width, height)
    buf = io.BytesIO()
    Image.fromarray(real.clip(0, 255).astype(np.uint8)).save(buf, "JPEG", quality=92)
    sent = buf.getvalue()
    instruction = INSTRUCTIONS[purpose]
    key = base._sha(json.dumps([model_id, sweep_id, yaw_deg, pitch_deg, hfov_deg, purpose, instruction, base._sha(sent),
                                base.MODEL, base.QUALITY, VIEW_SIZE]).encode())[:8]
    folder = base.OUT / model_id / f"{sweep_id}_view{round(yaw_deg)}_{purpose}_{key}"
    record_path = folder / "record.json"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        return {"ok": True, "cached": True, "photo": record["output"]["photo"], "faces": record["output"]["faces"],
                "sheet": record["output"]["sheet"], "record": record, "reason": None}

    state = base.budget()
    if state["left"] <= 0:
        return {"ok": False, "cached": False, "reason": {"kind": "budget", **state}}
    what = {"model_id": model_id, "sweep_id": sweep_id, "view_yaw": yaw_deg, "purpose": purpose}
    try:
        result = service(([sent]), instruction) if service else base.openai_edit([sent], instruction, VIEW_SIZE)
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
    settled, shift = settle(real, redrawn)
    staged = lay_back(cube, settled, yaw_deg, pitch_deg, hfov_deg)

    Image.fromarray(real.clip(0, 255).astype(np.uint8)).save(folder / "real_view.jpg", quality=92)
    Image.fromarray(redrawn.clip(0, 255).astype(np.uint8)).save(folder / "staged_view.jpg", quality=92)
    faces = {}
    for face, pixels in staged.items():
        path = folder / f"face_{face}.jpg"
        Image.fromarray(pixels.clip(0, 255).astype(np.uint8)).save(path, quality=92)
        faces[str(face)] = str(path)

    # A sheet for people: the real all-round view above, the staged one below, labelled as generated.
    top, bottom = _strip(cube), _strip(staged)
    band = 40
    sheet = Image.new("RGB", (top.width, top.height * 2 + band * 2), (20, 20, 20))
    font = ImageFont.load_default(size=18)
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), "Real scan: the four side views from one standpoint, left to right", fill=(255, 255, 255), font=font)
    sheet.paste(top, (0, band))
    draw.text((12, band + top.height + 10), f"{base.LABEL} Staged as one wide photo and laid back onto the panorama.", fill=(255, 210, 120), font=font)
    sheet.paste(bottom, (0, band * 2 + top.height))
    sheet_path = folder / "all_round_sheet.jpg"
    sheet.save(sheet_path, quality=90)

    record = {
        "generated": True, "kind": "illustration", "label": base.LABEL, "purpose": purpose, "instruction": instruction,
        "method": "one wide photo cut from the real panorama, staged once, then laid back onto the panorama",
        "source": {"real": True, "type": "matterport panorama, six faces", "model_id": model_id, "sweep_id": sweep_id,
                   "view": {"yaw_deg_clockwise_from_face_1": yaw_deg, "pitch_deg": pitch_deg, "horizontal_field_deg": hfov_deg, "size": VIEW_SIZE}},
        "service": {k: v for k, v in result.items() if k != "image"},
        "created_at": base._now(),
        "frame_shift_undone_px": {"right": shift[0], "down": shift[1]},
        "seams_between_side_views": {"real": _seams(cube), "staged": _seams(staged),
                                     "note": "Mean 0 to 255 difference across each edge two neighbouring views share. Staged should match real."},
        "output": {"photo": str(folder / "staged_view.jpg"), "faces": faces, "sheet": str(sheet_path)},
    }
    record_path.write_text(json.dumps(record, indent=1))
    return {"ok": True, "cached": False, "photo": record["output"]["photo"], "faces": faces, "sheet": str(sheet_path), "record": record, "reason": None}


# ---- the room's real geometry, seen from a standpoint ------------------------------------------------------
# Checked on 14 November against scan 9odpSsu2KYQ: the entry door, a window and the wall-to-floor lines taken
# from the scan's wall measurements, projected with `project`, land on the real door, window and skirting in
# the photo cut by `wide_view` (see previews/geometry_overlay_A.jpg). So a point given in metres in the room
# can be drawn where it really is in any standpoint's photo, and the reverse for points on the floor.

def cameras(scan: dict) -> dict[str, dict]:
    """Where each scan position stands, in the same metres east and north that `backend.openings.layout`
    uses for the room's walls: {"e", "n", "z" (lens height above the floor), "h" (compass heading of face 1)}."""
    from .. import openings
    placed = [w for w in scan.get("sweeps") or [] if w.get("lon") is not None and w.get("lat") is not None]
    if not placed:
        return {}
    lon0, lat0 = placed[0]["lon"], placed[0]["lat"]
    kx = openings.M_PER_DEG * math.cos(math.radians(lat0))
    return {w["id"]: {"e": (w["lon"] - lon0) * kx, "n": (w["lat"] - lat0) * openings.M_PER_DEG,
                      "z": float((w.get("model_position") or {}).get("z") or 1.37), "h": float(w.get("heading") or 0.0)}
            for w in placed}


def _room_axes(camera: dict) -> tuple[np.ndarray, np.ndarray]:
    h = math.radians(camera["h"])
    return np.array([math.sin(h), math.cos(h)]), np.array([math.cos(h), -math.sin(h)])   # face 1's forward and right, as (east, north)


def project(points: list[tuple[float, float, float]], camera: dict, yaw_deg: float, pitch_deg: float, hfov_deg: float,
            width: int, height: int) -> list[tuple[float, float] | None]:
    """Room points (east, north, height above the floor) to pixels in that standpoint's wide photo. None when behind it."""
    forward, right = _room_axes(camera)
    back = _turn(yaw_deg, pitch_deg).T
    focal = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    out: list[tuple[float, float] | None] = []
    for e, n, z in points:
        d = np.array([e - camera["e"], n - camera["n"]])
        c = back @ np.array([d @ right, z - camera["z"], d @ forward])
        out.append(None if c[2] <= 0.05 else (width / 2 + c[0] / c[2] * focal, height / 2 - c[1] / c[2] * focal))
    return out


def floor_point(pixel: tuple[float, float], camera: dict, yaw_deg: float, pitch_deg: float, hfov_deg: float,
                width: int, height: int) -> tuple[float, float] | None:
    """The spot on the floor (east, north) that a pixel of a standpoint's wide photo looks at. None for a pixel at or above the horizon."""
    forward, right = _room_axes(camera)
    focal = (width / 2) / math.tan(math.radians(hfov_deg) / 2)
    ray = _turn(yaw_deg, pitch_deg) @ np.array([(pixel[0] - width / 2) / focal, (height / 2 - pixel[1]) / focal, 1.0])
    if ray[1] >= -1e-6:
        return None
    t = camera["z"] / -ray[1]
    spot = np.array([camera["e"], camera["n"]]) + t * (ray[0] * right + ray[2] * forward)
    return float(spot[0]), float(spot[1])
