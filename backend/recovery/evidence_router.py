"""Owner-only views of a registered, frozen sponsor evidence inventory.

Authentication and case assignment belong to ``resolve_owner_case``. This module
never loads a global property, refreshes an inventory, or fetches sponsor images.
The injected inventory provider must return a case-scoped registered manifest.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from inspect import isawaitable, iscoroutinefunction
from io import BytesIO
from pathlib import Path
import re
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.concurrency import run_in_threadpool

from .domain.temporal import date_bounds, normalize_date, source_eligibility

PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Cookie, Authorization",
                   "X-Content-Type-Options": "nosniff"}
_CONTEXT = ("case_id", "property_ref", "incident_at", "assessment_as_of", "mode")
_IMAGE_KINDS = {"vexcel_image", "matterport_view"}


class _EvidenceFailure(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def _refresh() -> _EvidenceFailure:
    return _EvidenceFailure(503, "source_refresh_required", "Source evidence changed. Refresh the registered case inventory.")


def _missing_image() -> _EvidenceFailure:
    return _EvidenceFailure(404, "evidence_image_unavailable", "No cached image is available for this evidence.")


def _response(error: _EvidenceFailure) -> JSONResponse:
    return JSONResponse({"error": {"code": error.code, "message": error.message,
                                   "retryable": error.status in (409, 503)}},
                        status_code=error.status, headers=PRIVATE_HEADERS)


async def _call(callback: Callable, *args):
    result = await callback(*args) if iscoroutinefunction(callback) else await run_in_threadpool(callback, *args)
    return await result if isawaitable(result) else result


def _mapping(value) -> dict:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        raise _refresh()
    return deepcopy(value)


def _validate_manifest(snapshot: dict, inventory: dict, case_id: str) -> None:
    from .registry import evidence_identity

    case = snapshot.get("case")
    if not isinstance(case, dict) or case.get("case_id") != case_id:
        # Never substitute a different case returned by an incorrectly wired resolver.
        raise _EvidenceFailure(404, "case_not_found", "This recovery case is unavailable.")
    revision = case.get("analysis_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise _refresh()
    expected = {key: case.get(key) for key in _CONTEXT}
    for key in ("incident_at", "assessment_as_of"):
        expected[key] = normalize_date(expected[key])
    if any(value is None for value in expected.values()) or inventory.get("_case_context") != expected:
        raise _refresh()
    if (inventory.get("subject") or {}).get("property_ref") != case["property_ref"]:
        raise _refresh()
    current_rows, original_rows = snapshot.get("evidence"), inventory.get("evidence")
    if not isinstance(current_rows, list) or not isinstance(original_rows, list):
        raise _refresh()
    try:
        current = {row["evidence_id"]: row for row in current_rows}
        original = {row["evidence_id"]: row for row in original_rows}
        if len(current) != len(current_rows) or len(original) != len(original_rows):
            raise _refresh()
        for evidence_id, row in original.items():
            if evidence_id not in current:
                raise _refresh()
            if evidence_identity(row) != evidence_identity(current[evidence_id]):
                raise _refresh()
            eligible, _ = source_eligibility(row.get("captured_at") or row.get("effective_at"),
                                             row.get("available_at"), case["assessment_as_of"], case["mode"])
            if not eligible:
                raise _refresh()
            if row.get("model_created_at") and date_bounds(row["model_created_at"])[1] > date_bounds(case["assessment_as_of"])[1]:
                raise _refresh()
        # Geometry is permitted only where the registered evidence supports that
        # scan or dated structure attribute record. New resident evidence does not
        # need to appear in this sponsor manifest.
        scan_ids = {(row.get("location") or {}).get("scan_id") for row in original_rows}
        source_ids = {row["source_id"] for row in original_rows}
        for scan in inventory.get("scans", []):
            if scan["id"] not in scan_ids:
                raise _refresh()
        structure_ids = set()
        for structure in inventory.get("structures", []):
            if structure.get("source_id") not in source_ids:
                raise _refresh()
            structure_ids.add(structure["id"])
        for location in inventory.get("locations", []):
            if location.get("scan_id") and location["scan_id"] not in scan_ids:
                raise _refresh()
            if location.get("structure_id") and location["structure_id"] not in structure_ids:
                raise _refresh()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise _refresh() from None


def _cached_image(inventory: dict, snapshot: dict, evidence_id: str, cache_root: Path) -> bytes:
    registered = {row["evidence_id"]: row for row in inventory["evidence"]}
    current = {row["evidence_id"]: row for row in snapshot["evidence"]}
    if evidence_id not in registered or evidence_id not in current or registered[evidence_id].get("kind") not in _IMAGE_KINDS:
        raise _missing_image()
    descriptor = inventory.get("assets", {}).get(evidence_id)
    # A request does not download a missing panorama/capture. Only pinned local
    # images enter this path; metadata-only and unmaterialized descriptors are 404.
    if not isinstance(descriptor, dict) or descriptor.get("kind") != "local_image":
        raise _missing_image()
    expected_hash, raw_path = descriptor.get("sha256"), descriptor.get("path")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_hash):
        raise _missing_image()
    if not isinstance(raw_path, str) or "://" in raw_path:
        raise _missing_image()
    try:
        path = Path(raw_path).resolve()
        if not path.is_relative_to(cache_root) or not path.is_file():
            raise _missing_image()
        with path.open("rb") as stream:
            raw = stream.read(25 * 1024 * 1024 + 1)
        if len(raw) > 25 * 1024 * 1024:
            raise _missing_image()
        if sha256(raw).hexdigest() != expected_hash.lower():
            raise _EvidenceFailure(409, "source_changed", "The cached image changed. Refresh the source evidence before viewing it.")
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 40_000_000:
                raise _missing_image()
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1536, 1536))
            output = BytesIO()
            image.save(output, "JPEG", quality=85)
        return output.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise _missing_image() from None


def _image_evidence_ids(inventory: dict, snapshot: dict, cache_root: Path) -> list[str]:
    """Only advertise images the cached-only endpoint can actually sanitize."""
    available = []
    for evidence_id, descriptor in inventory.get("assets", {}).items():
        if not isinstance(descriptor, dict) or descriptor.get("kind") != "local_image":
            continue
        try:
            _cached_image(inventory, snapshot, evidence_id, cache_root)
        except _EvidenceFailure:
            continue
        available.append(evidence_id)
    return available


def build_evidence_router(resolve_owner_case: Callable, inventory_provider: Callable,
                          *, cache_root: Path | None = None) -> APIRouter:
    """Build additive owner routes without replacing platform auth or storage.

    ``resolve_owner_case(request, case_id)`` MUST enforce authenticated owner and
    case assignment, then return OwnerCaseView. ``inventory_provider(snapshot)``
    returns its registered inventory with an exact ``_case_context`` manifest.
    Both callbacks support synchronous and asynchronous implementations.
    """
    from ..config import CACHE_DIR

    root = (cache_root or CACHE_DIR).resolve()
    router = APIRouter()

    async def load(request: Request, case_id: str) -> tuple[dict, dict]:
        try:
            snapshot = _mapping(await _call(resolve_owner_case, request, case_id))
            if (snapshot.get("case") or {}).get("case_id") != case_id:
                raise _EvidenceFailure(404, "case_not_found", "This recovery case is unavailable.")
            inventory = _mapping(await _call(inventory_provider, snapshot))
            await run_in_threadpool(_validate_manifest, snapshot, inventory, case_id)
            return snapshot, inventory
        except HTTPException as error:
            status = error.status_code if error.status_code in (401, 403, 404) else 503
            code, message = {
                401: ("unauthenticated", "An owner session is required."),
                403: ("forbidden", "Owner access to this case is required."),
                404: ("case_not_found", "This recovery case is unavailable."),
                503: ("evidence_unavailable", "Source evidence is temporarily unavailable."),
            }[status]
            raise _EvidenceFailure(status, code, message) from None
        except PermissionError:
            raise _EvidenceFailure(403, "forbidden", "Owner access to this case is required.") from None
        except _EvidenceFailure:
            raise
        except Exception:
            raise _EvidenceFailure(503, "evidence_unavailable", "Source evidence is temporarily unavailable.") from None

    @router.get("/api/recovery/cases/{case_id}/spatial")
    async def spatial(request: Request, case_id: str):
        try:
            snapshot, inventory = await load(request, case_id)
            result = {"case_id": case_id, "analysis_revision": snapshot["case"]["analysis_revision"]}
            for key in ("locations", "structures", "scans", "capture_pairs", "source_status", "limitations"):
                result[key] = inventory.get(key, {} if key in ("capture_pairs", "source_status") else [])
            result["image_evidence_ids"] = await run_in_threadpool(_image_evidence_ids, inventory, snapshot, root)
            return JSONResponse(result, headers=PRIVATE_HEADERS)
        except _EvidenceFailure as error:
            return _response(error)

    @router.get("/api/recovery/cases/{case_id}/evidence/{evidence_id}/image")
    async def evidence_image(request: Request, case_id: str, evidence_id: str):
        try:
            snapshot, inventory = await load(request, case_id)
            data = await run_in_threadpool(_cached_image, inventory, snapshot, evidence_id, root)
            return Response(data, media_type="image/jpeg", headers=PRIVATE_HEADERS)
        except _EvidenceFailure as error:
            return _response(error)

    return router
