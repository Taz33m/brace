"""Furnish a room again, in three dimensions.

Three states of one room, from one standpoint:
  1. As it was: the scan's own panorama.
  2. Cleared: Matterport's defurnished view of the same position. A product of the scan, not a photograph.
  3. Furnished again: new furniture, each piece made by a text-to-3D service from a description, standing
     where a piece stood before. An illustration, and labelled as one wherever it is shown.

What stood where is read from the scan, not invented. The furnished photo and the cleared photo are cut
from the two panoramas with the same aim; the vision model finds each piece in the furnished one; only
pieces whose pixels the clearing actually changed count as furniture (a fireplace or a door is the
building). Each is placed on the floor with the same geometry the staging work uses. That list is also
the contents of the room: what the difference between the two views amounts to.

Text to 3D uses Meshy (https://docs.meshy.ai/en/api/text-to-3d): a preview task for the shape, a refine
task for the surface, then the GLB is downloaded and kept. It needs MESHY_API_KEY in .env, every model
is made once and reused, and the number of models is capped. Without a key nothing is generated and the
scene says which pieces still have no model.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from .. import matterport
from ..config import BUILDINGS_DIR, CACHE_DIR
from . import reimagine_layout as rl
from . import reimagine_view as rv

OUT = CACHE_DIR / "open" / "furnish3d"
MODELS = OUT / "models"
DEFURNISHED = "matterport.model.defurnished"
MESHY = "https://api.meshy.ai/openapi/v2/text-to-3d"
KEY_ENV = "MESHY_API_KEY"
MAX_MODELS = 10                 # paid generations this module may ever make; counted on disk
POLL_SECONDS, WAIT_SECONDS = 5, 420
LABEL = "Illustration. Generated furniture, placed where furniture stood in the scan. Not a photo of the building."


class Furnish3dError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- the cleared view --------------------------------------------------------------------------------

def defurnished_view(scan_id: str) -> str | None:
    """The id of Matterport's defurnished view of a scan, or None when the scan has none."""
    path = OUT / "views.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    if scan_id not in known:
        data = matterport.gql('{ model(id:"%s"){ views{ id type enabled } } }' % scan_id)
        view = next((v["id"] for v in (data["model"].get("views") or []) if v["type"] == DEFURNISHED and v.get("enabled")), None)
        known[scan_id] = view
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, indent=1))
    return known[scan_id]


def cleared_face(scan_id: str, sweep_id: str, face: int) -> Path:
    """One cube face of the cleared view at a scan position."""
    view = defurnished_view(scan_id)
    if not view:
        raise Furnish3dError("this scan has no defurnished view")
    matterport.download_faces(view, [sweep_id], [face])
    return matterport.face_image(view, sweep_id, face)


# ---- what stood where --------------------------------------------------------------------------------

def _folder(scan_id: str, sweep_id: str) -> Path:
    return OUT / scan_id / sweep_id


def read_room(property_id: int | str, scan_id: str, sweep_id: str, yaw_deg: float, room: str, *, pitch_deg: float = -12.0, hfov_deg: float = 105.0,
              client=None) -> dict:
    """Find the furniture in a scan position's view and place each piece on the floor. One look by the vision
    model, saved. Returns the layout: pieces with a name, a look, a size, and a footprint in metres."""
    folder = _folder(scan_id, sweep_id)
    saved = folder / "layout.json"
    if saved.exists():
        return json.loads(saved.read_text())
    bundle = json.loads((BUILDINGS_DIR / str(property_id) / "building.json").read_text())
    scan = next(s for s in bundle["scans"] if s["id"] == scan_id)
    camera = rv.cameras(scan).get(sweep_id)
    view_id = defurnished_view(scan_id)
    if camera is None or not view_id:
        raise Furnish3dError("this position is not placed, or the scan has no defurnished view")
    matterport.download_faces(scan_id, [sweep_id], list(range(6)))
    matterport.download_faces(view_id, [sweep_id], list(range(6)))
    view = rl.view_of(yaw_deg, pitch_deg, hfov_deg)
    aim = (view["yaw_deg"], view["pitch_deg"], view["hfov_deg"], view["width"], view["height"])
    furnished = rv.wide_view(rv.load_cube(scan_id, sweep_id), *aim)
    cleared = rv.wide_view(rv.load_cube(view_id, sweep_id), *aim)
    folder.mkdir(parents=True, exist_ok=True)
    Image.fromarray(furnished.clip(0, 255).astype(np.uint8)).save(folder / "as_it_was.jpg", quality=90)
    Image.fromarray(cleared.clip(0, 255).astype(np.uint8)).save(folder / "cleared.jpg", quality=90)
    found = rl.find_pieces(folder / "as_it_was.jpg", folder / "pieces_found.json", client)
    layout = rl.build_layout(found, camera, view, None, room, {"scan_id": scan_id, "sweep_id": sweep_id, "photo": str(folder / "as_it_was.jpg")},
                             changed_mask=rl.changed(furnished, cleared))
    layout.update({
        "generated": False, "kind": "where the furniture in the scan stood",
        "label": "Read from the scan's own photo and its defurnished copy. Positions and sizes are estimates.",
        "note": "Each piece was found in the scan's photo and counted as furniture only where the defurnished view differs. "
                "Its place on the floor comes from the photo's geometry; its depth is assumed by kind of piece, as each piece says.",
        "property_id": int(property_id), "scan_id": scan_id, "sweep_id": sweep_id, "created_at": _now(),
    })
    saved.write_text(json.dumps(layout, indent=1))
    return layout


def saved_layout(scan_id: str) -> dict | None:
    """The layout read for a scan, from whichever of its positions was read."""
    for path in sorted((OUT / scan_id).glob("*/layout.json")) if (OUT / scan_id).is_dir() else []:
        return json.loads(path.read_text())
    return None


# ---- text to 3D --------------------------------------------------------------------------------------

def prompt_for(piece: dict) -> str:
    """What to ask the text-to-3D service for: the kind of piece and how it looked, one object on its own."""
    look = (piece.get("look") or "").strip().rstrip(".")
    return f"{piece['name']}{', ' + look if look else ''}. A single piece of home furniture on its own, nothing else in the scene."[:780]


def model_key(prompt: str) -> str:
    return hashlib.sha1(prompt.encode()).hexdigest()[:14]


def model_path(prompt: str) -> Path:
    return MODELS / f"{model_key(prompt)}.glb"


def generations() -> int:
    path = OUT / "ledger.json"
    return len(json.loads(path.read_text())) if path.exists() else 0


def _count(entry: dict) -> None:
    path = OUT / "ledger.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows + [entry], indent=1))


def _wait(client: httpx.Client, task_id: str, headers: dict, sleep=time.sleep) -> dict:
    waited = 0
    while True:
        r = client.get(f"{MESHY}/{task_id}", headers=headers)
        if r.status_code != 200:
            raise Furnish3dError(f"the 3D service could not report on the task (HTTP {r.status_code})")
        task = r.json()
        if task.get("status") == "SUCCEEDED":
            return task
        if task.get("status") in ("FAILED", "CANCELED"):
            raise Furnish3dError(f"the 3D service did not finish the model: {task.get('status')}")
        if waited >= WAIT_SECONDS:
            raise Furnish3dError("the 3D service took too long")
        sleep(POLL_SECONDS)
        waited += POLL_SECONDS


def generate(prompt: str, *, refine: bool = True, client: httpx.Client | None = None, sleep=time.sleep) -> Path:
    """One textured model for a description, as a GLB file. Made once: asking again for the same words returns the file."""
    path = model_path(prompt)
    if path.exists():
        return path
    key = os.environ.get(KEY_ENV)
    if not key:
        raise Furnish3dError(f"no text-to-3D key is set ({KEY_ENV})")
    if generations() >= MAX_MODELS:
        raise Furnish3dError(f"the limit of {MAX_MODELS} generated models has been reached")
    headers = {"Authorization": f"Bearer {key}"}
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        # Real-world size with the origin at the bottom, so the piece stands on the floor without guessing its scale.
        made = client.post(MESHY, headers=headers, json={"mode": "preview", "prompt": prompt, "target_formats": ["glb"], "auto_size": True, "origin_at": "bottom"})
        if made.status_code not in (200, 202):
            raise Furnish3dError(f"the 3D service refused the request (HTTP {made.status_code})")
        _count({"at": _now(), "prompt": prompt, "task": made.json()["result"]})
        task = _wait(client, made.json()["result"], headers, sleep)
        if refine:
            painted = client.post(MESHY, headers=headers, json={"mode": "refine", "preview_task_id": task["id"], "target_formats": ["glb"], "auto_size": True, "origin_at": "bottom"})
            if painted.status_code in (200, 202):
                task = _wait(client, painted.json()["result"], headers, sleep)
        url = (task.get("model_urls") or {}).get("glb")
        if not url:
            raise Furnish3dError("the 3D service returned no GLB file")
        data = client.get(url)
        if data.status_code != 200:
            raise Furnish3dError(f"the model could not be downloaded (HTTP {data.status_code})")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.content)
        path.with_suffix(".json").write_text(json.dumps({"prompt": prompt, "service": "Meshy text to 3D", "task": task.get("id"), "made_at": _now(), "generated": True}, indent=1))
        return path
    finally:
        if own:
            client.close()


# ---- the room, ready to draw -------------------------------------------------------------------------

def _stand(piece: dict) -> dict:
    """Where a piece stands: the middle of its footprint, and which way its front faces (compass degrees)."""
    (ax, ay), (bx, by), (cx, cy), (dx, dy) = piece["footprint"]
    east, north = (ax + bx + cx + dx) / 4, (ay + by + cy + dy) / 4
    # The first edge is the front, nearest the camera; the piece faces away from the edge behind it.
    fx, fy = (ax + bx) / 2 - (cx + dx) / 2, (ay + by) / 2 - (cy + dy) / 2
    return {"east_m": round(east, 3), "north_m": round(north, 3), "faces_deg": round(math.degrees(math.atan2(fx, fy)) % 360, 1)}


def _rest_on_tables(pieces: list[dict]) -> None:
    """A table lamp stands on a table, not on the floor. Its place was worked out as if it stood on the floor,
    which puts it too far away, so it is moved onto the table it belongs to: the one sharing its "left" or
    "right", else the nearest. Its height becomes its own height above the table top."""
    tables = [p for p in pieces if "table" in p["name"].lower() and "lamp" not in p["name"].lower() and "coffee" not in p["name"].lower()]
    for p in pieces:
        if "lamp" not in p["name"].lower() or "floor" in p["name"].lower() or not tables:
            continue
        side = next((w for w in ("left", "right") if w in p["name"].lower()), None)
        table = next((t for t in tables if side and side in t["name"].lower()), None) or \
            min(tables, key=lambda t: math.hypot(t["east_m"] - p["east_m"], t["north_m"] - p["north_m"]))
        p.update({"east_m": table["east_m"], "north_m": table["north_m"], "stands_on_m": table["height_m"],
                  "height_m": round(max(0.3, p["height_m"] - table["height_m"]), 2), "stands_on": table["name"]})


def scene(scan_id: str) -> dict | None:
    """Everything a viewer needs to show the three states of the room. None when no layout has been read."""
    layout = saved_layout(scan_id)
    if layout is None:
        return None
    pieces = []
    for p in layout["pieces"]:
        prompt = prompt_for(p)
        have = model_path(prompt).exists()
        pieces.append({"name": p["name"], "kind": p.get("kind"), "look": p.get("look"), "width_m": p["width_m"], "depth_m": p["depth_m"], "height_m": p["height_m"],
                       "stands_on_m": 0.0, **_stand(p), "prompt": prompt, "model": model_key(prompt) if have else None})
    _rest_on_tables(pieces)
    return {
        "scan_id": scan_id, "sweep_id": layout["source"]["sweep_id"], "room": layout.get("room"), "standpoint": layout["standpoint"], "view": layout["view"],
        "pieces": pieces, "contents": len(pieces), "models_made": sum(1 for p in pieces if p["model"]),
        "can_generate": bool(os.environ.get(KEY_ENV)) and generations() < MAX_MODELS, "service": "Meshy text to 3D",
        "labels": {"as_it_was": "As it was. The scan.", "cleared": "Cleared. Matterport's defurnished view of the scan, not a photograph.", "furnished": LABEL},
        "read_note": layout.get("note"),
    }


def furnish(scan_id: str, client: httpx.Client | None = None, sleep=time.sleep) -> dict:
    """Make a model for every piece that has none. Stops at the first failure and says which pieces are still without one."""
    layout = saved_layout(scan_id)
    if layout is None:
        raise Furnish3dError("no layout has been read for this scan")
    made, failed = [], None
    for p in layout["pieces"]:
        prompt = prompt_for(p)
        if model_path(prompt).exists():
            continue
        try:
            generate(prompt, client=client, sleep=sleep)
            made.append(p["name"])
        except Furnish3dError as e:
            failed = str(e)
            break
    return {"made": made, "stopped": failed, "scene": scene(scan_id)}
