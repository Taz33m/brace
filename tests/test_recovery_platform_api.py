"""HTTP surface of the platform router, mounted on a test-only FastAPI app."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.recovery.platform import auth
from backend.recovery.platform.router import build_router, make_owner_dependency
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, seeded

SECRET = "test-owner-secret-not-real"
REPORT = {"category": "water", "text": "Water under the sink", "selected_location_id": None,
          "location_description": "kitchen", "observed_at": None, "upload_ids": []}


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


@pytest.fixture
def app(store, monkeypatch):
    monkeypatch.setenv(auth.OWNER_SECRET_ENV, SECRET)
    app = FastAPI()
    app.include_router(build_router(store, None))

    @app.get("/api/legacy", dependencies=[Depends(make_owner_dependency(store))])
    def legacy():
        return {"ok": True}

    return app


@pytest.fixture
def world(store):
    return seeded(store)


def owner_client(app) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/recovery/session", json={"secret": SECRET})
    assert r.status_code == 200, r.text
    return c


def invite(owner: TestClient, household_id: str) -> str:
    rev = owner.get("/api/recovery/cases/case_test").json()["case"]["case_revision"]
    r = owner.post("/api/recovery/cases/case_test/commands",
                   json={"type": "create_invitation", "household_id": household_id, "expected_revision": rev})
    assert r.status_code == 200, r.text
    return r.json()["invitation_token"]


def resident_client(app, token: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/resident/session", json={"invitation_token": token})
    assert r.status_code == 200 and r.json() == {"ok": True}
    return c


def test_phone_report_reaches_owner(app, world):
    ha, _, _, _ = world
    owner = owner_client(app)
    assert [c["case_id"] for c in owner.get("/api/recovery/cases").json()["cases"]] == ["case_test"]
    phone = resident_client(app, invite(owner, ha))
    home = phone.get("/api/resident/home").json()
    assert home["unit_label"] == "A" and home["reports"] == []
    r = phone.post("/api/resident/reports", json=REPORT, headers={"Idempotency-Key": "phone-key-1"})
    assert r.status_code == 200, r.text
    receipt = r.json()
    assert receipt["duplicate"] is False and receipt["report"]["household_id"] == ha
    retry = phone.post("/api/resident/reports", json=REPORT, headers={"Idempotency-Key": "phone-key-1"})
    assert retry.json()["duplicate"] is True
    view = owner.get("/api/recovery/cases/case_test").json()
    assert [r["report_id"] for r in view["reports"]] == [receipt["report"]["report_id"]]
    assert view["case"]["pending_reports"] == 1


def test_session_cookies_are_httponly_strict_and_scoped(app, world):
    ha, _, _, _ = world
    c = TestClient(app)
    r = c.post("/api/recovery/session", json={"secret": SECRET})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api" in cookie
    token = invite(c, ha)
    r = TestClient(app).post("/api/resident/session", json={"invitation_token": token})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert token not in r.text


def test_routes_require_sessions(app, world):
    anon = TestClient(app)
    for method, path in (("get", "/api/recovery/cases"), ("get", "/api/recovery/cases/case_test"),
                         ("get", "/api/resident/home"), ("get", "/api/legacy")):
        r = getattr(anon, method)(path)
        assert r.status_code == 401, path
    r = anon.post("/api/resident/reports", json=REPORT, headers={"Idempotency-Key": "phone-key-1"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


def test_resident_session_cannot_use_owner_routes(app, world):
    ha, _, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    assert phone.get("/api/recovery/cases").status_code == 401
    assert phone.get("/api/recovery/cases/case_test").status_code == 401
    assert phone.get("/api/legacy").status_code == 401


def test_owner_login_wrong_secret_and_disabled(app, monkeypatch):
    r = TestClient(app).post("/api/recovery/session", json={"secret": "nope"})
    assert r.status_code == 401 and "set-cookie" not in r.headers
    monkeypatch.delenv(auth.OWNER_SECRET_ENV)
    r = TestClient(app).post("/api/recovery/session", json={"secret": SECRET})
    assert r.status_code == 503 and r.json()["error"]["code"] == "owner_login_disabled"


def test_bad_invitation_token_is_401(app, world):
    r = TestClient(app).post("/api/resident/session", json={"invitation_token": "made-up"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invitation_invalid"


def test_report_body_cannot_claim_household(app, world):
    ha, hb, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    r = phone.post("/api/resident/reports", json={**REPORT, "household_id": hb},
                   headers={"Idempotency-Key": "phone-key-1"})
    assert r.status_code == 422
    body = r.json()
    assert set(body["error"]) == {"code", "message", "retryable", "current_revision"}
    assert "Traceback" not in r.text


def test_resident_b_does_not_see_resident_a_report(app, world):
    ha, hb, _, _ = world
    owner = owner_client(app)
    a = resident_client(app, invite(owner, ha))
    b = resident_client(app, invite(owner, hb))
    a.post("/api/resident/reports", json=REPORT, headers={"Idempotency-Key": "phone-key-1"})
    assert b.get("/api/resident/home").json()["reports"] == []


def test_stale_owner_command_is_409_with_current_revision(app, world):
    ha, _, _, _ = world
    owner = owner_client(app)
    r = owner.post("/api/recovery/cases/case_test/commands",
                   json={"type": "create_invitation", "household_id": ha, "expected_revision": 1})
    assert r.status_code == 409
    assert r.json()["error"] == {"code": "revision_conflict", "retryable": True, "current_revision": 3,
                                 "message": "This case changed. Reload before applying this edit."}


def test_revoked_invitation_ends_phone_session(app, store, world):
    ha, _, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    store.revoke_invitation(OWNER, "case_test", store.invitations(OWNER, "case_test")[0]["invitation_id"])
    r = phone.get("/api/resident/home")
    assert r.status_code == 401


def test_responses_are_not_cached(app, world):
    owner = owner_client(app)
    assert owner.get("/api/recovery/cases").headers["cache-control"] == "no-store"
