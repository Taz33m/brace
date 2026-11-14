"""Vision helpers: image blocks for the model, and a cheap first pass over a scan's panoramas."""
from __future__ import annotations

import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor

import anthropic
from PIL import Image

from . import matterport
from .building import Site
from .config import VISION_MODEL

MAX_SWEEPS = 10
PROMPT = (
    "These four photos are the four horizontal views from one camera position inside a commercial or apartment "
    "building, in clockwise order. An owner is preparing the building for a severe storm or wildfire. Report only "
    "what is visible: how much of the surrounding wall is glass; whether the space is at ground level (you can see "
    "the ground, parking or landscaping at the same height through a window or door) or on an upper floor; anything "
    "valuable or hazardous sitting on or near the floor (electrical panels, servers or IT racks, appliances, gym "
    "machines, stock on low shelves, furniture, files); and exterior doors or roll-up doors."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "glass": {"type": "string", "enum": ["none", "some windows", "large windows", "mostly glass"]},
        "level": {"type": "string", "enum": ["ground", "upper", "unknown"]},
        "floor_level_items": {"type": "array", "items": {"type": "string"}, "description": "Up to five short noun phrases."},
        "exterior_doors": {"type": "string", "enum": ["none seen", "glass doors", "solid doors", "roll-up doors"]},
        "note": {"type": "string", "description": "One sentence on what this space is and what stands out for storm or fire preparation."},
    },
    "required": ["glass", "level", "floor_level_items", "exterior_doors", "note"],
    "additionalProperties": False,
}


def image_block(source, max_side: int = 1024, quality: int = 82) -> dict:
    """A base64 JPEG content block from a path or PIL image, downsized to keep a look cheap."""
    im = source if isinstance(source, Image.Image) else Image.open(source)
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def strip(model_id: str, sweep_id: str, side: int = 512) -> Image.Image:
    """The four side faces of one scan position, left to right in clockwise order."""
    sheet = Image.new("RGB", (4 * side, side))
    for i, face in enumerate(matterport.SIDE_FACES):
        with Image.open(matterport.face_image(model_id, sweep_id, face)) as im:
            sheet.paste(im.convert("RGB").resize((side, side), Image.LANCZOS), (i * side, 0))
    return sheet


def _one(client: anthropic.Anthropic, model_id: str, sweep_id: str) -> dict:
    resp = client.messages.create(
        model=VISION_MODEL, max_tokens=1024,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [image_block(strip(model_id, sweep_id), max_side=2048), {"type": "text", "text": PROMPT}]}],
    )
    if resp.stop_reason == "refusal":
        raise ValueError("declined")
    return {"sweep_id": sweep_id, **json.loads(next(b.text for b in resp.content if b.type == "text"))}


def survey(site: Site, scan_id: str, client: anthropic.Anthropic, refresh: bool = False) -> list[dict]:
    """First-pass description of up to MAX_SWEEPS positions in one scan, spread evenly. Cached per scan."""
    path = site.dir / "surveys" / f"{scan_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    sweeps = [s["id"] for s in site.scans[scan_id]["sweeps"]]
    step = max(1, len(sweeps) // MAX_SWEEPS)
    picked = sweeps[::step][:MAX_SWEEPS]
    matterport.download_faces(scan_id, picked, list(matterport.SIDE_FACES))

    def safe(sid: str) -> dict | None:
        try:
            return _one(client, scan_id, sid)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise
        except (anthropic.APIError, json.JSONDecodeError, matterport.MatterportError, ValueError, StopIteration):
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [r for r in pool.map(safe, picked) if r]
    if len(results) >= max(1, len(picked) // 2):  # do not cache a pass that mostly failed
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results))
    return results
