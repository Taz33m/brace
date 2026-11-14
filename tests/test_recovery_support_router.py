"""Resident support reaches an owner and returns a scoped, explicit status update."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recovery.platform.auth import Actor
from backend.recovery.platform.models import SupportInput
from backend.recovery.platform.router import build_router, make_owner_dependency
from backend.recovery.platform.store import CaseStore
from backend.recovery.support_router import build_support_router
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input, seeded


def test_support_lifecycle_is_atomic_idempotent_and_household_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACE_OWNER_SECRET", "synthetic-support-test-secret")
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", "https://owner.example")
    store = CaseStore(tmp_path / "cases.sqlite3")
    household_a, _, resident_a, resident_b = seeded(store)
    submitted = store.append_support_request(resident_a, SupportInput(category="housing", description="Synthetic temporary housing request"), "support-submit-1")
    store.create_case(OTHER_OWNER, case_input("foreign-case"))
    app = FastAPI()
    app.include_router(build_router(store))
    app.include_router(build_support_router(store, make_owner_dependency(store)))
    base = "/api/recovery/cases/case_test/support-requests"
    target = f"{base}/{submitted.request_id}/respond"
    with TestClient(app, headers={"Origin": "https://owner.example"}) as owner:
        assert owner.post("/api/recovery/session", json={"secret": "synthetic-support-test-secret"}).status_code == 200
        before = owner.get(base).json()
        assert before["requests"][0]["status"] == "received"
        body = {"expected_revision": before["case_revision"], "status": "under_review",
                "public_status_detail": "We are reviewing your housing request. Please check this portal for our response."}
        response = owner.post(target, json=body, headers={"Idempotency-Key": "support-review-1"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["analysis_revision"] == before["analysis_revision"]
        assert result["case_revision"] == before["case_revision"] + 1
        assert result["request"]["household_id"] == household_a
        assert result["request"]["public_status_detail"] == body["public_status_detail"]
        cursor = store.resident_home(resident_a).event_cursor
        retry = owner.post(target, json=body, headers={"Idempotency-Key": "support-review-1"})
        assert retry.status_code == 200 and retry.json()["duplicate"]
        assert store.resident_home(resident_a).event_cursor == cursor
        assert owner.post(target, json={**body, "public_status_detail": "Changed text"}, headers={"Idempotency-Key": "support-review-1"}).status_code == 409
        assert owner.post(target, json=body, headers={"Idempotency-Key": "stale-support-new-key"}).status_code == 409
        for status, detail in (("responded", "Please contact the property office to review the available housing options."),
                               ("closed", "This request is closed after our review. You can submit another request if your needs change."),
                               ("under_review", "Your request has been reopened for another review.")):
            current = owner.get(base).json()
            reply = owner.post(target, json={"expected_revision": current["case_revision"], "status": status,
                               "public_status_detail": detail}, headers={"Idempotency-Key": f"support-state-{status}"})
            assert reply.status_code == 200, reply.text
            assert store.resident_home(resident_a).support_requests[0].public_status_detail == detail
            assert store.resident_home(resident_a).support_requests[0].status == status
            assert store.resident_home(resident_b).support_requests == []
            assert reply.json()["analysis_revision"] == before["analysis_revision"]
        assert store.events_after(resident_b, 0) == []
        assert {event.type for event in store.events_after(resident_a, 0)} == {"support.updated"}
        assert owner.get("/api/recovery/cases/foreign-case/support-requests").status_code == 404
        current = owner.get(base).json()
        assert owner.post(target, json={"expected_revision": current["case_revision"], "status": "responded", "public_status_detail": " "},
                          headers={"Idempotency-Key": "blank-response-key"}).status_code == 422
        assert owner.post(target, json={"expected_revision": current["case_revision"], "status": "responded", "public_status_detail": "An update."},
                          headers={"Idempotency-Key": "foreign-origin-key", "Origin": "https://other.example"}).status_code == 403
        assert owner.get(base).headers["cache-control"] == "private, no-store"
        invitation = store.create_invitation(OWNER, "case_test", household_a, current["case_revision"])
        guest = TestClient(app)
        try:
            assert guest.post("/api/resident/session", json={"invitation_token": invitation.invitation_token}).status_code == 200
            assert guest.get(base).status_code == 401
            assert guest.post(target, json=body, headers={"Idempotency-Key": "resident-edit-key"}).status_code == 401
        finally:
            guest.close()
    reopened = CaseStore(tmp_path / "cases.sqlite3")
    assert reopened.resident_home(resident_a).support_requests[0].status == "under_review"
    assert reopened.resident_home(resident_a).support_requests[0].public_status_detail == "Your request has been reopened for another review."
