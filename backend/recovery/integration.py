"""Lead-owned security wiring; install with Platform's authenticated router.

This module implements no credentials, sessions, resident permissions, or store.
The supplied authorizer must establish an owner from trusted server-side state.
It may return an authorized actor/True or raise HTTPException(401/403). False or
None denies access. Never use a client-provided role as authorization.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send


def _platform_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ("/api/recovery", "/api/resident"))


class _LegacyOwnerGate:
    def __init__(self, app: ASGIApp, *, authorize_owner: Callable, router: Any, cors_preflight: bool):
        self.app, self.authorize_owner, self.router = app, authorize_owner, router
        self.cors_preflight = cors_preflight

    def _mounted_platform_route(self, scope: Scope) -> bool:
        # Unknown namespace URLs stay 404 even when a legacy catch-all is present.
        # Only explicit platform routes may delegate their permission checks.
        partial = None
        def effective_routes():
            for route in self.router.routes:
                # FastAPI can retain included routers as branches rather than
                # copying APIRoutes. Their contexts apply all include prefixes.
                # A branch has no path, so inspecting it directly fails closed
                # even for valid session bootstrap endpoints.
                contexts = getattr(route, "effective_route_contexts", None)
                if callable(contexts):
                    yield from contexts()
                else:
                    yield route

        def declared_path(route):
            return (getattr(route, "path", None) or getattr(route, "path_format", None)
                    or getattr(getattr(route, "starlette_route", None), "path", ""))

        for route in effective_routes():
            match = route.matches(scope)[0]
            if match == Match.FULL:
                # Match actual router order: a legacy catch-all ahead of a later
                # platform declaration must never receive the delegated bypass.
                return _platform_path(declared_path(route))
            if match == Match.PARTIAL and partial is None:
                partial = route
        return partial is not None and _platform_path(declared_path(partial))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == "/api" or path.startswith("/api/")):
            await self.app(scope, receive, send)
            return

        async def private_send(message: dict) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", []))}
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "private, no-store"
                headers["Pragma"] = "no-cache"
                headers["Expires"] = "0"
                # Shared caches/CDNs must not override the browser cache policy.
                headers["CDN-Cache-Control"] = "no-store"
                headers["Surrogate-Control"] = "no-store"
            await send(message)

        async def error(status: int, code: str, message: str, *, retryable: bool = False) -> None:
            response = JSONResponse({"error": {"code": code, "message": message, "retryable": retryable}}, status_code=status)
            await response(scope, receive, private_send)

        headers = Headers(scope=scope)
        # Only an installed CORS middleware may handle preflight without a session.
        # It intercepts these requests before routing; actual requests remain gated.
        if self.cors_preflight and scope.get("method") == "OPTIONS" and "origin" in headers and "access-control-request-method" in headers:
            await self.app(scope, receive, private_send)
            return

        if _platform_path(path):
            if not self._mounted_platform_route(scope):
                await error(404, "not_found", "This endpoint is unavailable.")
                return
            await self.app(scope, receive, private_send)
            return

        try:
            request = Request(scope, receive=receive)
            if inspect.iscoroutinefunction(self.authorize_owner):
                actor = await self.authorize_owner(request)
            else:
                actor = await run_in_threadpool(self.authorize_owner, request)
                if inspect.isawaitable(actor):
                    actor = await actor
            if not actor:
                await error(401, "authentication_required", "An owner session is required.")
                return
            role = actor.get("role") if isinstance(actor, dict) else getattr(actor, "role", None)
            if role is not None and role != "owner":
                await error(403, "owner_required", "This endpoint requires owner access.")
                return
        except HTTPException as exc:
            status = 403 if exc.status_code == 403 else 401
            await error(status, "owner_required" if status == 403 else "authentication_required",
                        "This endpoint requires owner access." if status == 403 else "An owner session is required.")
            return
        except Exception:
            # Dependency errors can include tokens, signed URLs or resident data.
            await error(401, "authentication_unavailable", "Owner authorization could not be established.", retryable=True)
            return
        await self.app(scope, receive, private_send)


def install_legacy_owner_gate(app: FastAPI, authorize_owner: Callable[[Request], Any]) -> None:
    """Idempotently protect every legacy/future /api route before serving requests.

    Install Platform's router first (or before application startup). Explicit
    /api/recovery and /api/resident routes keep their own scoped authentication,
    including their session bootstrap endpoints. Unknown namespace paths are 404.
    All other API paths require owner authorization. The authorizer should inspect
    headers/cookies/server state and must not consume the request body.

    This helper does not enable resident access by itself and is intentionally not
    called by the existing server until Platform's router is ready.
    """
    if getattr(app.state, "brace_legacy_owner_gate_installed", False):
        return
    if not callable(authorize_owner):
        raise TypeError("An owner authorization callback is required")
    cors_preflight = any(issubclass(middleware.cls, CORSMiddleware) for middleware in app.user_middleware)
    app.add_middleware(_LegacyOwnerGate, authorize_owner=authorize_owner, router=app.router,
                       cors_preflight=cors_preflight)
    app.state.brace_legacy_owner_gate_installed = True
