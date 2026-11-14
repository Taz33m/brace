"""Explicit owner responses to resident support requests, persisted atomically.

These are portal status updates, never external messages or automatically booked
assistance. Case revisions move; financial analysis inputs do not change.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Annotated, Callable, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .notice_router import _NoticeRoute as OwnerEnvelopeRoute
from .platform.auth import hash_token
from .platform.errors import PlatformError
from .platform.store import dumps


class SupportResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)
    status: Literal["under_review", "responded", "closed"]
    public_status_detail: str = Field(min_length=1, max_length=1200)

    @field_validator("public_status_detail")
    @classmethod
    def explicit_copy(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("An explicit resident-visible update is required")
        return value


_TRANSITIONS = {
    "received": {"under_review", "responded", "closed"},
    "under_review": {"under_review", "responded", "closed"},
    "responded": {"responded", "under_review", "closed"},
    "closed": {"closed", "under_review"},
}


def respond_support_request(store, actor, case_id: str, request_id: str,
                            body: SupportResponseInput, idempotency_key: str) -> dict:
    """A narrow extension of CaseStore's transaction/idempotency primitives.

    Authorization, revision check, state update, household event, and retry
    receipt share one transaction. No separate ledger or shadow case state.
    """
    key = store._check_key(idempotency_key)
    operation = f"support-response:{case_id}:{request_id}"
    body_hash = hash_token(dumps(body))
    with store._write() as conn:
        case = store._owner_case(conn, actor, case_id)
        replay = store._replay(conn, actor, operation, key, body_hash)
        if replay is not None:
            replay = deepcopy(replay)
            replay["duplicate"] = True
            replay["request"]["duplicate"] = True
            return replay
        row = conn.execute("SELECT * FROM support_requests WHERE case_id = ? AND request_id = ?",
                           (case_id, request_id)).fetchone()
        if row is None:
            raise PlatformError(404, "support_request_not_found", "This support request was not found on this case.")
        store._check_revision(case, body.expected_revision)
        data = json.loads(row["json"])
        if body.status not in _TRANSITIONS.get(data["status"], set()):
            raise PlatformError(409, "invalid_transition", "Reopen a closed request for review before responding again.")
        data.update(status=body.status, public_status_detail=body.public_status_detail.strip())
        conn.execute("UPDATE support_requests SET json = ? WHERE case_id = ? AND request_id = ?",
                     (dumps(data), case_id, request_id))
        case_revision, analysis_revision = store._bump(conn, case_id)
        store._event(conn, case_id, "support.updated", audience="households", households=[row["household_id"]],
                     entity_id=request_id, public_summary="The property team updated your support request")
        updated = conn.execute("SELECT * FROM support_requests WHERE case_id = ? AND request_id = ?",
                               (case_id, request_id)).fetchone()
        result = {"request": store._support_view(updated).model_dump(mode="json"), "case_revision": case_revision,
                  "analysis_revision": analysis_revision, "duplicate": False}
        store._remember(conn, actor, operation, key, body_hash, result)
        return result


def build_support_router(store, resolve_owner: Callable) -> APIRouter:
    router = APIRouter(route_class=OwnerEnvelopeRoute)

    @router.get("/api/recovery/cases/{case_id}/support-requests")
    def requests(case_id: str, actor=Depends(resolve_owner)):
        with store._read() as conn:
            case = store._owner_case(conn, actor, case_id)
            rows = conn.execute("SELECT * FROM support_requests WHERE case_id = ? ORDER BY received_at, rowid", (case_id,))
            return {"case_id": case_id, "case_revision": case["case_revision"], "analysis_revision": case["analysis_revision"],
                    "requests": [store._support_view(row).model_dump(mode="json") for row in rows]}

    @router.post("/api/recovery/cases/{case_id}/support-requests/{request_id}/respond")
    def respond(case_id: str, request_id: str, body: SupportResponseInput,
                idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
                actor=Depends(resolve_owner)):
        return respond_support_request(store, actor, case_id, request_id, body, idempotency_key)

    return router
