"""Owner-only, stateless value-impact previews over the registered case inventory."""
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .domain.financial_models import FinancialInputError
from .domain.impact import ImpactInput, calculate_impact, impact_sources
from .evidence_router import PRIVATE_HEADERS, _EvidenceFailure, _call, _mapping, _response, _validate_manifest
from .platform.errors import PlatformError
from .platform.router import EnvelopeRoute


class _ImpactRoute(EnvelopeRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except _EvidenceFailure as error:
                response = _response(error)
            response.headers.update(PRIVATE_HEADERS)
            return response

        return handler


def build_impact_router(resolve_owner_case: Callable, inventory_provider: Callable) -> APIRouter:
    router = APIRouter(route_class=_ImpactRoute)

    async def load(request: Request, case_id: str):
        try:
            snapshot = _mapping(await _call(resolve_owner_case, request, case_id))
            if snapshot.get("case", {}).get("case_id") != case_id:
                raise _EvidenceFailure(404, "case_not_found", "This recovery case is unavailable.")
            inventory = _mapping(await _call(inventory_provider, snapshot))
            await run_in_threadpool(_validate_manifest, snapshot, inventory, case_id)
            return snapshot, inventory
        except HTTPException as error:
            status = error.status_code if error.status_code in (401, 403, 404) else 503
            raise _EvidenceFailure(status, "owner_access_required" if status in (401, 403) else "case_unavailable",
                                   "Owner access to this registered case is required.") from None
        except PermissionError:
            raise _EvidenceFailure(403, "forbidden", "Owner access to this case is required.") from None
        except (_EvidenceFailure, PlatformError):
            raise
        except Exception:
            raise _EvidenceFailure(503, "evidence_unavailable", "Registered source inputs are temporarily unavailable.") from None

    @router.get("/api/recovery/cases/{case_id}/value-impact")
    async def get_sources(request: Request, case_id: str):
        snapshot, inventory = await load(request, case_id)
        return JSONResponse(await run_in_threadpool(impact_sources, inventory, snapshot), headers=PRIVATE_HEADERS)

    @router.post("/api/recovery/cases/{case_id}/value-impact")
    async def preview(request: Request, case_id: str, body: ImpactInput):
        snapshot, inventory = await load(request, case_id)
        revision = snapshot["case"]["analysis_revision"]
        if body.expected_analysis_revision != revision:
            raise PlatformError(409, "analysis_revision_conflict", "Case evidence changed. Reload the source quantities before calculating.",
                                retryable=True, current_revision=revision)
        try:
            result = await run_in_threadpool(calculate_impact, inventory, snapshot, body)
        except FinancialInputError as error:
            raise PlatformError(422, "invalid_scenario", str(error)) from None
        return JSONResponse(result, headers=PRIVATE_HEADERS)

    return router
