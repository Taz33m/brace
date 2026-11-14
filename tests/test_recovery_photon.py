"""Private bridge isolation and durable retries; no Photon network calls."""
from datetime import datetime, timedelta, timezone
from base64 import b64decode
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recovery.photon import Acknowledgment, Inbound, PhotonService, build_photon_router
from backend.recovery.forecast_cards import FORECAST_CARDS, forecast_card
from backend.recovery.platform.auth import OWNER_SECRET_ENV
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.router import build_router
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input, seeded


BASE = "/api/recovery/photon"
WORKER = {"Authorization": "Bearer synthetic-worker-secret"}


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    now = [datetime(2026, 11, 14, tzinfo=timezone.utc)]
    store = CaseStore(tmp_path / "recovery.db", clock=lambda: now[0])
    households = seeded(store)
    store.create_case(OTHER_OWNER, case_input("foreign"))
    monkeypatch.setenv(OWNER_SECRET_ENV, "synthetic-owner-secret")
    monkeypatch.setenv("BRACE_PHOTON_BRIDGE_SECRET", "synthetic-worker-secret")
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", "https://brace.example")
    service = PhotonService(store)
    app = FastAPI()
    app.include_router(build_router(store, None))
    app.include_router(build_photon_router(store, service))
    owner = TestClient(app, headers={"Origin": "https://brace.example"})
    assert owner.post("/api/recovery/session", json={"secret": "synthetic-owner-secret"}).status_code == 200
    worker = TestClient(app, headers=WORKER)
    yield store, service, households, owner, worker, now
    owner.close(); worker.close()


def link(bridge, household=None):
    _, _, households, owner, _, _ = bridge
    response = owner.post(f"/api/recovery/cases/case_test/households/{household or households[0]}/photon-link")
    assert response.status_code == 200, response.text
    return response.json()


def inbound(bridge, text, *, message_id="message-1", sender="sender-a", space="private-a"):
    return bridge[4].post(BASE + "/inbound", json={"message_id": message_id, "sender_id": sender, "space_id": space, "text": text})


def join(bridge, **kwargs):
    invitation = link(bridge, kwargs.pop("household", None))
    response = inbound(bridge, invitation["join_message"], **kwargs)
    assert response.status_code == 200 and response.json()["kind"] == "joined", response.text
    return invitation, response.json()


def notice(bridge):
    return bridge[0].publish_preparation_notice(OWNER, "case_test", approval_key="approved-photon-notice",
        title="Exercise notice", body="Approved update; no work has been booked.", source_ids=[])


def test_forecast_card_poll_and_household_scoped_support(bridge):
    store, service, _, _, worker, _ = bridge
    join(bridge)
    published = notice(bridge)
    assert service.queue_notice("case_test", published["notice_id"],
        "Exercise notice", "Approved update; no work has been booked.", property_name="The Parker at Ellington",
        threat={"name": "Hurricane Beryl", "kind": "hurricane", "replay": True,
                "scenario_id": "beryl-2024", "step_id": "adv37",
                "forecast_issued": "2024-07-07T21:00:00Z",
                "at_this_site": {"peak_wind_mph": 55, "hours_until_tropical_storm_wind": 7.5}}) == 1
    alert, = worker.get(BASE + "/outbox").json()["items"]
    assert b64decode(alert["card_png"]) == FORECAST_CARDS["hurricane-beryl"].read_bytes()
    assert "Historical forecast replay" in alert["text"] and "7.5 hours" in alert["text"]
    assert worker.post(BASE + f"/outbox/{alert['id']}/ack",
                       json={"status": "sent", "provider_message_id": "alert-1"}).is_success
    choices, = worker.get(BASE + "/outbox").json()["items"]
    assert "I need help with access" in choices["choices"]
    assert worker.post(BASE + f"/outbox/{choices['id']}/ack",
                       json={"status": "sent", "provider_message_id": "poll-1"}).is_success
    vote = {"message_id": "vote-1", "sender_id": "sender-a", "space_id": "private-a",
            "text": "I need help with access", "poll_id": "poll-1", "option_id": "access-option"}
    assert worker.post(BASE + "/inbound", json={**vote, "sender_id": "stranger",
                                               "message_id": "foreign-vote"}).json()["kind"] == "ignored"
    assert worker.post(BASE + "/inbound", json=vote).json()["kind"] == "support"
    assert worker.post(BASE + "/inbound", json={**vote, "message_id": "vote-reselected"}).json()["reply"] is None
    snapshot = store.owner_snapshot(OWNER, "case_test")
    assert [record.category for record in snapshot.support_requests] == ["access"]


def test_forecast_art_is_scoped_to_the_matching_replays():
    threat = {"scenario_id": "la-red-flag-jan-2025", "step_id": "20250105T2240Z",
              "replay": True, "at_this_site": {"in_warning": True}}
    assert forecast_card("Pasadena Park Place", threat) == "los-angeles-red-flag"
    assert forecast_card("Pasadena Park Place", {**threat, "replay": False}) is None
    assert forecast_card("Pasadena Park Place", {**threat, "step_id": "another-issuance"}) is None


def test_one_use_join_uses_real_session_without_storing_raw_credentials(bridge):
    store, service, _, owner, _, _ = bridge
    invitation, first = join(bridge)
    retry = inbound(bridge, invitation["join_message"])
    assert retry.json() == {**first, "duplicate": True}
    used = inbound(bridge, invitation["join_message"], message_id="different", sender="stranger")
    assert used.json()["kind"] == "join_required"
    with service._db() as conn:
        record = dict(conn.execute("SELECT * FROM links").fetchone())
        assert len(record["code_hash"]) == 64 and len(record["session_hash"]) == 64
        assert invitation["join_code"] not in json.dumps(record)
        assert "token" not in " ".join(record)
    assert invitation["join_code"].encode() not in service.db_path.read_bytes()
    status = owner.get("/api/recovery/cases/case_test/photon").json()
    assert status["active_connections"] == 1
    assert "session_hash" not in json.dumps(status) and "sender-a" not in json.dumps(status)


@pytest.mark.parametrize("text,kind,category", [
    ("HELP I need housing because there is water in my home", "support", "housing"),
    ("Please help with access to the elevator", "support", "access"),
    ("The elevator is out, and I can’t manage the stairs.", "support", "access"),
    ("I need someone to call me", "support", "communication"),
    ("I need help with my medicine", "support", "other"),
    ("I see water in my kitchen", "report", "water"),
    ("Water under the balcony door", "report", "water"),
    ("Smoke coming in through my bedroom window", "report", "smoke_or_fire"),
    ("There is smoke in the hallway", "report", "smoke_or_fire"),
])
def test_inbound_uses_existing_household_scoped_workflows(bridge, text, kind, category):
    store, _, households, _, _, _ = bridge
    join(bridge)
    first = inbound(bridge, text, message_id="observation-1").json()
    assert first["kind"] == kind and first["request_id"]
    retry = inbound(bridge, text, message_id="observation-1").json()
    assert retry == {**first, "duplicate": True}
    home = store.resident_home(households[2])
    rows = home.support_requests if kind == "support" else home.reports
    assert len(rows) == 1 and rows[0].category == category
    other = store.resident_home(households[3])
    assert other.support_requests == [] and other.reports == []
    if kind == "report":
        assert rows[0].status == "reported" and rows[0].location is None
        assert "logged your report for the property team" in first["reply"]
        assert ("call 911" in first["reply"]) == (category == "smoke_or_fire")


def test_unknown_sender_and_ambiguous_text_never_create_reports(bridge):
    assert inbound(bridge, "I see water in my kitchen").json()["kind"] == "join_required"
    join(bridge, message_id="join-2")
    for i, text in enumerate(("What if there is water?", "There is no smoke", "Hello", "Water")):
        assert inbound(bridge, text, message_id=f"unclear-{i}").json()["kind"] == "clarify"
    assert inbound(bridge, "HELP housing", message_id="wrong-space", space="public-other").json()["kind"] == "join_required"
    home = bridge[0].resident_home(bridge[2][2])
    assert home.reports == [] and home.support_requests == []


def test_expired_code_and_revoked_household_bindings_fail_closed(bridge):
    store, service, households, _, _, now = bridge
    code = link(bridge)
    now[0] += timedelta(minutes=11)
    assert inbound(bridge, code["join_message"]).json()["kind"] == "join_required"
    join(bridge, message_id="fresh-join")
    published = notice(bridge)
    assert service.queue_notice("case_test", published["notice_id"], "Exercise notice", "Approved update; no work has been booked.") == 1
    revision = store.owner_snapshot(OWNER, "case_test").case.case_revision
    store.revoke_household_access(OWNER, "case_test", households[0], {"expected_revision": revision}, "revoke-photon-access")
    assert inbound(bridge, "HELP housing", message_id="after-revoke").json()["kind"] == "join_required"
    assert service.claim_outbox() == {"items": []}
    assert service.status(OWNER, "case_test")["delivery"] == {"cancelled": 1}


def test_outbox_is_claimed_once_and_sent_means_provider_accepted(bridge):
    _, service, _, _, worker, _ = bridge
    join(bridge)
    published = notice(bridge)
    args = ("case_test", published["notice_id"], "Exercise notice", "Approved update; no work has been booked.")
    assert service.queue_notice(*args) == 1 and service.queue_notice(*args) == 0
    items = worker.get(BASE + "/outbox").json()["items"]
    assert len(items) == 1 and items[0]["space_id"] == "private-a"
    assert worker.get(BASE + "/outbox").json() == {"items": []}
    restarted = PhotonService(bridge[0])
    assert restarted.claim_outbox() == {"items": []}
    ack = worker.post(BASE + "/outbox/" + items[0]["id"] + "/ack", json={"status": "sent", "provider_message_id": "provider-1"})
    assert ack.status_code == 200 and ack.json()["status"] == "provider_accepted"
    assert worker.post(BASE + "/outbox/" + items[0]["id"] + "/ack", json={"status": "sent"}).json()["duplicate"]
    assert service.status(OWNER, "case_test")["delivery"] == {"provider_accepted": 1}


def test_failed_or_uncertain_delivery_does_not_resend(bridge):
    join(bridge)
    published = notice(bridge)
    service = bridge[1]
    service.queue_notice("case_test", published["notice_id"], "Exercise notice", "Approved update; no work has been booked.")
    item = service.claim_outbox()["items"][0]
    result = service.acknowledge(item["id"], Acknowledgment(status="failed", error="sensitive-provider-detail"))
    assert result["status"] == "failed" and service.claim_outbox() == {"items": []}
    assert b"sensitive-provider-detail" not in service.db_path.read_bytes()


def test_rebinding_same_channel_cannot_release_previous_household_notice(bridge):
    join(bridge)
    published = notice(bridge)
    service = bridge[1]
    service.queue_notice("case_test", published["notice_id"], "Exercise notice", "Approved update; no work has been booked.")
    join(bridge, household=bridge[2][1], message_id="new-household")
    assert service.claim_outbox() == {"items": []}


def test_worker_and_owner_auth_are_distinct_and_case_scoped(bridge):
    store, _, households, owner, worker, _ = bridge
    assert owner.post(BASE + "/inbound", json={"message_id": "1", "sender_id": "a", "space_id": "b", "text": "HELP"}).status_code == 401
    assert owner.get(BASE + "/outbox").status_code == 401
    assert worker.post(f"/api/recovery/cases/case_test/households/{households[0]}/photon-link").status_code == 401
    assert owner.get("/api/recovery/cases/foreign/photon").status_code == 404
    assert owner.post(f"/api/recovery/cases/foreign/households/{households[0]}/photon-link").status_code == 404
    assert owner.post("/api/recovery/cases/case_test/households/missing/photon-link").status_code == 404
    assert owner.post(f"/api/recovery/cases/case_test/households/{households[0]}/photon-link", headers={"Origin": "https://evil.example"}).status_code == 403


def test_provider_id_conflicts_and_cross_database_retry_does_not_duplicate_submission(bridge, monkeypatch):
    store, service, households, _, _, _ = bridge
    join(bridge)
    message = Inbound(message_id="crash-window", sender_id="sender-a", space_id="private-a", text="HELP housing")
    original = service._receive
    def crash_after_case_write(conn, incoming):
        original(conn, incoming)
        raise RuntimeError("Synthetic bridge receipt failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "_receive", crash_after_case_write)
        with pytest.raises(RuntimeError):
            service.inbound(message)
    result = service.inbound(message)
    assert result["kind"] == "support" and len(store.resident_home(households[2]).support_requests) == 1
    assert PhotonService(store).inbound(message)["duplicate"] is True
    assert inbound(bridge, "Different", message_id="crash-window").status_code == 409


def test_support_update_queue_is_household_scoped_and_deduplicated(bridge):
    store, service, households, _, _, _ = bridge
    join(bridge)
    join(bridge, household=households[1], message_id="join-b", sender="sender-b", space="private-b")
    inbound(bridge, "HELP housing", message_id="help-a")
    event = [row for row in store.events_after(households[2], 0) if row.type == "support.updated"][-1]
    assert service.queue_household_update("case_test", households[0], event.event_id, "The property team is reviewing your request.") == 1
    assert service.queue_household_update("case_test", households[0], event.event_id, "The property team is reviewing your request.") == 0
    assert [row["space_id"] for row in service.claim_outbox()["items"]] == ["private-a"]
    with pytest.raises(PlatformError) as error:
        service.queue_household_update("case_test", households[1], event.event_id, "Not yours")
    assert error.value.status == 404
