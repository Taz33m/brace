"""Lead-owned assembly point; Platform supplies identity, persistence and routes.

Importing this module does not start workers or expose endpoints. Install only
after validating the team's real Platform implementation and configuration.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from .domain.service import AssessmentService
from .integration import install_legacy_owner_gate


def install_recovery(app: FastAPI, *, store: Any, registry: Any,
                     platform_router_factory: Callable,
                     resolve_owner: Callable, resolve_owner_case: Callable,
                     agent_factory: Callable | None = None,
                     input_provider: Callable | None = None) -> AssessmentService:
    """Mount the real platform and source viewers as one protected application.

    resolve_owner must authorize the specific legacy request, including property
    scope. resolve_owner_case(request, case_id) returns an authorized OwnerCaseView.
    The platform factory has the agreed build_router(store, assessment_launcher)
    signature. No default credentials, anonymous mode, or production stand-in.
    """
    from .evidence_router import build_evidence_router
    from .impact_router import build_impact_router

    if getattr(app.state, "brace_recovery_service", None) is not None:
        raise RuntimeError("Recovery is already installed on this application")
    if app.middleware_stack is not None:
        raise RuntimeError("Install recovery before the application starts serving requests")
    if not all(callable(cb) for cb in (platform_router_factory, resolve_owner, resolve_owner_case)):
        raise TypeError("Explicit platform routes and owner authorizers are required")
    if not all(callable(getattr(store, name, None)) for name in ("snapshot_for_analysis", "complete_assessment")):
        raise TypeError("The platform must implement the assessment worker handshake before mounting recovery")
    service = AssessmentService(store, input_provider or registry.input_provider, agent_factory=agent_factory)
    try:
        platform_router = platform_router_factory(store, service.launch)
        evidence_router = build_evidence_router(resolve_owner_case, registry.load_inventory)
        impact_router = build_impact_router(resolve_owner_case, registry.load_inventory)
        # Install the guard first, so even a later mounting failure fails closed.
        install_legacy_owner_gate(app, resolve_owner)
        # Explicit owner viewer routes precede any broad platform route pattern.
        app.include_router(evidence_router)
        app.include_router(impact_router)
        app.include_router(platform_router)
        app.router.add_event_handler("shutdown", service.close)
        app.state.brace_recovery_service = service
        return service
    except Exception:
        service.close()
        raise
