"""Assessment run hook: tickets, stale detection, publication, restart, worker handshake."""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from backend.recovery.platform import models as m
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, report, seeded


class RecordingLauncher:
    def __init__(self):
        self.tickets = []

    def __call__(self, ticket):
        self.tickets.append(dict(ticket))
        return None


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


@pytest.fixture
def world(store):
    return seeded(store)


def rev(store):
    return store.owner_snapshot(OWNER, "case_test").case.case_revision


def command(store, launcher=None, **kw):
    c = TypeAdapter(m.OwnerCommand).validate_python({"expected_revision": rev(store), **kw})
    return store.apply_command(OWNER, "case_test", c, launcher=launcher)


def start(store, launcher):
    return command(store, launcher, type="start_assessment")


def envelope(run_id, base, *, task_households=(), status="draft"):
    return {
        "assessment": {"assessment_id": "assessment_" + run_id, "run_id": run_id,
                       "base_analysis_revision": base, "status": status, "headline": "Water damage in unit A",
                       "summary": "Draft", "created_at": "2026-11-14T12:00:00+00:00", "published_at": None,
                       "valuation": None, "observation_ids": [], "unresolved_questions": ["Depth unknown"],
                       "failure_reason": None},
        "proposed_tasks": [{"task_id": "task_from_" + run_id, "revision": 1, "title": "Inspect unit A",
                            "scope": "Moisture readings", "status": "proposed", "location": None,
                            "evidence_ids": [], "household_ids": list(task_households), "assignee_label": None,
                            "confirmation_source": None, "confirmed_schedule": None,
                            "completion_evidence_ids": [], "updated_at": "2026-11-14T12:00:00+00:00",
                            "superseded_scope": None}],
        "draft_notices": [{"draft_id": "d1", "title": "Update", "body": "We are inspecting.", "source_ids": [],
                           "audience": "case", "requires_owner_review": True}],
        "trace": [],
    }


def test_no_launcher_is_503_assessment_unavailable(store, world):
    with pytest.raises(PlatformError) as e:
        start(store, None)
    assert e.value.status == 503 and e.value.code == "assessment_unavailable"


def test_start_creates_ticket_and_repeat_returns_same_run(store, world):
    launcher = RecordingLauncher()
    analysis = store.owner_snapshot(OWNER, "case_test").case.analysis_revision
    first = start(store, launcher)
    assert first.run_id and launcher.tickets == [{"run_id": first.run_id, "case_id": "case_test",
                                                  "base_analysis_revision": analysis}]
    assert first.analysis_revision == analysis  # starting a run does not change inputs
    again = start(store, launcher)
    # Same run; the launcher may see the same ticket again (it dedupes by run_id).
    assert again.run_id == first.run_id and all(t == launcher.tickets[0] for t in launcher.tickets)


def test_launcher_failure_marks_run_failed_and_is_503(store, world):
    def broken(ticket):
        raise RuntimeError("Recovery assessment workers are busy; retry later")

    with pytest.raises(PlatformError) as e:
        start(store, broken)
    assert e.value.status == 503 and e.value.retryable
    # The failed run does not block the next attempt.
    assert start(store, RecordingLauncher()).run_id


def test_completion_on_current_inputs_is_draft_with_proposals(store, world):
    ha, _, res_a, _ = world
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    saved = store.complete_assessment(run.run_id, base, envelope(run.run_id, base, task_households=[ha]))
    assert saved.status == "draft"
    view = store.owner_snapshot(OWNER, "case_test")
    assert view.current_assessment_id == saved.assessment_id
    assert [t.status for t in view.tasks] == ["proposed"]
    assert view.notices == []  # agent drafts are never published by saving
    assert store.resident_home(res_a).tasks == [] and store.resident_home(res_a).notices == []


def test_report_during_run_makes_result_stale(store, world):
    _, _, res_a, _ = world
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    store.append_report(res_a, report(), "key-0001")
    saved = store.complete_assessment(run.run_id, base, envelope(run.run_id, base))
    assert saved.status == "stale"
    view = store.owner_snapshot(OWNER, "case_test")
    assert view.current_assessment_id is None and view.tasks == []
    assert [a.status for a in view.assessments] == ["stale"]


def test_notice_during_run_does_not_stale_result(store, world):
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    command(store, type="publish_notice", title="t", body="b", household_ids=None, source_ids=[])
    assert store.complete_assessment(run.run_id, base, envelope(run.run_id, base)).status == "draft"


def test_completion_is_idempotent_by_run_id(store, world):
    ha, _, _, _ = world
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    first = store.complete_assessment(run.run_id, base, envelope(run.run_id, base, task_households=[ha]))
    again = store.complete_assessment(run.run_id, base, envelope(run.run_id, base, task_households=[ha]))
    assert first == again
    view = store.owner_snapshot(OWNER, "case_test")
    assert len(view.assessments) == 1 and len(view.tasks) == 1


def test_completion_rejects_mismatched_identity(store, world):
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    with pytest.raises(PlatformError):
        store.complete_assessment(run.run_id, base + 5, envelope(run.run_id, base + 5))
    with pytest.raises(PlatformError):
        store.complete_assessment("run_unknown", base, envelope("run_unknown", base))


def test_publish_draft_then_later_report_supersedes_nothing(store, world):
    _, _, res_a, _ = world
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    saved = store.complete_assessment(run.run_id, base, envelope(run.run_id, base))
    result = command(store, type="publish_assessment", assessment_id=saved.assessment_id)
    view = store.owner_snapshot(OWNER, "case_test")
    assert view.assessments[0].status == "published" and view.assessments[0].published_at
    assert result.analysis_revision == base
    store.append_report(res_a, report(), "key-0001")
    # Published versions stay in history.
    assert store.owner_snapshot(OWNER, "case_test").assessments[0].status == "published"


def test_publish_of_draft_made_stale_by_new_report_is_409(store, world):
    _, _, res_a, _ = world
    run = start(store, RecordingLauncher())
    base = store.snapshot_for_analysis("case_test")["case"]["analysis_revision"]
    saved = store.complete_assessment(run.run_id, base, envelope(run.run_id, base))
    store.append_report(res_a, report(), "key-0001")
    assert store.owner_snapshot(OWNER, "case_test").assessments[0].status == "stale"
    with pytest.raises(PlatformError) as e:
        command(store, type="publish_assessment", assessment_id=saved.assessment_id)
    assert e.value.status == 409


def test_restart_marks_running_runs_failed_and_retryable(tmp_path):
    db, media = tmp_path / "recovery.db", tmp_path / "media"
    store = CaseStore(db, media)
    seeded(store)
    run = start(store, RecordingLauncher())
    reopened = CaseStore(db, media)
    view = reopened.owner_snapshot(OWNER, "case_test")
    failed = [a for a in view.assessments if a.run_id == run.run_id]
    assert failed and failed[0].status == "failed" and "retry" in failed[0].failure_reason.lower()
    assert start(reopened, RecordingLauncher()).run_id != run.run_id


def test_snapshot_for_analysis_is_owner_case_view(store, world):
    snap = store.snapshot_for_analysis("case_test")
    m.OwnerCaseView.model_validate(snap)
    assert snap["case"]["analysis_revision"] >= 1


def test_real_assessment_service_handshake(store, world):
    """Lead's AssessmentService with a scripted agent (no model, no network)."""
    from backend.recovery.domain.service import AssessmentService

    ha, _, _, _ = world

    class ScriptedAgent:
        def __init__(self, snapshot, inputs, inspect_image=None):
            self.snapshot = snapshot

        def run(self):
            run_id = self.snapshot["run_id"]
            return envelope(run_id, self.snapshot["case"]["analysis_revision"], task_households=[ha])

    service = AssessmentService(store, lambda snap: ({}, None), agent_factory=ScriptedAgent, max_workers=1)
    try:
        result = start(store, service.launch)
        service.futures[result.run_id].result(timeout=10)
    finally:
        service.close()
    view = store.owner_snapshot(OWNER, "case_test")
    assert view.assessments[0].status == "draft" and view.current_assessment_id
    assert [t.status for t in view.tasks] == ["proposed"]


def test_failed_commit_does_not_leave_run_stuck(store, world, monkeypatch):
    """A worker whose commit fails must be retryable from start_assessment (no permanent running)."""
    from backend.recovery.domain.service import AssessmentService

    class ScriptedAgent:
        def __init__(self, snapshot, inputs, inspect_image=None):
            self.snapshot = snapshot

        def run(self):
            return envelope(self.snapshot["run_id"], self.snapshot["case"]["analysis_revision"])

    real_complete, calls = store.complete_assessment, []

    def flaky(run_id, base, result):
        calls.append(run_id)
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return real_complete(run_id, base, result)

    monkeypatch.setattr(store, "complete_assessment", flaky)
    service = AssessmentService(store, lambda snap: ({}, None), agent_factory=ScriptedAgent, max_workers=1)
    try:
        first = start(store, service.launch)
        with pytest.raises(RuntimeError):
            service.futures[first.run_id].result(timeout=10)
        again = start(store, service.launch)
        assert again.run_id == first.run_id
        service.futures[first.run_id].result(timeout=10)
    finally:
        service.close()
    assert store.owner_snapshot(OWNER, "case_test").assessments[0].status == "draft"


def test_double_click_start_returns_same_run_not_409(store, world, monkeypatch):
    """Click B lands between click A's lookup and its insert: both must get the same run."""
    import threading
    from contextlib import contextmanager

    launcher = RecordingLauncher()
    expected = rev(store)
    cmd = TypeAdapter(m.OwnerCommand).validate_python({"type": "start_assessment", "expected_revision": expected})
    real_write = store._write
    a_first_write_done, b_done = threading.Event(), threading.Event()
    a_thread = {}

    @contextmanager
    def paused_write():
        with real_write() as conn:
            yield conn
        if threading.get_ident() == a_thread.get("id") and not a_first_write_done.is_set():
            a_first_write_done.set()
            b_done.wait(5)

    monkeypatch.setattr(store, "_write", paused_write)
    results = {}

    def click(name):
        if name == "a":
            a_thread["id"] = threading.get_ident()
        else:
            a_first_write_done.wait(5)
        try:
            results[name] = store.apply_command(OWNER, "case_test", cmd, launcher=launcher)
        except PlatformError as exc:
            results[name] = exc
        finally:
            if name == "b":
                b_done.set()

    threads = [threading.Thread(target=click, args=(n,)) for n in ("a", "b")]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert not isinstance(results["a"], PlatformError), results["a"]
    assert not isinstance(results["b"], PlatformError), results["b"]
    assert results["a"].run_id == results["b"].run_id
    runs = [a for a in store.owner_snapshot(OWNER, "case_test").events if a.type == "assessment.started"]
    assert len(runs) == 1
