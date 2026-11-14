"""HTTP surface for the recovery platform (05-SHARED-CONTRACT.md, "HTTP surface").

`build_router(store, assessment_launcher)` returns an APIRouter the lead mounts in
backend/server.py. Identity comes only from HttpOnly session cookies; household and
case come from the session, never from request JSON. All errors use the contract's
envelope and every response is `Cache-Control: no-store`.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from collections import deque
from typing import AsyncIterator, Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from . import models as m
from . import uploads
from .households import (CreateHouseholdInput, CreateHouseholdResult, HouseholdAccessListing,
                         RevokeHouseholdAccessInput, RevokeHouseholdAccessResult)
from .auth import LOCAL_OWNER_ID, Actor, check_owner_secret
from .errors import PlatformError, unauthenticated
from .store import OWNER_SESSION_TTL, RESIDENT_SESSION_TTL, CaseStore

OWNER_COOKIE = "brace_owner_session"
RESIDENT_COOKIE = "brace_resident_session"
COOKIE_PATH = "/api"
ALLOWED_ORIGINS_ENV = "BRACE_ALLOWED_ORIGINS"
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 1.0
OWNER_LOGIN_MAX_FAILURES = 10
OWNER_LOGIN_WINDOW_SECONDS = 300
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_monotonic = time.monotonic

AssessmentLauncher = Callable[[dict], object]


class EnvelopeRoute(APIRoute):
    """Turn PlatformError and validation failures into the contract envelope; never cache."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                if request.method not in ("GET", "HEAD", "OPTIONS"):
                    check_origin(request)
                response = await original(request)
            except PlatformError as exc:
                response = JSONResponse(exc.envelope(), status_code=exc.status)
            except RequestValidationError as exc:
                fields = sorted({".".join(str(p) for p in err.get("loc", ())[1:]) or "body"
                                 for err in exc.errors()})
                err = PlatformError(422, "invalid_request", "Some fields are missing or invalid: "
                                    + ", ".join(fields)[:300])
                response = JSONResponse(err.envelope(), status_code=422)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


def check_origin(request: Request) -> None:
    """CSRF defence for state changes, on top of SameSite=Strict cookies.

    Browsers set Sec-Fetch-Site and page scripts cannot forge it, so a cross-site request
    is rejected. The Vite proxy rewrites Host (changeOrigin), so Origin is compared with
    an explicit allowlist instead, and only when BRACE_ALLOWED_ORIGINS is configured.
    """
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise PlatformError(403, "cross_site_request", "This request came from another site.")
    allowed = {o.strip().rstrip("/") for o in os.environ.get(ALLOWED_ORIGINS_ENV, "").split(",") if o.strip()}
    origin = request.headers.get("origin")
    if allowed and origin is not None and origin.rstrip("/") not in allowed:
        raise PlatformError(403, "cross_site_request", "This request came from another site.")


def parse_cursor(request: Request) -> int:
    raw = request.headers.get("last-event-id") or request.query_params.get("after") or "0"
    if not raw.isdigit():
        raise PlatformError(422, "invalid_cursor", "The event cursor must be a non-negative integer.")
    return int(raw)


async def event_stream(store: CaseStore, token: str, role: str, cursor: int, case_id: Optional[str],
                       *, poll_seconds: float = POLL_SECONDS) -> AsyncIterator[dict]:
    """Persisted-cursor replay with session checks before reads and delivery.

    A revoked/expired session never drains pending private events. An established
    resident stream may receive only its scoped, persisted revocation notice on
    its way out; that notice has no report, support, financial, or media content.
    """
    actor = await run_in_threadpool(store.resolve_session, token)
    if actor is None or actor.role != role:
        return

    async def terminal_notice():
        if actor.role != "resident":
            return None
        events = await run_in_threadpool(store.events_after, actor, cursor, case_id)
        notices = [event for event in events if event.type == "session.revoked"]
        if notices:
            event = notices[-1]
            return {"id": str(event.event_id), "data": event.model_dump_json()}
        return None

    while True:
        current = await run_in_threadpool(store.resolve_session, token)
        if current is None or current != actor:
            notice = await terminal_notice()
            if notice:
                yield notice
            return
        events = await run_in_threadpool(store.events_after, actor, cursor, case_id)
        for event in events:
            # Session revocation can happen during the query or while the client
            # is consuming an earlier frame in this batch.
            current = await run_in_threadpool(store.resolve_session, token)
            if current is None or current != actor:
                notice = await terminal_notice()
                if notice:
                    yield notice
                return
            cursor = event.event_id
            # Revocation notices belong to the invalidated session, not every
            # invitation for its household. A replacement (or another valid)
            # invitation must not expire when replaying this household event.
            if actor.role == "resident" and event.type == "session.revoked":
                continue
            yield {"id": str(event.event_id), "data": event.model_dump_json()}
        if not events:
            await asyncio.sleep(poll_seconds)


def _secure(request: Request) -> bool:
    """Secure cookies on HTTPS. uvicorn already applies X-Forwarded-Proto from trusted
    proxies to the scheme; the raw header is honored only from a loopback client (the
    local Vite proxy), never from an arbitrary device."""
    if request.url.scheme == "https":
        return True
    client = request.client.host if request.client else None
    proto = request.headers.get("x-forwarded-proto", "")
    return client in LOOPBACK_HOSTS and proto.split(",")[0].strip().lower() == "https"


def _set_cookie(response: Response, request: Request, name: str, token: str, max_age: int) -> None:
    response.set_cookie(name, token, max_age=max_age, path=COOKIE_PATH, httponly=True,
                        samesite="strict", secure=_secure(request))


def _actor(store: CaseStore, request: Request, cookie: str, role: str) -> Actor:
    actor = store.resolve_session(request.cookies.get(cookie))
    if actor is None or actor.role != role:
        raise unauthenticated()
    return actor


def make_owner_dependency(store: CaseStore):
    """FastAPI dependency for gating existing owner endpoints (building/plan/image routes).

    Usage in server.py: `dependencies=[Depends(make_owner_dependency(store))]`. Raises a
    plain HTTPException so it works on routes outside this router.
    """

    def require_owner(request: Request) -> Actor:
        actor = store.resolve_session(request.cookies.get(OWNER_COOKIE))
        if actor is None or actor.role != "owner":
            raise HTTPException(401, detail=unauthenticated().envelope()["error"])
        return actor

    return require_owner


def build_router(store: CaseStore, assessment_launcher: Optional[AssessmentLauncher] = None) -> APIRouter:
    router = APIRouter(route_class=EnvelopeRoute)

    def owner(request: Request) -> Actor:
        return _actor(store, request, OWNER_COOKIE, "owner")

    def resident(request: Request) -> Actor:
        return _actor(store, request, RESIDENT_COOKIE, "resident")

    # ---------------------------------------------------------------- owner

    login_failures: deque[float] = deque()
    login_lock = threading.Lock()

    def throttle_failed_owner_login() -> None:
        # The loopback proxy can hide client identities. Bound failed attempts
        # without letting one client lock out an owner with the correct secret.
        with login_lock:
            now = _monotonic()
            cutoff = now - OWNER_LOGIN_WINDOW_SECONDS
            while login_failures and login_failures[0] <= cutoff:
                login_failures.popleft()
            if len(login_failures) >= OWNER_LOGIN_MAX_FAILURES:
                raise PlatformError(429, "too_many_attempts",
                                    "Too many sign-in attempts. Wait a few minutes and try again.", retryable=True)
            login_failures.append(now)

    @router.post("/api/recovery/session")
    def owner_session(body: m.OwnerSessionInput, request: Request, response: Response):
        if not check_owner_secret(body.secret):
            throttle_failed_owner_login()
            raise PlatformError(401, "invalid_secret", "That owner secret is not correct.")
        store.end_session(request.cookies.get(OWNER_COOKIE))
        _set_cookie(response, request, OWNER_COOKIE, store.create_owner_session(LOCAL_OWNER_ID),
                    int(OWNER_SESSION_TTL.total_seconds()))
        return {"ok": True}

    @router.get("/api/recovery/cases")
    def list_cases(request: Request):
        return {"cases": store.list_cases(owner(request))}

    @router.get("/api/recovery/cases/{case_id}", response_model=m.OwnerCaseView)
    def case_view(case_id: str, request: Request):
        return store.owner_snapshot(owner(request), case_id)

    @router.post("/api/recovery/cases/{case_id}/households", response_model=CreateHouseholdResult,
                 status_code=201)
    def create_household(case_id: str, body: CreateHouseholdInput, request: Request,
                         idempotency_key: str = Header(min_length=8, max_length=200)):
        return store.create_household(owner(request), case_id, body, idempotency_key)

    @router.get("/api/recovery/cases/{case_id}/households/access", response_model=HouseholdAccessListing)
    def household_access(case_id: str, request: Request):
        return store.household_access(owner(request), case_id)

    @router.post("/api/recovery/cases/{case_id}/households/{household_id}/revoke-access",
                 response_model=RevokeHouseholdAccessResult)
    def revoke_household_access(case_id: str, household_id: str, body: RevokeHouseholdAccessInput,
                                request: Request, idempotency_key: str = Header(min_length=8, max_length=200)):
        return store.revoke_household_access(owner(request), case_id, household_id, body, idempotency_key)

    @router.post("/api/recovery/cases/{case_id}/commands", response_model=m.CommandResult)
    def command(case_id: str, body: m.OwnerCommand, request: Request,
                idempotency_key: Optional[str] = Header(default=None)):
        return store.apply_command(owner(request), case_id, body, idempotency_key,
                                   launcher=assessment_launcher)

    # ---------------------------------------------------------------- resident

    @router.post("/api/resident/session")
    def resident_session(body: m.ResidentSessionInput, request: Request, response: Response):
        token = store.exchange_invitation(body.invitation_token)
        store.end_session(request.cookies.get(RESIDENT_COOKIE))
        _set_cookie(response, request, RESIDENT_COOKIE, token, int(RESIDENT_SESSION_TTL.total_seconds()))
        return {"ok": True}

    @router.get("/api/resident/home", response_model=m.ResidentHome)
    def resident_home(request: Request):
        return store.resident_home(resident(request))

    @router.post("/api/resident/uploads", response_model=m.UploadedMedia)
    async def resident_upload(request: Request, idempotency_key: Optional[str] = Header(default=None)):
        # Cheap checks first: never read up to 10 MB for a request that will be refused.
        actor = await run_in_threadpool(resident, request)
        store._check_key(idempotency_key)
        body = await uploads.read_limited(request)
        data = uploads.extract_file_part(request.headers.get("content-type", ""), body)
        return await run_in_threadpool(store.save_upload, actor, data, idempotency_key)

    @router.get("/api/recovery/media/{media_id}")
    def media(media_id: str, request: Request):
        actor = store.resolve_session(request.cookies.get(OWNER_COOKIE))
        if actor is None or actor.role != "owner":
            actor = store.resolve_session(request.cookies.get(RESIDENT_COOKIE))
        if actor is None:
            raise unauthenticated()
        return Response(store.media_bytes(actor, media_id), media_type="image/jpeg",
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": "inline"})

    @router.get("/api/recovery/cases/{case_id}/events")
    def owner_events(case_id: str, request: Request):
        actor = owner(request)
        cursor = parse_cursor(request)
        store.events_after(actor, cursor, case_id, limit=1)  # 404 unless this owner's case
        return EventSourceResponse(event_stream(store, request.cookies[OWNER_COOKIE], "owner", cursor, case_id),
                                   ping=HEARTBEAT_SECONDS)

    @router.get("/api/resident/events")
    def resident_events(request: Request):
        resident(request)
        cursor = parse_cursor(request)
        return EventSourceResponse(event_stream(store, request.cookies[RESIDENT_COOKIE], "resident", cursor, None),
                                   ping=HEARTBEAT_SECONDS)

    @router.post("/api/resident/support", response_model=m.SupportReceipt)
    def resident_support(body: m.SupportInput, request: Request,
                         idempotency_key: Optional[str] = Header(default=None)):
        return store.append_support_request(resident(request), body, idempotency_key)

    @router.post("/api/resident/reports", response_model=m.ReportReceipt)
    def resident_report(body: m.ReportInput, request: Request,
                        idempotency_key: Optional[str] = Header(default=None)):
        return store.append_report(resident(request), body, idempotency_key)

    return router
