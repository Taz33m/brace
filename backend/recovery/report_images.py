"""Compose attached resident photographs with the registered sponsor image reader.

The platform supplies ``load_image(snapshot, evidence)`` and remains responsible
for checking media ownership, attachment and access using the frozen case. This
module never opens a media URL or path from evidence/report text. The platform's
server-created photo evidence uses ``source_id == media.media_id``.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
from typing import Callable

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
DISPLAY_MAX_PX = 1536

ImageReader = Callable[[str], list[dict]]
InputProvider = Callable[[dict], tuple[dict, ImageReader]]
ResidentImageLoader = Callable[[dict, dict], bytes]


class ReportImageError(ValueError):
    """A safe, caller-visible image validation failure without private paths."""


def _supported(row: dict) -> bool:
    media = row.get("media")
    identity = media.get("media_id") if isinstance(media, dict) else None
    return (row.get("kind") == "resident_photo" and isinstance(identity, str) and bool(identity)
            and row.get("source_id") == identity)


def _sanitize(raw: bytes) -> bytes:
    if not isinstance(raw, bytes):
        raise ReportImageError("The resident image loader must return image bytes.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ReportImageError("Resident photo exceeds the 25 MB image limit.")
    try:
        with Image.open(BytesIO(raw)) as probe:
            if probe.width * probe.height > MAX_IMAGE_PIXELS:
                raise ReportImageError("Resident photo exceeds the 40 megapixel image limit.")
            probe.verify()
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ReportImageError("Resident photo exceeds the 40 megapixel image limit.")
            decoded = ImageOps.exif_transpose(source).convert("RGB")
            decoded.thumbnail((DISPLAY_MAX_PX, DISPLAY_MAX_PX))
            # A fresh image has no inherited EXIF, ICC, comments or text chunks.
            image = Image.new("RGB", decoded.size)
            image.paste(decoded)
            output = BytesIO()
            image.save(output, "JPEG", quality=85)
            return output.getvalue()
    except ReportImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ReportImageError("Resident photo could not be decoded safely.") from None


def with_report_images(input_provider: InputProvider, load_image: ResidentImageLoader) -> InputProvider:
    """Wrap ``CaseInputRegistry.input_provider`` without replacing sponsor reads.

    ``load_image`` is called lazily, only with a resident_photo row from the exact
    frozen snapshot and a matching media/source identity. It must recheck that the
    media is an attached image authorized for that snapshot's case. Unknown IDs
    never reach either reader. Unsupported resident rows remain metadata-only.

    A private snapshot copy survives caller/provider/loader mutations. Successfully
    inspected resident image bytes are pinned for the remainder of this run.
    """
    if not callable(input_provider) or not callable(load_image):
        raise TypeError("Input provider and resident image loader must be callable.")

    def provide(snapshot: dict) -> tuple[dict, ImageReader]:
        frozen = deepcopy(snapshot)
        case = frozen.get("case") if isinstance(frozen, dict) else None
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
            raise ReportImageError("A frozen case snapshot is required for resident images.")
        rows = frozen.get("evidence")
        if not isinstance(rows, list):
            raise ReportImageError("The case must supply an evidence list.")
        by_id: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("evidence_id"), str) or not row["evidence_id"]:
                raise ReportImageError("Every evidence row needs a valid identifier.")
            if row["evidence_id"] in by_id:
                raise ReportImageError("Duplicate evidence identifiers are ambiguous.")
            by_id[row["evidence_id"]] = row
        # The base registry sees its own copy and cannot mutate the image boundary.
        original_inputs, sponsor_reader = input_provider(deepcopy(frozen))
        if not isinstance(original_inputs, dict) or not callable(sponsor_reader):
            raise ReportImageError("The source input provider returned invalid image inputs.")
        inputs = deepcopy(original_inputs)
        availability = inputs.get("image_availability", {})
        if not isinstance(availability, dict):
            raise ReportImageError("Source image availability must be a mapping.")
        inputs["image_availability"] = availability
        for identity, row in by_id.items():
            if row.get("kind") == "resident_photo":
                availability[identity] = "cached" if _supported(row) else "metadata_only"
        pinned: dict[str, bytes] = {}

        def inspect(evidence_id: str) -> list[dict]:
            if not isinstance(evidence_id, str) or evidence_id not in by_id:
                raise ReportImageError("No authorized image is available for this evidence.")
            row = by_id[evidence_id]
            if row.get("kind") != "resident_photo":
                return sponsor_reader(evidence_id)
            if not _supported(row):
                raise ReportImageError("Resident photo has no matching attached media identity.")
            if evidence_id not in pinned:
                try:
                    raw = load_image(deepcopy(frozen), deepcopy(row))
                except Exception:
                    raise ReportImageError("Resident photo is unavailable for this case.") from None
                pinned[evidence_id] = _sanitize(raw)
            return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                     "data": base64.b64encode(pinned[evidence_id]).decode("ascii")}}]

        return inputs, inspect

    return provide
