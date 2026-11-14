"""Stable source IDs can be reused in separately authorized cases, including v1 upgrades."""
import json
import sqlite3

import pytest

from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.models import Evidence
from backend.recovery.platform.schema import MIGRATIONS
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, OTHER_OWNER, case_input


def evidence(eid="ev-stable-source", summary="Synthetic sponsor record"):
    return Evidence(evidence_id=eid, source_id="costar:synthetic-property", kind="costar_record",
                    source_label="Synthetic test source", captured_at=None, effective_at="2026-11-01",
                    available_at="2026-11-02", received_at="2026-11-14T00:00:00Z", model_created_at=None,
                    location=None, media=None, summary=summary, limitations=[])


def test_separate_cases_reuse_source_evidence_without_cross_owner_access(tmp_path):
    store = CaseStore(tmp_path / "cases.sqlite3")
    first = case_input("first").model_copy(update={"evidence": [evidence(summary="First case metadata")]})
    second = case_input("second").model_copy(update={"evidence": [evidence(summary="Second case metadata")]})
    store.create_case(OWNER, first)
    store.create_case(OTHER_OWNER, second)
    a = store.owner_snapshot(OWNER, "first").evidence[0]
    b = store.owner_snapshot(OTHER_OWNER, "second").evidence[0]
    assert a.evidence_id == b.evidence_id == "ev-stable-source"
    assert a.source_id == b.source_id == "costar:synthetic-property"
    assert a.summary == "First case metadata" and b.summary == "Second case metadata"
    for actor, case_id in ((OWNER, "second"), (OTHER_OWNER, "first")):
        with pytest.raises(PlatformError) as error:
            store.owner_snapshot(actor, case_id)
        assert error.value.status == 404


def test_add_evidence_duplicate_check_is_case_scoped(tmp_path):
    store = CaseStore(tmp_path / "cases.sqlite3")
    store.create_case(OWNER, case_input("first"))
    store.create_case(OTHER_OWNER, case_input("second"))
    shared = evidence()
    first = store.add_evidence(OWNER, "first", shared, 1)
    second = store.add_evidence(OTHER_OWNER, "second", shared, 1)
    assert first.analysis_revision == second.analysis_revision == 2
    with pytest.raises(PlatformError) as error:
        store.add_evidence(OWNER, "first", shared, first.case_revision)
    assert error.value.code == "evidence_exists"
    with pytest.raises(PlatformError) as error:
        store.add_evidence(OWNER, "second", evidence("new-source"), second.case_revision)
    assert error.value.status == 404


def test_v2_migration_preserves_v1_evidence_json_and_case_state(tmp_path):
    path = tmp_path / "v1.sqlite3"
    original = evidence()
    original_json = original.model_dump_json()
    original_row = (original.evidence_id, "old-case", None, original_json, "2026-11-14T00:00:00Z")
    seed = case_input("old-case").model_copy(update={"mode_label": "Scenario exercise"})
    summary = seed.model_dump(exclude={"evidence", "locations"})
    with sqlite3.connect(path) as conn:
        conn.executescript(MIGRATIONS[0])
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
                     ("old-case", OWNER.actor_id, 7, 3, json.dumps(summary), "2026-11-14", "2026-11-14"))
        conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?)", original_row)
    store = CaseStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert conn.execute("SELECT * FROM evidence").fetchone() == original_row
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    old = store.owner_snapshot(OWNER, "old-case")
    assert old.case.case_revision == 7 and old.case.analysis_revision == 3
    assert old.evidence[0].model_dump() == original.model_dump()
    store.create_case(OWNER, case_input("new-case").model_copy(update={"evidence": [original]}))
    assert len(store.owner_snapshot(OWNER, "new-case").evidence) == 1
    reopened = CaseStore(path)
    assert len(reopened.owner_snapshot(OWNER, "old-case").evidence) == 1
