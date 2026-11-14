"""Open problem: furnish an empty room. A small spike, not a solution.

`stage()` takes one real panorama face from a Matterport scan and asks an image editing service to redraw
it for one of two purposes: "storm_ready" (what the room looks like with the preparation carried out) or
"listing" (the empty unit staged again). The result is an illustration and is never evidence:

- every generated file is written beside a JSON record saying it is generated, from which real image,
  with what instruction, by which model and when; the PNG carries the same label in its metadata, and a
  second copy has the label printed under the picture for anything that shows it to a person;
- the source is always the real face fetched through `backend.matterport`; the only generated image that
  may be passed in is an earlier result of this module, as a furniture reference for a neighbouring view;
- `is_generated(path)` lets any other code refuse these files. Nothing that reports the building's
  condition may read them.

Paid calls are limited by a ledger on disk (MAX_GENERATIONS) and every result is cached, so the same
request is never paid for twice.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat
from PIL.PngImagePlugin import PngInfo

from .. import matterport
from ..config import CACHE_DIR

OUT = CACHE_DIR / "open" / "reimagine"
MAX_GENERATIONS = 12  # raised from 8 on 14 November for the two-standpoint attempt

# Checked against OpenAI's image API reference on 2026-11-14: JSON body, input images as data URLs.
ENDPOINT = "https://api.openai.com/v1/images/edits"
MODEL = "gpt-image-2"  # always reads input images at high fidelity, so there is no input_fidelity to set
QUALITY = "high"
SIZE = "1024x1024"  # panorama faces are square
SEND_SIDE = 1024

LABEL = "AI-generated illustration. Not a photo of the building and not evidence of its condition."

KEEP = ("Keep the camera position and the room exactly as they are: the same walls and wall colour, the same "
        "windows, blinds and doors, the same fireplace, the same ceiling and the same floor. Do not add, remove "
        "or move any part of the building. Photorealistic, matching the light already in the photo.")
INSTRUCTIONS = {
    "storm_ready": (
        "Show this same room prepared for a severe storm. Put away any loose items and move any furniture that "
        "is there back from the windows and glass doors. Do not add furniture, shutters, boards, tape or anything "
        "else. If there is nothing loose to put away, leave the picture unchanged. " + KEEP),
    "listing": (
        "Stage this same room for a rental listing with simple modern furniture: a sofa, a coffee table, a rug, "
        "a floor lamp and one or two plants. Do not block doors or the fireplace. " + KEEP),
}
REFERENCE_NOTE = (
    " The second image is the view immediately to the {side} of this one, taken from the same spot in the same "
    "room and already staged; its {its_edge} edge joins this view's {this_edge} edge. Use the same furniture as in "
    "the second image, with the same shapes, colours and materials, placed where those same pieces would really "
    "be seen from this view, and continue anything that crosses the shared edge. Take only the furniture from "
    "the second image, never its walls, windows or floor.")


class ServiceRefused(Exception):
    """The service answered and declined (a 4xx). Nothing was generated."""

    def __init__(self, status: int, code: str | None, message: str):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message = status, code, message


class ServiceError(Exception):
    """No clear answer (timeout, 5xx). The call may have been billed, so it counts against the budget."""


Service = Callable[[list[bytes], str], dict]


def openai_edit(images: list[bytes], instruction: str, size: str = SIZE) -> dict:
    """One paid call to OpenAI's image edit endpoint. `images` are JPEG bytes; the first is the one to edit."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ServiceRefused(401, "no_key", "OPENAI_API_KEY is not set")
    body = {
        "model": MODEL, "prompt": instruction, "n": 1, "size": size, "quality": QUALITY, "output_format": "png",
        "images": [{"image_url": "data:image/jpeg;base64," + base64.b64encode(b).decode()} for b in images],
    }
    try:
        r = httpx.post(ENDPOINT, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=420)
    except httpx.HTTPError as e:
        raise ServiceError(f"{type(e).__name__}") from None  # never echo the request, it carries the key
    if 400 <= r.status_code < 500:
        try:
            err = r.json().get("error") or {}
        except ValueError:
            err = {}
        raise ServiceRefused(r.status_code, err.get("code") or err.get("type"), (err.get("message") or r.text)[:500])
    if r.status_code != 200:
        raise ServiceError(f"HTTP {r.status_code}")
    data = r.json()
    b64 = ((data.get("data") or [{}])[0]).get("b64_json")
    if not b64:
        raise ServiceError("the service returned no image")
    return {"image": base64.b64decode(b64), "provider": "openai", "endpoint": ENDPOINT, "model": MODEL,
            "quality": data.get("quality") or QUALITY, "size": data.get("size") or size, "usage": data.get("usage")}


# ---- budget ledger -------------------------------------------------------------------------------------

def _ledger_path() -> Path:
    return OUT / "ledger.json"


def _ledger() -> list[dict]:
    p = _ledger_path()
    return json.loads(p.read_text()) if p.exists() else []


def _log(entry: dict) -> None:
    rows = _ledger() + [{"at": _now(), **entry}]
    OUT.mkdir(parents=True, exist_ok=True)
    _ledger_path().write_text(json.dumps(rows, indent=1))


def budget() -> dict:
    """Generations used so far. A refusal (4xx) made nothing and is not counted; an unclear failure is."""
    used = sum(1 for e in _ledger() if e.get("counted"))
    return {"used": used, "limit": MAX_GENERATIONS, "left": max(0, MAX_GENERATIONS - used)}


# ---- helpers -------------------------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _jpeg(path: Path) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB").resize((SEND_SIDE, SEND_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def _gray(path: Path, side: int = 256) -> Image.Image:
    with Image.open(path) as im:
        return im.convert("L").resize((side, side), Image.LANCZOS)


def pixel_change(real: Path, generated: Path) -> dict:
    """How far the generated picture is from the real one, 0 to 255 mean grey-level difference. A crude
    number: the top 40% of the frame is ceiling and upper wall, where staging has no reason to change anything."""
    a, b = _gray(real), _gray(generated)
    d = ImageChops.difference(a, b)
    top = d.crop((0, 0, d.width, int(d.height * 0.4)))
    return {"whole_frame": round(ImageStat.Stat(d).mean[0], 2), "top_40_percent": round(ImageStat.Stat(top).mean[0], 2)}


def seam_gap(left: Path, right: Path, band: int = 4, side: int = 512) -> float:
    """Mean difference (0 to 255) between the right edge of `left` and the left edge of `right`. Neighbouring
    cube faces of one real panorama join there, so real pairs score low; a staged pair scores low only if
    the two pictures agree about what crosses the edge."""
    def edge(path: Path, at_right: bool) -> Image.Image:
        with Image.open(path) as im:
            im = im.convert("RGB").resize((side, side), Image.LANCZOS)
        box = (side - band, 0, side, side) if at_right else (0, 0, band, side)
        return im.crop(box).resize((1, side), Image.BOX)
    d = ImageChops.difference(edge(left, True), edge(right, False))
    return round(sum(ImageStat.Stat(d).mean) / 3, 2)


def _is_right_neighbour(face: int, other: int) -> bool:
    """True if `other` is the side face one step clockwise (to the right) of `face`."""
    sides = list(matterport.SIDE_FACES)
    return sides[(sides.index(face) + 1) % 4] == other


def is_generated(path: str | Path) -> bool:
    """True for any file this module made. Code that reports the building's condition must refuse these."""
    p = Path(path).resolve()
    if OUT.resolve() in p.parents and "defurnished" not in p.parts:
        return True
    try:
        with Image.open(p) as im:
            return (getattr(im, "text", {}) or {}).get("generated") == "true"
    except (OSError, ValueError):
        return False


def _labelled_copy(png: Path, purpose: str) -> Path:
    """The same picture with the label printed underneath, for anything that shows it to a person."""
    with Image.open(png) as im:
        im = im.convert("RGB")
    band = max(44, im.height // 18)
    sheet = Image.new("RGB", (im.width, im.height + band), (20, 20, 20))
    sheet.paste(im, (0, 0))
    font = ImageFont.load_default(size=max(14, band // 3))
    ImageDraw.Draw(sheet).text((12, im.height + band // 4), f"{LABEL} ({purpose.replace('_', ' ')})", fill=(255, 255, 255), font=font)
    out = png.with_name(png.stem + "_labelled.jpg")
    sheet.save(out, "JPEG", quality=90)
    return out


def _paths(model_id: str, sweep_id: str, face: int, purpose: str, reference_face: int | None, key: str) -> tuple[Path, Path]:
    ref = f"_ref{reference_face}" if reference_face else ""
    stem = OUT / model_id / f"{sweep_id}_{face}_{purpose}{ref}_{key[:8]}"
    return stem.with_suffix(".png"), stem.with_suffix(".json")


def _fail(kind: str, **more) -> dict:
    return {"ok": False, "cached": False, "image": None, "labelled": None, "record_path": None, "record": None,
            "reason": {"kind": kind, **more}}


# ---- the one function the app calls --------------------------------------------------------------------

def stage(model_id: str, sweep_id: str, face: int, purpose: str, *, reference_face: int | None = None,
          service: Service | None = None) -> dict:
    """Redraw one real panorama face for `purpose` ("storm_ready" or "listing") and save it with its record.

    `reference_face` names a neighbouring side face of the same position that has already been staged for the
    same purpose; that earlier result is sent as a second image so the service can try to reuse its furniture.

    Returns {"ok", "cached", "image", "labelled", "record_path", "record", "reason"}. When the service
    declines, or the budget is spent, ok is False, `reason` says why, and no file is written.
    """
    if purpose not in INSTRUCTIONS:
        raise ValueError(f"purpose must be one of {sorted(INSTRUCTIONS)}")
    if face not in matterport.SIDE_FACES:
        raise ValueError("face must be one of the four side faces, 1 to 4")
    source = Path(matterport.face_image(model_id, sweep_id, face))
    if is_generated(source):
        raise ValueError("the source must be a real panorama face, not a generated picture")
    source_sha = _sha(source.read_bytes())
    instruction = INSTRUCTIONS[purpose]

    reference = None
    if reference_face is not None:
        if reference_face == face or reference_face not in matterport.SIDE_FACES:
            raise ValueError("reference_face must be a different side face, 1 to 4")
        earlier = stage_cached(model_id, sweep_id, reference_face, purpose)
        if not earlier:
            raise ValueError(f"face {reference_face} has not been staged for {purpose} yet")
        on_right = _is_right_neighbour(face, reference_face)
        on_left = _is_right_neighbour(reference_face, face)
        if not (on_right or on_left):
            raise ValueError("reference_face must be next to face")
        instruction += REFERENCE_NOTE.format(side="right" if on_right else "left",
                                             its_edge="left" if on_right else "right",
                                             this_edge="right" if on_right else "left")
        ref_path = Path(earlier["image"])
        reference = {"generated": True, "face": reference_face, "path": str(ref_path), "sha256": _sha(ref_path.read_bytes()),
                     "position": "right of this view" if on_right else "left of this view",
                     "note": "An earlier result of this module, sent as a second image for its furniture only."}

    key = _sha(json.dumps([model_id, sweep_id, face, purpose, instruction, source_sha, MODEL, QUALITY, SIZE,
                           reference and reference["sha256"]]).encode())
    png, rec = _paths(model_id, sweep_id, face, purpose, reference_face, key)
    if png.exists() and rec.exists():
        return {"ok": True, "cached": True, "image": str(png), "labelled": str(png.with_name(png.stem + "_labelled.jpg")),
                "record_path": str(rec), "record": json.loads(rec.read_text()), "reason": None}

    state = budget()
    if state["left"] <= 0:
        return _fail("budget", message=f"all {state['limit']} generations have been used", **state)

    images = [_jpeg(source)] + ([_jpeg(Path(reference["path"]))] if reference else [])
    what = {"model_id": model_id, "sweep_id": sweep_id, "face": face, "purpose": purpose, "reference_face": reference_face}
    try:
        result = (service or openai_edit)(images, instruction)
    except ServiceRefused as e:
        _log({**what, "counted": False, "outcome": "refused", "status": e.status, "code": e.code})
        return _fail("service_refused", status=e.status, code=e.code, message=e.message)
    except ServiceError as e:
        _log({**what, "counted": True, "outcome": "unclear", "error": str(e)})
        return _fail("service_error", message=str(e))
    _log({**what, "counted": True, "outcome": "generated", "file": png.name})

    created = _now()
    png.parent.mkdir(parents=True, exist_ok=True)
    meta = PngInfo()
    for k, v in (("generated", "true"), ("label", LABEL), ("purpose", purpose), ("created_at", created),
                 ("source", f"matterport {model_id} sweep {sweep_id} face {face}")):
        meta.add_text(k, v)
    with Image.open(io.BytesIO(result["image"])) as im:
        im.load()
        width, height = im.size
        im.save(png, "PNG", pnginfo=meta)
    labelled = _labelled_copy(png, purpose)

    record = {
        "generated": True,
        "kind": "illustration",
        "label": LABEL,
        "purpose": purpose,
        "instruction": instruction,
        "source": {"real": True, "type": "matterport panorama face", "model_id": model_id, "sweep_id": sweep_id, "face": face,
                   "path": str(source), "sha256": source_sha, "sent_as": f"{SEND_SIDE}x{SEND_SIDE} JPEG"},
        "reference": reference,
        "service": {k: v for k, v in result.items() if k != "image"},
        "created_at": created,
        "output": {"path": str(png), "labelled_copy": str(labelled), "sha256": _sha(png.read_bytes()), "width": width, "height": height},
        "pixel_change_from_real": pixel_change(source, png),
    }
    if reference:
        ref_source = Path(matterport.face_image(model_id, sweep_id, reference_face))
        ref_png = Path(reference["path"])
        left_real, right_real = (source, ref_source) if on_right else (ref_source, source)
        left_gen, right_gen = (png, ref_png) if on_right else (ref_png, png)
        record["seam_with_reference"] = {"real_pair": seam_gap(left_real, right_real), "staged_pair": seam_gap(left_gen, right_gen),
                                         "note": "Mean 0 to 255 difference across the edge the two views share; the real pair is the floor."}
    rec.write_text(json.dumps(record, indent=1))
    return {"ok": True, "cached": False, "image": str(png), "labelled": str(labelled), "record_path": str(rec), "record": record, "reason": None}


def stage_cached(model_id: str, sweep_id: str, face: int, purpose: str) -> dict | None:
    """The saved result for this view and purpose made without a reference, if there is one. Never calls the service."""
    folder = OUT / model_id
    for rec in sorted(folder.glob(f"{sweep_id}_{face}_{purpose}_*.json")) if folder.exists() else []:
        record = json.loads(rec.read_text())
        png = rec.with_suffix(".png")
        if record.get("reference") is None and png.exists():
            return {"ok": True, "cached": True, "image": str(png), "labelled": str(png.with_name(png.stem + "_labelled.jpg")),
                    "record_path": str(rec), "record": record, "reason": None}
    return None
