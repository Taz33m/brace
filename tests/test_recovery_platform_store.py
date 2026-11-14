from __future__ import annotations

import sqlite3

import pytest

from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OTHER_OWNER, OWNER, case_input, seeded


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


def test_case_persists_after_reopening_store(tmp_path):
    db = tmp_path / "recovery.db"
    CaseStore(db, tmp_path / "media").create_case(OWNER, case_input())
    reopened = CaseStore(db, tmp_path / "media")
    cases = reopened.list_cases(OWNER)
    assert [c.case_id for c in cases] == ["case_test"]
    assert cases[0].case_revision == 1 and cases[0].analysis_revision == 1
    assert cases[0].mode_label.startswith("Scenario exercise")


def test_database_uses_wal(tmp_path):
    CaseStore(tmp_path / "r.db", tmp_path / "m")
    assert sqlite3.connect(tmp_path / "r.db").execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_list_cases_hides_other_owners_cases(store):
    store.create_case(OWNER, case_input())
    assert store.list_cases(OTHER_OWNER) == []


def test_owner_snapshot_of_foreign_or_missing_case_is_404(store):
    store.create_case(OWNER, case_input())
    for actor, case_id in ((OTHER_OWNER, "case_test"), (OWNER, "nope")):
        with pytest.raises(PlatformError) as e:
            store.owner_snapshot(actor, case_id)
        assert e.value.status == 404


def test_residents_cannot_use_owner_reads(store):
    _, _, res_a, _ = seeded(store)
    with pytest.raises(PlatformError) as e:
        store.owner_snapshot(res_a, "case_test")
    assert e.value.status == 403


def test_owner_snapshot_shape_and_household_labels(store):
    seeded(store)
    view = store.owner_snapshot(OWNER, "case_test")
    assert view.case.case_id == "case_test"
    assert sorted(h.unit_label for h in view.household_labels) == ["A", "B"]
    assert view.reports == [] and view.tasks == [] and view.current_assessment_id is None
    # Adding households is a public mutation: revision moved and events were written.
    assert view.case.case_revision == 3 and view.event_cursor >= 3


def test_create_case_rejects_duplicate_id(store):
    store.create_case(OWNER, case_input())
    with pytest.raises(PlatformError) as e:
        store.create_case(OWNER, case_input())
    assert e.value.status == 409


def test_add_household_rejects_unknown_location(store):
    store.create_case(OWNER, case_input())
    with pytest.raises(PlatformError) as e:
        store.add_household(OWNER, "case_test", "C", location_ids=["loc_nowhere"])
    assert e.value.status == 422
