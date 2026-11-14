"""Owner commands: observation review, task transitions, notices, revision checks."""
from __future__ import annotations

import threading

import pytest

from backend.recovery.platform import models as m
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, report, seeded


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


@pytest.fixture
def world(store):
    return seeded(store)


def rev(store) -> int:
    return store.owner_snapshot(OWNER, "case_test").case.case_revision


def cmd(store, **kw):
    command = {"expected_revision": rev(store), **kw}
    from pydantic import TypeAdapter

    return store.apply_command(OWNER, "case_test", TypeAdapter(m.OwnerCommand).validate_python(command))


def notice(store, household_ids=None, expected=None):
    from pydantic import TypeAdapter

    c = TypeAdapter(m.OwnerCommand).validate_python({
        "type": "publish_notice", "title": "Water shutoff", "body": "Water is off on floor 2 until inspected.",
        "household_ids": household_ids, "source_ids": [], "expected_revision": expected or rev(store)})
    return store.apply_command(OWNER, "case_test", c)


# ---------------------------------------------------------------- revisions

def test_stale_expected_revision_is_409_with_current_revision(store, world):
    current = rev(store)
    with pytest.raises(PlatformError) as e:
        notice(store, expected=current - 1)
    assert e.value.status == 409 and e.value.current_revision == current


def test_concurrent_owner_edits_one_wins_one_conflicts(store, world):
    expected = rev(store)
    outcomes, barrier = [], threading.Barrier(2)

    def go():
        barrier.wait()
        try:
            notice(store, expected=expected)
            outcomes.append("ok")
        except PlatformError as exc:
            outcomes.append(exc.status)

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(outcomes, key=str) == [409, "ok"]
    assert len(store.owner_snapshot(OWNER, "case_test").notices) == 1


def test_command_idempotency_key_replays_result(store, world):
    from pydantic import TypeAdapter

    c = TypeAdapter(m.OwnerCommand).validate_python({
        "type": "publish_notice", "title": "t", "body": "b", "household_ids": None, "source_ids": [],
        "expected_revision": rev(store)})
    first = store.apply_command(OWNER, "case_test", c, "owner-key-1")
    again = store.apply_command(OWNER, "case_test", c, "owner-key-1")
    assert first == again and len(store.owner_snapshot(OWNER, "case_test").notices) == 1


# ---------------------------------------------------------------- observations

def _observation(store, world):
    _, _, res_a, _ = world
    receipt = store.append_report(res_a, report(), "key-0001")
    obs = store.owner_snapshot(OWNER, "case_test").observations[0]
    return receipt, obs


def _evidence(store):
    from tests.test_recovery_platform_support import location

    return store.add_evidence(OWNER, "case_test", m.Evidence(
        evidence_id="ev_inspection_1", kind="inspection", source_id="inspection-1",
        source_label="Site inspection notes", captured_at="2024-07-10", effective_at="2024-07-10",
        available_at="2024-07-10", received_at="2026-11-14T12:00:00+00:00", model_created_at=None,
        location=location("loc_kitchen_a", "Unit A kitchen", "A"), media=None,
        summary="Inspector saw standing water", limitations=[]), rev(store))


def test_review_to_under_review_then_verified_updates_report_status(store, world):
    _, _, res_a, _ = world
    receipt, obs = _observation(store, world)
    before = store.owner_snapshot(OWNER, "case_test").case
    cmd(store, type="review_observation", observation_id=obs.observation_id, status="under_review",
        note="", evidence_ids=[])
    _evidence(store)
    result = cmd(store, type="review_observation", observation_id=obs.observation_id, status="verified",
                 note="Inspector confirmed", evidence_ids=["ev_inspection_1"])
    assert result.analysis_revision > before.analysis_revision
    view = store.owner_snapshot(OWNER, "case_test")
    o = view.observations[0]
    assert o.status == "verified" and o.verified_by == OWNER.actor_id and o.verification_note == "Inspector confirmed"
    assert "ev_inspection_1" in o.evidence_ids
    home = store.resident_home(res_a)
    assert home.reports[0].status == "verified"
    assert home.reports[0].report_id == receipt.report.report_id


def test_verify_requires_note_and_case_evidence(store, world):
    _, obs = _observation(store, world)
    for note, evidence in (("", ["ev_x"]), ("ok", []), ("ok", ["ev_not_in_case"])):
        with pytest.raises(PlatformError) as e:
            cmd(store, type="review_observation", observation_id=obs.observation_id, status="verified",
                note=note, evidence_ids=evidence)
        assert e.value.status == 422


def test_dismiss_requires_note(store, world):
    _, obs = _observation(store, world)
    with pytest.raises(PlatformError):
        cmd(store, type="review_observation", observation_id=obs.observation_id, status="dismissed",
            note=" ", evidence_ids=[])
    cmd(store, type="review_observation", observation_id=obs.observation_id, status="dismissed",
        note="Duplicate of another report", evidence_ids=[])


def test_review_of_unknown_observation_is_404(store, world):
    with pytest.raises(PlatformError) as e:
        cmd(store, type="review_observation", observation_id="obs_nope", status="under_review",
            note="", evidence_ids=[])
    assert e.value.status == 404


# ---------------------------------------------------------------- tasks

def _task(store, households):
    return store.add_task_proposal(OWNER, "case_test", title="Dry out unit A kitchen",
                                   scope="Extract water and run dehumidifiers", household_ids=households)


def _move(store, task_id, status, **kw):
    task = next(t for t in store.owner_snapshot(OWNER, "case_test").tasks if t.task_id == task_id)
    args = dict(note="", confirmation_source=None, evidence_ids=[])
    args.update(kw)
    return cmd(store, type="transition_task", task_id=task_id, expected_task_revision=task.revision,
               status=status, **args)


def test_task_full_lifecycle_with_required_confirmations(store, world):
    ha, _, res_a, res_b = world
    task_id = _task(store, [ha])
    assert store.resident_home(res_a).tasks == []  # proposed is owner-only
    _move(store, task_id, "approved")
    assert store.resident_home(res_a).tasks[0].status == "approved"
    assert store.resident_home(res_b).tasks == []
    with pytest.raises(PlatformError):
        _move(store, task_id, "accepted")  # no confirmation source
    _move(store, task_id, "accepted", confirmation_source="Phone call with contractor, 2026-11-14")
    _move(store, task_id, "in_progress")
    with pytest.raises(PlatformError):
        _move(store, task_id, "completion_submitted")  # no evidence
    _evidence(store)
    _move(store, task_id, "completion_submitted", evidence_ids=["ev_inspection_1"])
    before = store.owner_snapshot(OWNER, "case_test").case.analysis_revision
    with pytest.raises(PlatformError):
        _move(store, task_id, "verified")  # reviewer note required
    result = _move(store, task_id, "verified", note="Checked on site")
    assert result.analysis_revision == before + 1
    task = store.owner_snapshot(OWNER, "case_test").tasks[0]
    assert task.status == "verified" and task.completion_evidence_ids == ["ev_inspection_1"]
    assert task.confirmation_source == "Phone call with contractor, 2026-11-14"
    assert "occupancy" in store.resident_home(res_a).tasks[0].public_status_detail


@pytest.mark.parametrize("target", ["accepted", "in_progress", "completion_submitted", "verified", "proposed"])
def test_invalid_task_transitions_rejected(store, world, target):
    ha, _, _, _ = world
    task_id = _task(store, [ha])
    with pytest.raises(PlatformError) as e:
        _move(store, task_id, target, confirmation_source="x", evidence_ids=[], note="n")
    assert e.value.status in (409, 422)


def test_cancel_needs_reason_and_is_terminal(store, world):
    ha, _, _, _ = world
    task_id = _task(store, [ha])
    with pytest.raises(PlatformError):
        _move(store, task_id, "cancelled")
    _move(store, task_id, "cancelled", note="Duplicate task")
    with pytest.raises(PlatformError):
        _move(store, task_id, "approved")


def test_stale_task_revision_conflicts(store, world):
    ha, _, _, _ = world
    task_id = _task(store, [ha])
    _move(store, task_id, "approved")
    with pytest.raises(PlatformError) as e:
        cmd(store, type="transition_task", task_id=task_id, expected_task_revision=1, status="cancelled",
            note="x", confirmation_source=None, evidence_ids=[])
    assert e.value.status == 409


def test_changed_accepted_scope_requires_new_acceptance(store, world):
    ha, _, _, _ = world
    task_id = _task(store, [ha])
    _move(store, task_id, "approved")
    _move(store, task_id, "accepted", confirmation_source="Email from contractor")
    store.revise_task_scope(OWNER, "case_test", task_id, "Also replace baseboards", rev(store))
    task = store.owner_snapshot(OWNER, "case_test").tasks[0]
    assert task.status == "approved" and task.confirmation_source is None
    assert task.superseded_scope == "Extract water and run dehumidifiers" and task.scope == "Also replace baseboards"


# ---------------------------------------------------------------- notices

def test_targeted_notice_only_reaches_that_household_and_does_not_bump_analysis(store, world):
    ha, _, res_a, res_b = world
    before = store.owner_snapshot(OWNER, "case_test").case
    result = notice(store, household_ids=[ha])
    assert result.analysis_revision == before.analysis_revision
    assert result.case_revision == before.case_revision + 1
    assert [n.title for n in store.resident_home(res_a).notices] == ["Water shutoff"]
    assert store.resident_home(res_b).notices == []
    assert [e.type for e in store.events_after(res_a, 0)] == ["notice.published"]
    assert store.events_after(res_b, 0) == []


def test_case_wide_notice_reaches_everyone(store, world):
    _, _, res_a, res_b = world
    notice(store)
    assert len(store.resident_home(res_a).notices) == len(store.resident_home(res_b).notices) == 1


def test_notice_validation(store, world):
    for households in ([], ["hh_not_in_case"]):
        with pytest.raises(PlatformError) as e:
            notice(store, household_ids=households)
        assert e.value.status == 422
