"""Owner household access: scoped listing, atomic revocation, retry and restoration."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
import threading

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.recovery.platform.errors import PlatformError
from tests.test_recovery_platform_households import app, owner, store, snapshot, CASE, ORIGIN  # noqa: F401
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input


ACCESS = CASE + "/households/access"


def invitation(owner, household_id):
    response = owner.post(CASE + "/commands", json={"type": "create_invitation", "household_id": household_id,
        "expected_revision": snapshot(owner)["case"]["case_revision"]})
    assert response.status_code == 200, response.text
    return response.json()["invitation_token"]


def phone(app, token):
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert client.post("/api/resident/session", json={"invitation_token": token}).status_code == 200
    return client


def revoke(client, household_id, expected_revision, key="revoke-household-key", case=CASE):
    return client.post(case + f"/households/{household_id}/revoke-access", json={"expected_revision": expected_revision},
                       headers={"Idempotency-Key": key})


def test_access_listing_revoke_retry_preserves_data_and_new_invitation_restores_access(app, owner, store):
    household, other = [row["household_id"] for row in snapshot(owner)["household_labels"]]
    first_link, second_link, other_link = invitation(owner, household), invitation(owner, household), invitation(owner, other)
    first, second, unaffected = phone(app, first_link), phone(app, second_link), phone(app, other_link)
    image = BytesIO()
    Image.new("RGB", (8, 8)).save(image, "PNG")
    upload = first.post("/api/resident/uploads", files={"file": ("test.png", image.getvalue(), "image/png")},
                        headers={"Idempotency-Key": "access-upload-key"})
    assert upload.status_code == 200
    report = first.post("/api/resident/reports", json={"category": "water", "text": "Water under sink",
        "selected_location_id": None, "location_description": None, "observed_at": None,
        "upload_ids": [upload.json()["upload_id"]]}, headers={"Idempotency-Key": "access-report-key"})
    assert report.status_code == 200
    assert first.post("/api/resident/support", json={"category": "housing", "description": "Need a place to stay"},
                      headers={"Idempotency-Key": "access-support-key"}).status_code == 200
    before = snapshot(owner)
    listing = owner.get(ACCESS)
    assert listing.status_code == 200 and listing.headers["cache-control"] == "no-store"
    households = {row["household_id"]: row for row in listing.json()["households"]}
    assert households[household]["active_session_count"] == households[household]["active_invitation_count"] == 2
    assert households[other]["active_session_count"] == 1
    assert set(households[household]["invitations"][0]) == {"invitation_id", "created_at", "expires_at", "revoked_at"}
    assert all(secret not in listing.text for secret in (first_link, second_link, other_link, "token_hash", "session_hash"))

    result = revoke(owner, household, before["case"]["case_revision"])
    assert result.status_code == 200, result.text
    receipt = result.json()
    assert receipt == {"case_id": "case_test", "household_id": household,
        "case_revision": before["case"]["case_revision"] + 1, "analysis_revision": before["case"]["analysis_revision"],
        "revoked_invitation_count": 2, "revoked_session_count": 2, "duplicate": False}
    after = snapshot(owner)
    for field in ("reports", "evidence", "support_requests", "household_labels"):
        assert after[field] == before[field]
    assert [event["type"] for event in after["events"][-2:]] == ["household.access_revoked", "session.revoked"]
    assert first.get("/api/resident/home").status_code == second.get("/api/resident/home").status_code == 401
    assert unaffected.get("/api/resident/home").status_code == 200
    assert not any(event.type == "session.revoked" for event in store.events_after(store.resolve_session(
        unaffected.cookies.get("brace_resident_session")), 0))
    for token in (first_link, second_link):
        assert TestClient(app).post("/api/resident/session", json={"invitation_token": token}).status_code == 401
    replay = revoke(owner, household, before["case"]["case_revision"])
    assert replay.status_code == 200 and replay.json() == {**receipt, "duplicate": True}
    assert snapshot(owner) == after
    revoked = next(row for row in owner.get(ACCESS).json()["households"] if row["household_id"] == household)
    assert revoked["active_session_count"] == revoked["active_invitation_count"] == 0
    assert all(link["revoked_at"] for link in revoked["invitations"])
    restored = phone(app, invitation(owner, household))
    assert restored.get("/api/resident/home").json()["reports"][0]["report_id"] == report.json()["report"]["report_id"]
    restored_snapshot = snapshot(owner)
    assert revoke(owner, household, before["case"]["case_revision"]).json() == {**receipt, "duplicate": True}
    assert snapshot(owner) == restored_snapshot and restored.get("/api/resident/home").status_code == 200


def test_access_auth_case_scope_stale_revision_and_required_key(app, owner, store):
    household = snapshot(owner)["household_labels"][0]["household_id"]
    resident = phone(app, invitation(owner, household))
    before = snapshot(owner)
    revision = before["case"]["case_revision"]
    for client in (TestClient(app), resident):
        assert client.get(ACCESS).status_code == 401
        assert revoke(client, household, revision).status_code == 401
    store.create_case(OTHER_OWNER, case_input("other_case"))
    foreign = store.add_household(OTHER_OWNER, "other_case", "Other")
    other_path = "/api/recovery/cases/other_case"
    assert owner.get(other_path + "/households/access").status_code == 404
    assert revoke(owner, foreign, 2, case=other_path).status_code == 404
    assert revoke(owner, foreign, revision).status_code == 404
    stale = revoke(owner, household, revision - 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    path = CASE + f"/households/{household}/revoke-access"
    assert owner.post(path, json={"expected_revision": revision}).status_code == 422
    assert owner.post(path, json={"expected_revision": revision}, headers={
        "Origin": "https://foreign.example", "Idempotency-Key": "cross-origin-key"}).status_code == 403
    assert snapshot(owner) == before
    assert resident.get("/api/resident/home").status_code == 200


def test_listing_uses_server_clock_and_keeps_sessions_after_link_expiry(app, owner, store):
    household = snapshot(owner)["household_labels"][0]["household_id"]
    resident = phone(app, invitation(owner, household))
    instant = store.clock()
    store.clock = lambda: instant + timedelta(days=4)
    # The owner HTTP cookie is older now, so inspect with the already-authorized
    # owner identity to exercise the exact server-side count logic.
    listing = store.household_access(OWNER, "case_test")
    access = next(row for row in listing.households if row.household_id == household)
    assert access.active_invitation_count == 0 and access.active_session_count == 1
    assert store.resolve_session(resident.cookies.get("brace_resident_session")) is not None
    result = store.revoke_household_access(OWNER, "case_test", household,
        {"expected_revision": listing.case_revision}, "revoke-expired-links")
    assert result.revoked_invitation_count == result.revoked_session_count == 1


def test_failed_revoke_receipt_rolls_back_links_sessions_revision_and_events(app, owner, store, monkeypatch):
    household = snapshot(owner)["household_labels"][0]["household_id"]
    resident = phone(app, invitation(owner, household))
    before = snapshot(owner)
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic receipt failure")
    monkeypatch.setattr(store, "_remember", fail)
    with pytest.raises(RuntimeError, match="synthetic receipt failure"):
        revoke(owner, household, before["case"]["case_revision"])
    assert snapshot(owner) == before
    assert resident.get("/api/resident/home").status_code == 200
    assert all(row["revoked_at"] is None for row in store.invitations(OWNER, "case_test"))


def test_invitation_creation_and_household_revocation_serialize_at_one_revision(app, owner, store):
    household = snapshot(owner)["household_labels"][0]["household_id"]
    token = invitation(owner, household)
    resident = store.exchange_invitation(token)
    revision = snapshot(owner)["case"]["case_revision"]
    barrier = threading.Barrier(2)
    def run(which):
        barrier.wait()
        try:
            if which == "invite":
                result = store.create_invitation(OWNER, "case_test", household, revision)
            else:
                result = store.revoke_household_access(OWNER, "case_test", household,
                    {"expected_revision": revision}, "concurrent-revoke-key")
            return which, result
        except PlatformError as error:
            assert error.code == "revision_conflict"
            return which, None
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = dict(pool.map(run, ["invite", "revoke"]))
    assert sum(value is not None for value in outcomes.values()) == 1
    assert snapshot(owner)["case"]["case_revision"] == revision + 1
    assert (store.resolve_session(resident) is None) is (outcomes["revoke"] is not None)
