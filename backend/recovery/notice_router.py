"""Owner review of agent notice drafts; publication remains a Platform command.

No messages are sent. Source citations come from the stored draft, never the
publish body. A draft's run and current analysis revision establish eligibility.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException

from .platform.errors import PlatformError, revision_conflict
from .platform.models import CommandResult, PublishNotice
from .platform.router import EnvelopeRoute


class PublishDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    household_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("title", "body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must not be blank")
        return value


class _NoticeRoute(EnvelopeRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except HTTPException as exc:
                code = "authentication_required" if exc.status_code == 401 else "access_denied"
                response = JSONResponse({"error": {"code": code, "message": "Owner access is required.", "retryable": False}},
                                        status_code=exc.status_code)
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return handler


def _dictionary(model) -> dict:
    return model.model_dump(mode="json") if hasattr(model, "model_dump") else model


def _rows(snapshot: dict, stored: list[dict]) -> list[dict]:
    assessments = {row["run_id"]: row for row in snapshot["assessments"]}
    known_sources = {row[key] for row in snapshot["evidence"] for key in ("evidence_id", "source_id")}
    ids = Counter(row.get("draft_id") for row in stored if isinstance(row.get("draft_id"), str))
    output = []
    for draft in stored:
        identity = draft.get("draft_id")
        if not isinstance(identity, str) or not identity:
            identity = "legacy:" + hashlib.sha256(json.dumps(draft, sort_keys=True).encode()).hexdigest()[:20]
        match = re.fullmatch(r"(.+):notice:([1-9][0-9]*)", identity)
        run_id = match.group(1) if match else None
        assessment = assessments.get(run_id)
        sources = draft.get("source_ids")
        valid_sources = isinstance(sources, list) and len(sources) <= 50 and all(isinstance(s, str) and s for s in sources)
        reason = None
        if ids.get(identity, 0) != 1:
            reason = "This draft has no unique linked identifier. Create a fresh assessment draft."
        elif assessment is None:
            reason = "This draft is not linked to an assessment on this case."
        elif assessment["status"] not in {"draft", "published"}:
            reason = "The assessment behind this draft is not current and reviewable."
        elif assessment["base_analysis_revision"] != snapshot["case"]["analysis_revision"]:
            reason = "New evidence arrived after this draft. Run a fresh assessment."
        elif not valid_sources or not set(sources).issubset(known_sources):
            reason = "This draft cites sources that are unavailable on this case."
        output.append({"draft_id": identity, "run_id": run_id if assessment else None,
                       "base_analysis_revision": assessment["base_analysis_revision"] if assessment else None,
                       "title": draft.get("title") if isinstance(draft.get("title"), str) else "",
                       "body": draft.get("body") if isinstance(draft.get("body"), str) else "",
                       "source_ids": list(sources) if valid_sources else [], "eligible": reason is None,
                       "unavailable_reason": reason})
    return output


def build_notice_router(store, resolve_owner: Callable) -> APIRouter:
    """Add GET review and POST publication endpoints to the authenticated app.

    Retried old revisions delegate to Platform's command idempotency BEFORE its
    revision check. Revisions only increase, so an old revision with no saved
    receipt cannot create a new publication, even when this draft is now stale.
    Fresh/current requests must pass eligibility and Platform's atomic revision
    check. Future revisions are rejected before any command dispatch.
    """
    router = APIRouter(route_class=_NoticeRoute)

    def state(actor, case_id):
        if actor is None or getattr(actor, "role", None) != "owner":
            raise PlatformError(403, "owner_required", "Owner access is required.")
        snapshot = _dictionary(store.owner_snapshot(actor, case_id))
        return snapshot, _rows(snapshot, store.draft_notices(actor, case_id))

    @router.get("/api/recovery/cases/{case_id}/draft-notices")
    def drafts(case_id: str, actor=Depends(resolve_owner)):
        snapshot, rows = state(actor, case_id)
        return {"case_id": case_id, "case_revision": snapshot["case"]["case_revision"],
                "analysis_revision": snapshot["case"]["analysis_revision"], "drafts": rows}

    @router.post("/api/recovery/cases/{case_id}/draft-notices/{draft_id}/publish", response_model=CommandResult)
    def publish(case_id: str, draft_id: str, body: PublishDraftInput,
                idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
                actor=Depends(resolve_owner)):
        if not idempotency_key.isprintable():
            raise PlatformError(422, "idempotency_key_required", "Use a printable Idempotency-Key.")
        snapshot, rows = state(actor, case_id)
        matches = [row for row in rows if row["draft_id"] == draft_id]
        if not matches:
            raise PlatformError(404, "draft_not_found", "This draft was not found on this case.")
        if len(matches) != 1:
            raise PlatformError(409, "draft_ambiguous", "This draft has an ambiguous identifier. Run a fresh assessment.")
        draft = matches[0]
        current = snapshot["case"]["case_revision"]
        if body.expected_revision > current:
            raise revision_conflict(current)
        if body.expected_revision == current and not draft["eligible"]:
            raise PlatformError(409, "draft_unavailable", draft["unavailable_reason"], retryable=True, current_revision=current)
        # Scope receipt identity to the draft route, preventing collisions with a
        # generic PublishNotice command or another draft using the same client key.
        key = "draft:" + hashlib.sha256(json.dumps([case_id, draft_id, idempotency_key], separators=(",", ":")).encode()).hexdigest()
        command = PublishNotice(type="publish_notice", expected_revision=body.expected_revision,
                                title=body.title, body=body.body, household_ids=body.household_ids,
                                source_ids=draft["source_ids"])
        return store.apply_command(actor, case_id, command, key)

    return router
