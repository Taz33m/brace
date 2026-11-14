"""Phase 3: SSE event streams, support requests, cross-site protection."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend.recovery.platform import router as router_mod
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.models import SupportInput
from tests.test_recovery_platform_api import (REPORT, app, invite, owner_client,  # noqa: F401 (fixtures)
                                              resident_client, store, world)
from tests.test_recovery_platform_support import OWNER, report

SUPPORT = {"category": "housing", "description": "We need somewhere to stay tonight"}


# ---------------------------------------------------------------- support requests

def test_support_request_is_idempotent_and_household_scoped(store, world):
    _, _, res_a, res_b = world
    first = store.append_support_request(res_a, SupportInput(**SUPPORT), "support-key-1")
    again = store.append_support_request(res_a, SupportInput(**SUPPORT), "support-key-1")
    assert first.status == "received" and again.duplicate and again.request_id == first.request_id
    with pytest.raises(PlatformError) as e:
        store.append_support_request(res_a, SupportInput(category="other", description="x"), "support-key-1")
    assert e.value.status == 409
    assert len(store.resident_home(res_a).support_requests) == 1
    assert store.resident_home(res_b).support_requests == []
    assert len(store.owner_snapshot(OWNER, "case_test").support_requests) == 1
    assert [e.type for e in store.events_after(res_a, 0)] == ["support.updated"]


def test_support_does_not_change_analysis_revision(store, world):
    _, _, res_a, _ = world
    before = store.owner_snapshot(OWNER, "case_test").case.analysis_revision
    store.append_support_request(res_a, SupportInput(**SUPPORT), "support-key-1")
    assert store.owner_snapshot(OWNER, "case_test").case.analysis_revision == before


def test_support_http_route(app, world):
    ha, _, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    r = phone.post("/api/resident/support", json=SUPPORT, headers={"Idempotency-Key": "support-key-1"})
    assert r.status_code == 200 and r.json()["category"] == "housing"


# ---------------------------------------------------------------- cross-site protection

def test_cross_site_state_change_is_rejected(app, world):
    ha, _, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    r = phone.post("/api/resident/reports", json=REPORT,
                   headers={"Idempotency-Key": "phone-key-1", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "cross_site_request"
    ok = phone.post("/api/resident/reports", json=REPORT,
                    headers={"Idempotency-Key": "phone-key-1", "Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 200


def test_allowed_origins_when_configured(app, world, monkeypatch):
    monkeypatch.setenv(router_mod.ALLOWED_ORIGINS_ENV, "http://localhost:5174, https://192.168.1.20:5175")
    c = TestClient(app)
    from tests.test_recovery_platform_api import SECRET

    bad = c.post("/api/recovery/session", json={"secret": SECRET}, headers={"Origin": "https://evil.example"})
    assert bad.status_code == 403
    good = c.post("/api/recovery/session", json={"secret": SECRET}, headers={"Origin": "http://localhost:5174"})
    assert good.status_code == 200


# ---------------------------------------------------------------- SSE

def frames(text: str) -> list[dict]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "data" in fields:
            out.append(fields)
    return out


async def collect(gen, n, timeout=5.0):
    items = []

    async def run():
        async for item in gen:
            items.append(item)
            if len(items) >= n:
                break

    await asyncio.wait_for(run(), timeout)
    await gen.aclose()
    return items


def test_owner_stream_replays_after_cursor_then_streams_new(store, world):
    _, _, res_a, _ = world
    token = store.create_owner_session("owner:local")
    cursor = store.owner_snapshot(OWNER, "case_test").event_cursor

    async def scenario():
        gen = router_mod.event_stream(store, token, "owner", cursor, "case_test", poll_seconds=0.01)
        first = asyncio.ensure_future(collect(gen, 1))
        await asyncio.sleep(0.05)
        store.append_report(res_a, report(), "key-0001")
        return await first

    items = asyncio.run(scenario())
    assert int(items[0]["id"]) > cursor
    assert json.loads(items[0]["data"])["type"] == "report.updated"


def test_resident_stream_is_filtered_and_resumes_without_duplicates(store, world):
    ha, _, res_a, res_b = world
    store.append_report(res_a, report(), "key-0001")
    store.append_report(res_b, report("B's report"), "key-0002")
    rev = store.owner_snapshot(OWNER, "case_test").case.case_revision
    token = store.exchange_invitation(store.create_invitation(OWNER, "case_test", ha, rev).invitation_token)

    items = asyncio.run(collect(router_mod.event_stream(store, token, "resident", 0, None, poll_seconds=0.01), 1))
    assert len(items) == 1
    event = json.loads(items[0]["data"])
    assert event["type"] == "report.updated"
    a_report = store.resident_home(res_a).reports[0].report_id
    assert event["entity_id"] == a_report
    # Resume after that id: nothing new for A (B's report is never delivered).
    resumed = router_mod.event_stream(store, token, "resident", int(items[0]["id"]), None, poll_seconds=0.01)

    async def nothing():
        try:
            await asyncio.wait_for(resumed.__anext__(), 0.2)
            return False
        except asyncio.TimeoutError:
            return True
        finally:
            await resumed.aclose()

    assert asyncio.run(nothing())


def test_stream_ends_after_delivering_revocation(store, world):
    ha, _, _, _ = world
    rev = store.owner_snapshot(OWNER, "case_test").case.case_revision
    token = store.exchange_invitation(store.create_invitation(OWNER, "case_test", ha, rev).invitation_token)
    cursor = store.owner_snapshot(OWNER, "case_test").event_cursor

    async def drain():
        return [i async for i in router_mod.event_stream(store, token, "resident", cursor, None, poll_seconds=0.01)]

    async def scenario():
        task = asyncio.ensure_future(asyncio.wait_for(drain(), 5))
        await asyncio.sleep(0.05)  # stream is open and polling
        store.revoke_invitation(OWNER, "case_test", store.invitations(OWNER, "case_test")[0]["invitation_id"])
        return await task

    items = asyncio.run(scenario())
    assert [json.loads(i["data"])["type"] for i in items] == ["session.revoked"]


def test_sse_routes_require_session_and_valid_cursor(app, world):
    anon = TestClient(app)
    assert anon.get("/api/resident/events").status_code == 401
    assert anon.get("/api/recovery/cases/case_test/events").status_code == 401
    owner = owner_client(app)
    assert owner.get("/api/recovery/cases/case_test/events?after=-3").status_code == 422
    assert owner.get("/api/recovery/cases/case_test/events", headers={"Last-Event-ID": "abc"}).status_code == 422
    assert owner.get("/api/recovery/cases/nope/events").status_code == 404
