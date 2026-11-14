"""Owner draft review/publication against the real Platform, without model calls."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.recovery.domain.service import failed_result
from backend.recovery.notice_router import build_notice_router
from backend.recovery.platform import models as m
from backend.recovery.platform.auth import Actor
from backend.recovery.platform.router import build_router, make_owner_dependency
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input, report


def add_draft(store, *, identity=None, sources=None):
    snapshot = store.owner_snapshot(OWNER, "case_test")
    tickets = []
    result = store.apply_command(OWNER, "case_test", m.StartAssessment(type="start_assessment", expected_revision=snapshot.case.case_revision),
                                 launcher=tickets.append)
    frozen = store.snapshot_for_analysis("case_test")
    envelope = failed_result(frozen, result.run_id, "Synthetic draft", status="draft")
    draft_id = identity if identity is not None else f"{result.run_id}:notice:1"
    envelope["draft_notices"] = [{"draft_id": draft_id, "title": "Review update", "body": "Work is awaiting review.",
                                  "source_ids": sources if sources is not None else ["inspection-source"]}]
    store.complete_assessment(result.run_id, tickets[0]["base_analysis_revision"], envelope)
    return draft_id, result.run_id


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACE_OWNER_SECRET", "synthetic-notice-test-secret")
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", "https://owner.example")
    store = CaseStore(tmp_path / "cases.sqlite3")
    evidence = m.Evidence(evidence_id="inspection", source_id="inspection-source", kind="inspection", source_label="Synthetic inspection",
                          captured_at=None, effective_at="2026-11-13", available_at="2026-11-13", received_at="2026-11-14T00:00:00Z",
                          model_created_at=None, location=None, media=None, summary="Synthetic test evidence", limitations=[])
    store.create_case(OWNER, case_input().model_copy(update={"evidence": [evidence]}))
    draft_id, run_id = add_draft(store)
    households = [store.add_household(OWNER, "case_test", label) for label in ("A", "B")]
    residents = [Actor("resident", "resident:" + household, "case_test", household) for household in households]
    app = FastAPI()
    app.include_router(build_router(store))
    app.include_router(build_notice_router(store, make_owner_dependency(store)))
    with TestClient(app, headers={"Origin": "https://owner.example"}) as owner:
        assert owner.post("/api/recovery/session", json={"secret": "synthetic-notice-test-secret"}).status_code == 200
        yield store, owner, app, draft_id, run_id, households, residents


def listed(owner):
    response = owner.get("/api/recovery/cases/case_test/draft-notices")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def publish(owner, draft_id, body, key="notice-publish-key-1"):
    return owner.post(f"/api/recovery/cases/case_test/draft-notices/{draft_id}/publish", json=body,
                      headers={"Idempotency-Key": key})


def test_owner_lists_linked_draft_and_publishes_edited_household_notice(world):
    store, owner, _, draft_id, run_id, households, residents = world
    view = listed(owner)
    assert set(view) == {"case_id", "case_revision", "analysis_revision", "drafts"}
    draft = view["drafts"][0]
    assert set(draft) == {"draft_id", "run_id", "base_analysis_revision", "title", "body", "source_ids", "eligible", "unavailable_reason"}
    assert draft["draft_id"] == draft_id and draft["run_id"] == run_id
    assert draft["eligible"] and draft["unavailable_reason"] is None
    response = publish(owner, draft_id, {"expected_revision": view["case_revision"], "title": "Edited update",
                                       "body": "Approved for review; no contractor is scheduled.", "household_ids": [households[0]]})
    assert response.status_code == 200, response.text
    notices = store.resident_home(residents[0]).notices
    assert len(notices) == 1 and notices[0].title == "Edited update"
    assert notices[0].source_ids == ["inspection-source"]
    assert store.resident_home(residents[1]).notices == []
    assert len(store.draft_notices(OWNER, "case_test")) == 1  # publication does not rewrite immutable drafts


def test_retry_after_new_report_returns_original_receipt_without_republishing(world):
    store, owner, _, draft_id, _, _, residents = world
    before = listed(owner)
    body = {"expected_revision": before["case_revision"], "title": "Reviewed update", "body": "Review is continuing.", "household_ids": None}
    first = publish(owner, draft_id, body)
    assert first.status_code == 200
    store.append_report(residents[0], report(), "new-report-after-notice")
    assert not listed(owner)["drafts"][0]["eligible"]
    again = publish(owner, draft_id, body)
    assert again.status_code == 200 and again.json() == first.json()
    assert len(store.resident_home(residents[0]).notices) == 1
    changed = publish(owner, draft_id, {**body, "body": "Different request body"})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
    stale = publish(owner, draft_id, body, key="brand-new-request-key")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "revision_conflict"
    fresh_revision_stale_draft = publish(owner, draft_id, {**body, "expected_revision": listed(owner)["case_revision"]}, key="another-new-key")
    assert fresh_revision_stale_draft.status_code == 409 and fresh_revision_stale_draft.json()["error"]["code"] == "draft_unavailable"


@pytest.mark.parametrize("identity,sources", [("legacy-id", None), (None, ["not-a-case-source"])])
def test_unknown_run_or_sources_make_draft_ineligible(world, identity, sources):
    store, owner, _, _, _, _, _ = world
    draft_id, _ = add_draft(store, identity=identity, sources=sources)
    view = listed(owner)
    row = next(x for x in view["drafts"] if x["draft_id"] == draft_id)
    assert not row["eligible"] and row["unavailable_reason"]
    response = publish(owner, draft_id, {"expected_revision": view["case_revision"], "title": "X", "body": "Y", "household_ids": None})
    assert response.status_code == 409


def test_publication_race_with_new_condition_is_caught_by_store_revision(world, monkeypatch):
    store, owner, _, draft_id, _, _, residents = world
    view = listed(owner)
    original = store.apply_command

    def race(actor, case_id, command, key):
        store.append_report(residents[0], report(), "report-during-publish")
        return original(actor, case_id, command, key)

    monkeypatch.setattr(store, "apply_command", race)
    response = publish(owner, draft_id, {"expected_revision": view["case_revision"], "title": "X", "body": "Y", "household_ids": None})
    assert response.status_code == 409
    assert store.resident_home(residents[0]).notices == []


def test_draft_routes_are_owner_only_and_case_scoped(world):
    store, owner, app, draft_id, _, households, _ = world
    other = case_input("another-case")
    store.create_case(OTHER_OWNER, other)
    assert owner.get("/api/recovery/cases/another-case/draft-notices").status_code == 404
    with TestClient(app) as guest:
        response = guest.get("/api/recovery/cases/case_test/draft-notices")
        assert response.status_code == 401 and "error" in response.json()
        revision = store.owner_snapshot(OWNER, "case_test").case.case_revision
        invitation = store.create_invitation(OWNER, "case_test", households[0], revision)
        assert guest.post("/api/resident/session", json={"invitation_token": invitation.invitation_token}).status_code == 200
        assert guest.get("/api/recovery/cases/case_test/draft-notices").status_code == 401
        assert publish(guest, draft_id, {"expected_revision": revision, "title": "X", "body": "Y", "household_ids": None}).status_code == 401


@pytest.mark.parametrize("change", [{"source_ids": ["invented"]}, {"title": " "}, {"title": "x" * 201}, {"body": "x" * 4001}, {"household_ids": []}])
def test_publish_input_limits_and_server_owned_sources(world, change):
    _, owner, _, draft_id, _, _, _ = world
    body = {"expected_revision": listed(owner)["case_revision"], "title": "X", "body": "Y", "household_ids": None, **change}
    assert publish(owner, draft_id, body).status_code == 422


def test_required_idempotency_and_origin_check(world):
    _, owner, _, draft_id, _, _, _ = world
    body = {"expected_revision": listed(owner)["case_revision"], "title": "X", "body": "Y", "household_ids": None}
    path = f"/api/recovery/cases/case_test/draft-notices/{draft_id}/publish"
    assert owner.post(path, json=body).status_code == 422
    assert owner.post(path, json=body, headers={"Idempotency-Key": "origin-test-key", "Origin": "https://foreign.example"}).status_code == 403


def test_future_revision_cannot_bypass_draft_guard(world):
    _, owner, _, draft_id, _, _, _ = world
    response = publish(owner, draft_id, {"expected_revision": listed(owner)["case_revision"] + 1, "title": "X", "body": "Y", "household_ids": None})
    assert response.status_code == 409 and response.json()["error"]["code"] == "revision_conflict"
