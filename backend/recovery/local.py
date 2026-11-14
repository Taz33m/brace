"""Explicit local-demo assembly of the real Platform and lead recovery engine.

The configured local operator can use the preparation portfolio. Other owner
identities remain restricted to their case routes. No credentials are generated.
"""
from __future__ import annotations

from copy import deepcopy
import fcntl
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from .registry import CaseInputRegistry
from .runtime import install_recovery


class LocalRecoveryLock:
    """One local runtime/importer per database; reopening must not fail live runs."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.fd = os.open(directory / "runtime.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            self.fd = None
            raise RuntimeError("The recovery database is in use. Stop its server before importing or starting another runtime.") from None

    def close(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def configured_origins() -> frozenset[str]:
    raw = os.environ.get("BRACE_ALLOWED_ORIGINS", "http://localhost:5174,http://127.0.0.1:5174")
    origins = frozenset(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
    if not origins:
        raise ValueError("Configure at least one recovery browser origin")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or "*" in origin):
            raise ValueError("Recovery browser origins must be explicit HTTP(S) origins")
    return origins


class MutationOriginGate:
    """Cover legacy and Platform writes, including same-site sibling origins."""

    def __init__(self, app, *, origins: frozenset[str]):
        self.app, self.origins = app, origins

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope.get("path", "").startswith("/api/")
                and scope.get("method") not in ("GET", "HEAD", "OPTIONS")):
            headers = Headers(scope=scope)
            origin, site = headers.get("origin"), headers.get("sec-fetch-site", "").lower()
            if (site == "cross-site" or (origin is not None and origin.rstrip("/") not in self.origins)
                    or (origin is None and site not in ("", "none"))):
                response = JSONResponse({"error": {"code": "cross_site_request",
                    "message": "This request came from an unapproved browser origin.", "retryable": False}},
                    status_code=403, headers={"Cache-Control": "private, no-store"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install_local_recovery(app: FastAPI, *, root: Path | None = None, agent_factory=None):
    """Called only by the enabled local server; tests inject a temporary root/model."""
    if app.middleware_stack is not None or getattr(app.state, "brace_recovery_service", None) is not None:
        raise RuntimeError("Install recovery once, before serving requests")
    from ..config import DATA_DIR
    from .platform.auth import Actor, LOCAL_OWNER_ID
    from .platform.errors import PlatformError
    from .platform.router import build_router, make_owner_dependency
    from .platform.store import CaseStore
    from .report_images import with_report_images
    from .notice_router import build_notice_router

    origins = configured_origins()
    directory = Path(root or os.environ.get("BRACE_RECOVERY_DATA_DIR") or DATA_DIR / "recovery")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = directory / "platform"
    lock = LocalRecoveryLock(private)
    try:
        store = CaseStore(private / "platform.sqlite3", private / "media")
        registry = CaseInputRegistry(directory / "registered-inputs")
    except Exception:
        lock.close()
        raise
    owner = make_owner_dependency(store)

    def legacy_owner(request: Request):
        actor = owner(request)
        # The local operator is explicitly allowed to prepare the kit portfolio.
        # A future multi-owner deployment must not grant this to every owner role.
        if actor.actor_id != LOCAL_OWNER_ID:
            raise HTTPException(403)
        return actor

    def owner_case(request: Request, case_id: str):
        try:
            return store.owner_snapshot(owner(request), case_id).model_dump(mode="json")
        except PlatformError as exc:
            raise HTTPException(exc.status) from None

    def report_image(snapshot: dict, evidence: dict) -> bytes:
        # The worker operates only on this configured operator's cases. Recheck
        # membership through the store; never fetch evidence.media.url.
        actor = Actor("owner", LOCAL_OWNER_ID)
        current = store.owner_snapshot(actor, snapshot["case"]["case_id"])
        expected = evidence["media"]["media_id"]
        match = next((row for row in current.evidence if row.evidence_id == evidence["evidence_id"]), None)
        frozen_reports = {report["report_id"] for report in snapshot.get("reports", [])
                          if any(media.get("media_id") == expected for media in report.get("media", []))}
        attached = any(report.report_id in frozen_reports and any(media.media_id == expected for media in report.media)
                       for report in current.reports)
        if (not attached or match is None or match.kind != "resident_photo" or match.media is None
                or match.media.media_id != expected or match.source_id != expected):
            raise ValueError("The report image is no longer attached to this case")
        return store.media_bytes(actor, expected)

    try:
        service = install_recovery(app, store=store, registry=registry, platform_router_factory=build_router,
            resolve_owner=legacy_owner, resolve_owner_case=owner_case, agent_factory=agent_factory,
            input_provider=with_report_images(registry.input_provider, report_image))
        app.include_router(build_notice_router(store, owner))
        app.add_middleware(MutationOriginGate, origins=origins)
        app.router.add_event_handler("shutdown", lock.close)
        app.state.brace_recovery_store = store
        app.state.brace_recovery_registry = registry
        return service
    except Exception:
        lock.close()
        raise


def import_fresh_case(store, registry: CaseInputRegistry, seed: dict, inventory: dict, finance=None) -> dict:
    """Idempotent operator bootstrap; never overwrites reports or creates residents."""
    from .platform.auth import Actor, LOCAL_OWNER_ID
    from .platform.errors import PlatformError
    from .platform.models import CaseInput

    if any(seed.get(key) for key in ("observations", "reports", "tasks", "assessments", "household_labels", "notices")):
        raise ValueError("Import a fresh source seed, not a reviewed recovery snapshot")
    actor = Actor("owner", LOCAL_OWNER_ID)
    case_id = seed["case"]["case_id"]
    # Validate source registration before any database mutation.
    registry.register(seed, inventory, finance)
    try:
        snapshot = store.owner_snapshot(actor, case_id).model_dump(mode="json")
    except PlatformError as exc:
        if exc.status != 404:
            raise
        value = CaseInput.from_seed({**deepcopy(seed), "locations": deepcopy(inventory.get("locations", []))})
        store.create_case(actor, value)
        snapshot = store.owner_snapshot(actor, case_id).model_dump(mode="json")
    registry.load_inventory(snapshot)
    return snapshot
