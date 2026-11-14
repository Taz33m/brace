"""Resident image uploads: bounded body reading, stdlib multipart parsing, decode check.

python-multipart is not a project dependency yet, so the single `file` part is parsed
with the stdlib email parser. Only JPEG, PNG and WEBP that Pillow actually decodes are
accepted. The display copy is re-encoded as JPEG with no EXIF (no GPS, camera, or time).
"""
from __future__ import annotations

from email.parser import BytesParser
from email.policy import HTTP
from io import BytesIO

from PIL import Image, ImageOps

from .errors import PlatformError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # stated limit for one photo; 413 above it
MULTIPART_OVERHEAD = 16 * 1024
MAX_PIXELS = 40_000_000
DISPLAY_MAX_PX = 2048
ACCEPTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def too_large() -> PlatformError:
    return PlatformError(413, "upload_too_large",
                         f"Photos must be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller.")


def unsupported() -> PlatformError:
    return PlatformError(422, "unsupported_media", "Send a JPEG, PNG, or WEBP photo.")


async def read_limited(request) -> bytes:
    """Read the request body, stopping as soon as it exceeds the limit."""
    limit = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise too_large()
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def extract_file_part(content_type: str, body: bytes) -> bytes:
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type:
        raise PlatformError(422, "invalid_request", "Upload the photo as multipart form data in a 'file' field.")
    message = BytesParser(policy=HTTP).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body)
    for part in message.iter_parts() if message.is_multipart() else ():
        if part.get_param("name", header="content-disposition") == "file":
            data = part.get_payload(decode=True) or b""
            if len(data) > MAX_UPLOAD_BYTES:
                raise too_large()
            if not data:
                raise unsupported()
            return data
    raise PlatformError(422, "invalid_request", "Upload the photo as multipart form data in a 'file' field.")


def decode_image(data: bytes) -> tuple[str, bytes]:
    """Return (original mime type, sanitized JPEG display bytes) or raise 422."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise too_large()
    try:
        with Image.open(BytesIO(data)) as probe:
            fmt = probe.format
            if fmt not in ACCEPTED_FORMATS or probe.width * probe.height > MAX_PIXELS:
                raise unsupported()
            probe.verify()
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((DISPLAY_MAX_PX, DISPLAY_MAX_PX))
            out = BytesIO()
            image.save(out, "JPEG", quality=85)  # no exif= argument: metadata is dropped
    except PlatformError:
        raise
    except Exception:  # Pillow plugins raise many types (EOFError, struct.error, ...) on hostile files
        raise unsupported() from None
    return ACCEPTED_FORMATS[fmt], out.getvalue()
