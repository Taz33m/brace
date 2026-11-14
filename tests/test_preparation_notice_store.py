"""Approved preparation notices publish atomically and survive delayed retries."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.recovery.platform.auth import SYSTEM
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input, report, seeded


@pytest.fixture
def world(tmp_path):
    store = CaseStore(tmp_path / "recovery.db", tmp_path / "media")
    return store, seeded(store)


def publish(store, *, actor=OWNER, case_id="case_test", **changes):
    content = {"approval_key": "approved-preparation-1", "title": "Storm preparation update",
               "body": "Property team preparation notice.\nNo occupancy clearance is implied.",
               "source_ids": ["prepared-plan:1", "forecast:1"]}
    return store.publish_preparation_notice(actor, case_id, **{**content, **changes})


def test_publishes_one_case_notice_event_and_receipt_with_exact_approved_content(world):
    store, (_, _, resident_a, resident_b) = world
    before = store.owner_snapshot(OWNER, "case_test")
    receipt = publish(store)
    assert set(receipt) == {"notice_id", "case_revision", "analysis_revision", "published_at", "already_published"}
    assert receipt["already_published"] is False
    assert receipt["case_revision"] == before.case.case_revision + 1
    assert receipt["analysis_revision"] == before.case.analysis_revision
    for resident in (resident_a, resident_b):
        notice = store.resident_home(resident).notices[0]
        assert notice.notice_id == receipt["notice_id"]
        assert notice.published_at == receipt["published_at"]
        assert notice.published_by == OWNER.actor_id
        assert notice.body == "Property team preparation notice.\nNo occupancy clearance is implied."
        assert notice.source_ids == ["prepared-plan:1", "forecast:1"]
        events = store.events_after(resident, before.event_cursor)
        assert [(event.type, event.entity_id) for event in events] == [("notice.published", receipt["notice_id"])]
    with store._read() as conn:
        assert conn.execute("SELECT count(*) FROM idempotency WHERE operation = 'preparation-notice:case_test'").fetchone()[0] == 1


def test_retry_survives_new_inputs_and_store_restart_without_another_publication(world):
    store, (_, _, resident, _) = world
    first = publish(store)
    store.append_report(resident, report(), "report-after-notice")
    reopened = CaseStore(store.db_path, store.media_dir)
    before = reopened.owner_snapshot(OWNER, "case_test")
    retry = publish(reopened)
    assert retry == {**first, "already_published": True}
    assert reopened.owner_snapshot(OWNER, "case_test") == before
    assert len(reopened.resident_home(resident).notices) == 1


@pytest.mark.parametrize("changed", [{"title": "Changed title"}, {"body": "Changed approved text"},
                                     {"source_ids": ["forecast:1"]}, {"source_ids": ["forecast:1", "prepared-plan:1"]}])
def test_same_approval_key_cannot_change_content(world, changed):
    store, _ = world
    publish(store)
    before = store.owner_snapshot(OWNER, "case_test")
    with pytest.raises(PlatformError) as exc:
        publish(store, **changed)
    assert exc.value.status == 409 and exc.value.code == "idempotency_conflict"
    assert store.owner_snapshot(OWNER, "case_test") == before


def test_owner_membership_is_checked_before_replay(world):
    store, (_, _, resident, _) = world
    publish(store)
    for actor, expected in ((OTHER_OWNER, 404), (resident, 403), (SYSTEM, 403)):
        with pytest.raises(PlatformError) as exc:
            publish(store, actor=actor)
        assert exc.value.status == expected


def test_approval_receipts_are_scoped_to_case(world):
    store, _ = world
    store.create_case(OWNER, case_input("case_other"))
    first = publish(store)
    other = publish(store, case_id="case_other")
    assert other["notice_id"] != first["notice_id"] and not other["already_published"]
    assert publish(store, case_id="case_other") == {**other, "already_published": True}


def test_receipt_failure_rolls_back_notice_revision_and_event(world, monkeypatch):
    store, _ = world
    before = store.owner_snapshot(OWNER, "case_test")
    def fail_receipt(*args, **kwargs):
        raise RuntimeError("Synthetic receipt failure")
    with monkeypatch.context() as patch:
        patch.setattr(store, "_remember", fail_receipt)
        with pytest.raises(RuntimeError, match="Synthetic receipt failure"):
            publish(store)
    assert store.owner_snapshot(OWNER, "case_test") == before
    with store._read() as conn:
        assert conn.execute("SELECT count(*) FROM notices").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM idempotency").fetchone()[0] == 0
    assert publish(store)["already_published"] is False


def test_simultaneous_approval_retries_publish_once(world):
    store, (_, _, resident, _) = world
    barrier = Barrier(2)
    def attempt():
        barrier.wait(timeout=3)
        return publish(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert results[0]["notice_id"] == results[1]["notice_id"]
    assert sorted(result["already_published"] for result in results) == [False, True]
    assert len(store.resident_home(resident).notices) == 1
    assert len([event for event in store.events_after(resident, 0) if event.type == "notice.published"]) == 1


@pytest.mark.parametrize("changes", [{"title": " "}, {"body": "x" * 4001}, {"source_ids": [""]},
                                     {"source_ids": ["source"] * 51}, {"approval_key": "short"}])
def test_invalid_publication_does_not_change_case(world, changes):
    store, _ = world
    before = store.owner_snapshot(OWNER, "case_test")
    with pytest.raises(PlatformError) as exc:
        publish(store, **changes)
    assert exc.value.status == 422
    assert store.owner_snapshot(OWNER, "case_test") == before
