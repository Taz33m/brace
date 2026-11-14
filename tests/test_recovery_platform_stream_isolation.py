"""Regressions for stream revocation and household-filtered cursor pagination."""
from __future__ import annotations

import asyncio
import json

from backend.recovery.platform.router import event_stream
from tests.test_recovery_platform_api import store, world  # noqa: F401 (fixtures)
from tests.test_recovery_platform_support import OWNER, report


def _session(store, household_id):
    revision = store.owner_snapshot(OWNER, "case_test").case.case_revision
    invitation = store.create_invitation(OWNER, "case_test", household_id, revision)
    return store.exchange_invitation(invitation.invitation_token)


def _revoke(store):
    store.revoke_invitation(OWNER, "case_test", store.invitations(OWNER, "case_test")[0]["invitation_id"])


def test_other_household_events_cannot_starve_a_resident_cursor(store, world):
    _, other_household, resident, _ = world
    cursor = store.owner_snapshot(OWNER, "case_test").event_cursor
    with store._write() as conn:
        for number in range(501):
            store._event(conn, "case_test", "report.updated", audience="households",
                         households=[other_household], entity_id=f"other-{number}")
    receipt = store.append_report(resident, report(), "own-after-foreign-events")
    events = store.events_after(resident, cursor)
    assert len(events) == 1
    assert events[0].entity_id == receipt.report.report_id
    assert store.events_after(resident, events[0].event_id) == []


def test_revocation_during_database_read_prevents_private_delivery(store, world, monkeypatch):
    household, _, resident, _ = world
    token = _session(store, household)
    store.append_report(resident, report("Private report created before revocation"), "before-revoke-report")
    original = store.events_after
    revoked = False

    def revoke_during_read(*args, **kwargs):
        nonlocal revoked
        events = original(*args, **kwargs)
        if not revoked:
            revoked = True
            _revoke(store)
            store.append_report(resident, report("Private report after revocation"), "after-revoke-report")
        return events

    monkeypatch.setattr(store, "events_after", revoke_during_read)

    async def drain():
        return [event async for event in event_stream(store, token, "resident", 0, None, poll_seconds=.001)]

    frames = asyncio.run(drain())
    assert [json.loads(frame["data"])["type"] for frame in frames] == ["session.revoked"]
    assert all("Private report" not in frame["data"] for frame in frames)


def test_revocation_while_consuming_batch_stops_later_frames(store, world):
    household, _, resident, _ = world
    token = _session(store, household)
    first = store.append_report(resident, report("First report"), "first-report-key")
    second = store.append_report(resident, report("Must not be delivered"), "second-report-key")

    async def scenario():
        stream = event_stream(store, token, "resident", 0, None, poll_seconds=.001)
        initial = await stream.__anext__()
        _revoke(store)
        remaining = [event async for event in stream]
        return initial, remaining

    initial, remaining = asyncio.run(scenario())
    assert json.loads(initial["data"])["entity_id"] == first.report.report_id
    assert [json.loads(frame["data"])["type"] for frame in remaining] == ["session.revoked"]
    assert all(json.loads(frame["data"])["entity_id"] != second.report.report_id for frame in remaining)


def test_already_revoked_session_does_not_read_events(store, world, monkeypatch):
    household, _, _, _ = world
    token = _session(store, household)
    _revoke(store)

    def forbidden_read(*args, **kwargs):
        raise AssertionError("An initially invalid session cannot read an event batch")

    monkeypatch.setattr(store, "events_after", forbidden_read)

    async def drain():
        return [event async for event in event_stream(store, token, "resident", 0, None, poll_seconds=.001)]

    assert asyncio.run(drain()) == []
