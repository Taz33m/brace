"""HTTP preparation approval publishes the exact corrected preview to its bound case."""
from copy import deepcopy
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.preparation_notices import correct_plan_notices
from backend.recovery.platform import auth
from backend.recovery.platform.models import CaseInput
from backend.recovery.platform.router import build_router
from backend.recovery.platform.store import CaseStore
from backend.recovery.preparation_approval import approve_notice
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input


PATH = "/api/test/preparation/approve"
ORIGIN = "https://brace.example"
SCENARIO = "synthetic-hurricane"
SECRET = "synthetic-preparation-owner-secret"


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv(auth.OWNER_SECRET_ENV, SECRET)
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("BRACE_PREPARATION_CASES", json.dumps({f"7:{SCENARIO}": "case_bound"}))
    store = CaseStore(tmp_path / "recovery.db", tmp_path / "media")
    for case_id, property_id, mode, actor in (("case_bound", "7", "scenario_exercise", OWNER),
            ("case_other", "8", "scenario_exercise", OWNER),
            ("case_observed", "7", "observed_recovery", OWNER),
            ("case_foreign", "7", "scenario_exercise", OTHER_OWNER)):
        data = case_input(case_id).model_dump()
        data.update(property_ref={"dataset": "commercial_property", "id": property_id}, mode=mode)
        store.create_case(actor, CaseInput(**data))
        store.add_household(actor, case_id, "A")
    store.add_household(OWNER, "case_bound", "B")
    raw_plan = {"actions": [{"id": "A1"}, {"id": "A2"}],
        "threat": {"kind": "hurricane", "name": "Hurricane Test", "replay": True,
            "forecast_issued": "2024-07-06T21:00:00Z", "hours_left": 30,
            "at_this_site": {"peak_wind_mph": 54}},
        "messages": [{"id": "M1", "kind": "notice", "to": "Residents", "subject": "Preparation exercise",
            "body": "Hurricane Test will bring extreme gusts.\n\nThe covered parking is fine to use.\n\nBring everything inside from your balcony or patio: chairs, tables, grills, plants and pots",
            "action_ids": ["A1"]},
            {"id": "M2", "kind": "work_order", "to": "Maintenance", "subject": "Internal plan",
             "body": "Not a resident notice", "action_ids": ["A2"]}]}
    app = FastAPI()
    app.state.brace_recovery_store = store
    app.state.plan = correct_plan_notices(raw_plan)
    app.include_router(build_router(store, None))

    @app.post(PATH)
    def approve(body: dict, request: Request):
        return approve_notice(request, building=body.get("building", 7), scenario=body.get("scenario", SCENARIO),
                              step=body.get("step", "t36"), action_id=body.get("action_id", "A1"),
                              plan=request.app.state.plan)

    def phone(case_id):
        snapshot = store.owner_snapshot(OWNER, case_id)
        invitation = store.create_invitation(OWNER, case_id, snapshot.household_labels[0].household_id,
                                             snapshot.case.case_revision)
        client = TestClient(app, headers={"Origin": ORIGIN})
        assert client.post("/api/resident/session", json={"invitation_token": invitation.invitation_token}).status_code == 200
        return client

    owner = TestClient(app, headers={"Origin": ORIGIN})
    assert owner.post("/api/recovery/session", json={"secret": SECRET}).status_code == 200
    resident, other = phone("case_bound"), phone("case_other")
    yield {"app": app, "store": store, "owner": owner, "resident": resident, "other": other,
           "raw_plan": raw_plan}
    owner.close(); resident.close(); other.close()


def test_owner_publishes_corrected_preview_to_bound_resident_feed_once(bridge):
    owner, store = bridge["owner"], bridge["store"]
    preview = bridge["app"].state.plan["messages"][0]
    assert preview["body"].startswith("SCENARIO EXERCISE")
    assert "sustained winds near 54 mph" in preview["body"]
    assert "Do not bring grills, fuel or propane cylinders indoors." in preview["body"]
    assert "The covered parking is fine to use." not in preview["body"]
    first = owner.post(PATH, json={})
    assert first.status_code == 200
    result = first.json()
    assert result["ok"] and result["delivery"] == "resident_feed" and result["case_id"] == "case_bound"
    assert result["household_count"] == 2 and result["already_published"] is False
    notice = bridge["resident"].get("/api/resident/home").json()["notices"][0]
    assert notice["notice_id"] == result["notice_id"]
    assert notice["title"] == preview["subject"] and notice["body"] == preview["body"]
    assert notice["source_ids"][0].startswith(f"preparation:7:{SCENARIO}:t36:M1:")
    assert bridge["other"].get("/api/resident/home").json()["notices"] == []
    store.add_household(OWNER, "case_bound", "C")
    before = store.owner_snapshot(OWNER, "case_bound")
    retry = owner.post(PATH, json={}).json()
    assert retry["already_published"] and retry["notice_id"] == result["notice_id"]
    assert retry["case_revision"] == result["case_revision"]
    assert retry["published_at"] == result["published_at"]
    assert store.owner_snapshot(OWNER, "case_bound") == before
    reopened = CaseStore(store.db_path, store.media_dir)
    assert len(reopened.owner_snapshot(OWNER, "case_bound").notices) == 1


def test_anonymous_and_resident_cannot_approve(bridge):
    with TestClient(bridge["app"], headers={"Origin": ORIGIN}) as anonymous:
        assert anonymous.post(PATH, json={}).status_code == 401
    assert bridge["resident"].post(PATH, json={}).status_code == 401
    assert bridge["resident"].get("/api/resident/home").json()["notices"] == []


@pytest.mark.parametrize("bindings,status", [({}, 409), ({f"7:{SCENARIO}": "case_other"}, 409),
    ({f"7:{SCENARIO}": "case_missing"}, 404), ({f"7:{SCENARIO}": "case_foreign"}, 404),
    ({f"7:{SCENARIO}": "case_observed"}, 409)])
def test_missing_wrong_foreign_or_nonexercise_binding_cannot_publish(bridge, monkeypatch, bindings, status):
    monkeypatch.setenv("BRACE_PREPARATION_CASES", json.dumps(bindings))
    response = bridge["owner"].post(PATH, json={})
    assert response.status_code == status
    if bindings.get(f"7:{SCENARIO}") == "case_observed":
        assert "exercise case" in response.json()["detail"]
    with bridge["store"]._read() as conn:
        assert conn.execute("SELECT count(*) FROM notices").fetchone()[0] == 0


@pytest.mark.parametrize("action,ambiguous", [("unknown", False), ("A2", False), ("A1", True)])
def test_unknown_unlinked_and_ambiguous_notice_approvals_are_rejected(bridge, action, ambiguous):
    if ambiguous:
        second = deepcopy(bridge["app"].state.plan["messages"][0])
        second["id"] = "M3"
        bridge["app"].state.plan["messages"].append(second)
    response = bridge["owner"].post(PATH, json={"action_id": action})
    assert response.status_code == 409
    assert "exactly one resident notice" in response.json()["detail"]
    assert bridge["resident"].get("/api/resident/home").json()["notices"] == []


def test_cross_origin_approval_is_rejected(bridge):
    response = bridge["owner"].post(PATH, json={}, headers={"Origin": "https://other.example"})
    assert response.status_code == 403
    assert bridge["resident"].get("/api/resident/home").json()["notices"] == []


@pytest.mark.parametrize("value", ["invalid-json", "[]", "null"])
def test_invalid_binding_configuration_fails_without_publication(bridge, monkeypatch, value):
    monkeypatch.setenv("BRACE_PREPARATION_CASES", value)
    assert bridge["owner"].post(PATH, json={}).status_code == 503
    assert bridge["resident"].get("/api/resident/home").json()["notices"] == []
