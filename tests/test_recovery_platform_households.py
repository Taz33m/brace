"""Owner household onboarding stays unconfirmed, scoped, and safe to retry."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.recovery.platform.router import build_router
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OTHER_OWNER, case_input, seeded


SECRET = "synthetic-household-owner-secret"
ORIGIN = "https://owner.example"
CASE = "/api/recovery/cases/case_test"
TARGET = CASE + "/households"


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "households.sqlite3", tmp_path / "media")


@pytest.fixture
def app(store, monkeypatch):
    monkeypatch.setenv("BRACE_OWNER_SECRET", SECRET)
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", ORIGIN)
    seeded(store)
    app = FastAPI()
    app.include_router(build_router(store))
    return app


@pytest.fixture
def owner(app):
    with TestClient(app, headers={"Origin": ORIGIN}) as client:
        assert client.post("/api/recovery/session", json={"secret": SECRET}).status_code == 200
        yield client


def snapshot(owner):
    response = owner.get(CASE)
    assert response.status_code == 200
    return response.json()


def create(owner, body, key="household-create-1", path=TARGET):
    headers = {} if key is None else {"Idempotency-Key": key}
    return owner.post(path, json=body, headers=headers)


def test_owner_creation_retry_invitation_and_resident_home(app, owner):
    before = snapshot(owner)
    body = {"expected_revision": before["case"]["case_revision"], "unit_label": "  Unit C  "}
    first = create(owner, body)
    assert first.status_code == 201, first.text
    receipt = first.json()
    assert receipt["case_id"] == "case_test"
    assert receipt["duplicate"] is False
    assert receipt["household"]["unit_label"] == "Unit C"
    assert receipt["household"]["unit_confirmed"] is False
    assert receipt["case_revision"] == before["case"]["case_revision"] + 1
    assert receipt["analysis_revision"] == before["case"]["analysis_revision"]
    household_id = receipt["household"]["household_id"]
    after = snapshot(owner)
    assert len(after["household_labels"]) == len(before["household_labels"]) + 1
    assert after["events"][-1]["type"] == "household.added"
    assert after["events"][-1]["entity_id"] == household_id

    replay = create(owner, body)
    assert replay.status_code == 201, replay.text
    assert replay.json() == {**receipt, "duplicate": True}
    assert snapshot(owner) == after, "A retry must not add another household, revision, or event"

    invitation = owner.post(CASE + "/commands", json={
        "type": "create_invitation", "expected_revision": receipt["case_revision"],
        "household_id": household_id,
    }, headers={"Idempotency-Key": "household-invitation-1"})
    assert invitation.status_code == 200, invitation.text
    token = invitation.json()["invitation_token"]
    assert token
    with TestClient(app, headers={"Origin": ORIGIN}) as resident:
        exchanged = resident.post("/api/resident/session", json={"invitation_token": token})
        assert exchanged.status_code == 200
        home = resident.get("/api/resident/home")
        assert home.status_code == 200
        assert home.json()["unit_label"] == "Unit C"
        assert home.json()["unit_confirmed"] is False
        assert home.json()["selectable_locations"] == []
        assert home.json()["reports"] == []
        assert home.json()["support_requests"] == []
        assert token not in home.text


def test_changed_body_and_stale_revision_do_not_add_households(owner):
    before = snapshot(owner)
    body = {"expected_revision": before["case"]["case_revision"], "unit_label": "C"}
    assert create(owner, body).status_code == 201
    after = snapshot(owner)
    changed = create(owner, {**body, "unit_label": "D"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"
    stale = create(owner, body, key="different-household-key")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "revision_conflict"
    assert stale.json()["error"]["current_revision"] == after["case"]["case_revision"]
    assert snapshot(owner) == after


def test_foreign_case_is_hidden_from_owner(owner, store):
    store.create_case(OTHER_OWNER, case_input("foreign-case"))
    foreign_before = store.owner_snapshot(OTHER_OWNER, "foreign-case")
    response = create(owner, {"expected_revision": 1, "unit_label": "C"},
                      path="/api/recovery/cases/foreign-case/households")
    assert response.status_code == 404
    assert store.owner_snapshot(OTHER_OWNER, "foreign-case") == foreign_before


def test_anonymous_and_resident_sessions_cannot_create_households(app, owner):
    before = snapshot(owner)
    body = {"expected_revision": before["case"]["case_revision"], "unit_label": "C"}
    with TestClient(app, headers={"Origin": ORIGIN}) as anonymous:
        assert create(anonymous, body).status_code == 401
    household_id = before["household_labels"][0]["household_id"]
    invitation = owner.post(CASE + "/commands", json={
        "type": "create_invitation", "expected_revision": body["expected_revision"],
        "household_id": household_id,
    }, headers={"Idempotency-Key": "existing-household-invitation"})
    assert invitation.status_code == 200
    after_invitation = snapshot(owner)
    with TestClient(app, headers={"Origin": ORIGIN}) as resident:
        assert resident.post("/api/resident/session", json={
            "invitation_token": invitation.json()["invitation_token"],
        }).status_code == 200
        body["expected_revision"] = after_invitation["case"]["case_revision"]
        assert create(resident, body).status_code == 401
    assert snapshot(owner) == after_invitation


@pytest.mark.parametrize("extra", [{"unit_confirmed": True}, {"location_ids": ["loc_kitchen_a"]}])
def test_creation_cannot_assert_a_verified_unit_or_locations(owner, extra):
    before = snapshot(owner)
    response = create(owner, {"expected_revision": before["case"]["case_revision"], "unit_label": "C", **extra})
    assert response.status_code == 422
    assert snapshot(owner) == before


@pytest.mark.parametrize("revision", [True, "3", 3.0, 0, -1])
def test_revision_must_be_a_positive_strict_integer(owner, revision):
    before = snapshot(owner)
    response = create(owner, {"expected_revision": revision, "unit_label": "C"})
    assert response.status_code == 422
    assert snapshot(owner) == before


@pytest.mark.parametrize("label", [None, "   "])
def test_nullable_and_blank_labels_are_unconfirmed(owner, label):
    before = snapshot(owner)
    response = create(owner, {"expected_revision": before["case"]["case_revision"], "unit_label": label})
    assert response.status_code == 201
    assert response.json()["household"]["unit_label"] is None
    assert response.json()["household"]["unit_confirmed"] is False


@pytest.mark.parametrize("label", ["x" * 121, "A\nB"])
def test_labels_must_be_short_and_single_line(owner, label):
    before = snapshot(owner)
    response = create(owner, {"expected_revision": before["case"]["case_revision"], "unit_label": label})
    assert response.status_code == 422
    assert snapshot(owner) == before


@pytest.mark.parametrize("key", [None, "short", "x" * 201])
def test_idempotency_header_is_required_and_bounded(owner, key):
    before = snapshot(owner)
    response = create(owner, {"expected_revision": before["case"]["case_revision"], "unit_label": "C"}, key=key)
    assert response.status_code == 422
    assert snapshot(owner) == before


def test_foreign_origin_cannot_create_a_household(owner):
    before = snapshot(owner)
    response = owner.post(TARGET, json={"expected_revision": before["case"]["case_revision"], "unit_label": "C"},
                          headers={"Origin": "https://foreign.example", "Idempotency-Key": "foreign-origin-key"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_site_request"
    assert snapshot(owner) == before


def test_receipt_failure_rolls_back_household_revision_and_event(owner, store, monkeypatch):
    before = snapshot(owner)
    body = {"expected_revision": before["case"]["case_revision"], "unit_label": "C"}
    remember = store._remember

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("synthetic receipt write failure")

    monkeypatch.setattr(store, "_remember", fail_receipt)
    with pytest.raises(RuntimeError, match="synthetic receipt write failure"):
        create(owner, body)
    assert snapshot(owner) == before, "Failed receipt must not leave an orphan household or event"
    monkeypatch.setattr(store, "_remember", remember)
    retry = create(owner, body)
    assert retry.status_code == 201
    assert retry.json()["duplicate"] is False
    assert retry.json()["case_revision"] == before["case"]["case_revision"] + 1
    assert len(snapshot(owner)["household_labels"]) == len(before["household_labels"]) + 1
