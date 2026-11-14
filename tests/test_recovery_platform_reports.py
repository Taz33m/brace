from __future__ import annotations

import pytest

from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_support import OWNER, report, seeded


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


@pytest.fixture
def world(store):
    return seeded(store)


def test_report_creates_report_and_reported_observation(store, world):
    ha, _, res_a, _ = world
    receipt = store.append_report(res_a, report(selected_location_id="loc_kitchen_a"), "key-0001")
    assert receipt.duplicate is False
    assert receipt.report.household_id == ha and receipt.report.status == "reported"
    assert receipt.report.location.location_id == "loc_kitchen_a"
    view = store.owner_snapshot(OWNER, "case_test")
    assert [r.report_id for r in view.reports] == [receipt.report.report_id]
    assert view.observations[0].basis == "reported" and view.observations[0].status == "reported"
    assert view.observations[0].verified_by is None
    assert view.case.pending_reports == 1 and view.case.next_action == "Review 1 resident report"


def test_report_bumps_case_and_analysis_revisions(store, world):
    _, _, res_a, _ = world
    before = store.owner_snapshot(OWNER, "case_test").case
    receipt = store.append_report(res_a, report(), "key-0001")
    assert receipt.case_revision == before.case_revision + 1
    assert receipt.analysis_revision == before.analysis_revision + 1


def test_duplicate_retry_returns_one_report_and_original_receipt(store, world):
    _, _, res_a, _ = world
    first = store.append_report(res_a, report(), "key-0001")
    again = store.append_report(res_a, report(), "key-0001")
    assert again.duplicate is True
    assert again.report.report_id == first.report.report_id
    assert again.case_revision == first.case_revision
    view = store.owner_snapshot(OWNER, "case_test")
    assert len(view.reports) == 1 and len(view.observations) == 1
    assert view.case.case_revision == first.case_revision
    assert sum(e.type == "report.updated" for e in view.events) == 1


def test_same_key_with_altered_body_conflicts(store, world):
    _, _, res_a, _ = world
    store.append_report(res_a, report(), "key-0001")
    with pytest.raises(PlatformError) as e:
        store.append_report(res_a, report("Different text"), "key-0001")
    assert e.value.status == 409 and e.value.code == "idempotency_conflict"


def test_same_key_from_different_resident_is_independent(store, world):
    _, _, res_a, res_b = world
    a = store.append_report(res_a, report(), "key-0001")
    b = store.append_report(res_b, report(), "key-0001")
    assert a.report.report_id != b.report.report_id and b.duplicate is False


def test_missing_or_bad_idempotency_key_rejected(store, world):
    _, _, res_a, _ = world
    for key in (None, "", "short", "x" * 300):
        with pytest.raises(PlatformError) as e:
            store.append_report(res_a, report(), key)
        assert e.value.status == 422


def test_resident_cannot_report_location_of_other_household(store, world):
    _, _, res_a, _ = world
    with pytest.raises(PlatformError) as e:
        store.append_report(res_a, report(selected_location_id="loc_kitchen_b"), "key-0001")
    assert e.value.status == 422


def test_blank_text_and_bad_observed_at_rejected(store, world):
    _, _, res_a, _ = world
    for bad in (report("   "), report(observed_at="yesterday"), report(observed_at="2024-07-08T10:00:00")):
        with pytest.raises(PlatformError) as e:
            store.append_report(res_a, bad, "key-0001")
        assert e.value.status == 422
    assert store.append_report(res_a, report(observed_at="2024-07-08"), "key-0002").report.observed_at == "2024-07-08"


def test_resident_home_is_scoped_to_household(store, world):
    ha, hb, res_a, res_b = world
    store.append_report(res_a, report("A's water"), "key-0001")
    home_b = store.resident_home(res_b)
    assert home_b.reports == [] and home_b.unit_label == "B"
    assert {l.location_id for l in home_b.selectable_locations} == {"loc_kitchen_b", "loc_lobby"}
    home_a = store.resident_home(res_a)
    assert [r.text for r in home_a.reports] == ["A's water"]
    assert home_a.reports[0].public_status_detail
    assert home_a.property_name == "Synthetic Apartments" and home_a.mode == "scenario_exercise"


def test_owner_cannot_use_resident_home_and_resident_cannot_report_as_owner(store, world):
    with pytest.raises(PlatformError) as e:
        store.resident_home(OWNER)
    assert e.value.status == 403
    with pytest.raises(PlatformError):
        store.append_report(OWNER, report(), "key-0001")


def test_resident_events_are_filtered_and_household_scoped(store, world):
    _, _, res_a, res_b = world
    receipt = store.append_report(res_a, report(), "key-0001")
    owner_types = [e.type for e in store.events_after(OWNER, 0, case_id="case_test")]
    assert {"case.created", "household.added", "report.updated"} <= set(owner_types)
    a_events = store.events_after(res_a, 0)
    assert [e.type for e in a_events] == ["report.updated"]
    assert a_events[0].entity_id == receipt.report.report_id
    assert store.events_after(res_b, 0) == []
    assert store.events_after(res_a, a_events[0].event_id) == []


def test_owner_events_require_case_ownership(store, world):
    from tests.test_recovery_platform_support import OTHER_OWNER

    with pytest.raises(PlatformError) as e:
        store.events_after(OTHER_OWNER, 0, case_id="case_test")
    assert e.value.status == 404
