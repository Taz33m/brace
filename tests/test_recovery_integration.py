"""Synthetic test-only evidence through the real source/valuation/agent boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import re
from threading import Event, Lock
from types import SimpleNamespace

from backend.recovery.domain.agent import RecoveryAgent
from backend.recovery.domain.service import AssessmentService, make_case_seed, screen_case, valuation_inputs
from tests.test_recovery_valuation import financial, inputs, observation


def fixture_case():
    """All records and prices here are explicit synthetic test data, never demo data."""
    inventory = inputs()
    for sale in inventory["sales"]:
        inventory["evidence"].append({"evidence_id": sale["comp_id"], "source_id": sale["comp_id"],
                                      "kind": "costar_record", "effective_at": sale["transaction_date"],
                                      "available_at": sale["available_at"]})
    for evidence in inventory["evidence"]:
        evidence.update(source_label="Synthetic integration fixture", captured_at=None,
                        received_at="2026-11-14T12:00:00Z", model_created_at=None, location=None,
                        media=None, summary="Synthetic test-only evidence", limitations=[])
    snapshot = make_case_seed(inventory, incident_name="Synthetic test incident", incident_at="2026-11-01",
                              assessment_as_of="2026-11-14", mode="scenario_exercise", case_id="case-test")
    snapshot["observations"] = [observation("reported")]
    snapshot["observations"][0].update(title="Reported damage", description="Synthetic report", basis="reported",
                                       observed_at="2026-11-12", updated_at="2026-11-14T12:00:00Z")
    snapshot["reports"] = [{"report_id": "report-test", "household_id": "test-household", "category": "roof",
                            "text": "Synthetic test report", "location": observation()["location"],
                            "location_description": "Roof A", "observed_at": "2026-11-12",
                            "received_at": "2026-11-14T12:00:00Z", "status": "reported", "media": [],
                            "public_status_detail": "Awaiting review"}]
    return inventory, snapshot


def fields(interface):
    contract = (Path(__file__).resolve().parents[1] / "docs/recovery-handoffs/shared-contract.ts").read_text()
    body = re.search(rf"export interface {interface} \{{(.*?)\n\}}", contract, re.S).group(1)
    return set(re.findall(r"^  (\w+)\??:", body, re.M))


def assert_valuation_wire(value, evidence):
    assert set(value) == fields("ValuationResult")
    known = {row[key] for row in evidence for key in ("evidence_id", "source_id")}
    for name in ("benchmark", "current_condition", "after_repair", "repair_cost", "downtime_cost"):
        assert set(value[name]) == fields("MoneyRange")
        assert set(value[name]["source_ids"]) <= known
    for key, interface in (("comparables", "Comparable"), ("repair_lines", "RepairLine"), ("assumptions", "Assumption")):
        for row in value[key]:
            assert set(row) == fields(interface)
            assert set(row["source_ids"]) <= known
    json.dumps(value, allow_nan=False)


def verify_report(snapshot):
    snapshot["case"]["analysis_revision"] += 1
    snapshot["case"]["case_revision"] += 1
    snapshot["reports"][0]["status"] = "verified"
    snapshot["observations"][0].update(status="verified", verified_by="test-reviewer", verification_note="Reviewed test evidence")


def test_full_financial_flow_changes_only_after_verification_and_correction():
    inventory, snapshot = fixture_case()
    assert set(snapshot) == fields("OwnerCaseView")
    assert set(snapshot["case"]) == fields("RecoveryCaseSummary")
    supplied = financial()
    before = screen_case(snapshot, valuation_inputs(inventory, snapshot, supplied))
    assert before["kind"] == "deterministic_screen"
    assert before["valuation"]["current_condition"]["low"] is None
    assert_valuation_wire(before["valuation"], snapshot["evidence"])
    verify_report(snapshot)
    after = screen_case(snapshot, valuation_inputs(inventory, snapshot, supplied))
    assert after["base_analysis_revision"] == 2
    assert after["valuation"]["basis"] == "conditional"
    assert after["valuation"]["current_condition"]["low"] == 997787.4
    assert_valuation_wire(after["valuation"], snapshot["evidence"])
    supplied["repairs"][0]["quantity"] = 21
    snapshot["case"]["analysis_revision"] += 1
    corrected = screen_case(snapshot, valuation_inputs(inventory, snapshot, supplied))
    assert corrected["valuation"]["current_condition"]["low"] == 997575.3
    assert corrected["valuation"]["repair_cost"]["high"] == 424.2
    assert after["valuation"]["repair_cost"]["high"] == 212.1  # prior snapshot unchanged
    assert_valuation_wire(corrected["valuation"], snapshot["evidence"])


def test_case_evidence_correction_overrides_original_inventory():
    inventory, snapshot = fixture_case()
    verify_report(snapshot)
    snapshot["evidence"] = [e for e in snapshot["evidence"] if e["evidence_id"] != "quote"]
    value = screen_case(snapshot, valuation_inputs(inventory, snapshot, financial()))["valuation"]
    assert value["repair_cost"]["low"] is None and value["current_condition"]["low"] is None
    assert any(e["evidence_id"] == "quote" for e in inventory["evidence"])


def test_real_agent_and_valuation_commit_old_run_as_stale_after_new_report():
    inventory, snapshot = fixture_case()
    verify_report(snapshot)
    started, proceed = Event(), Event()

    class Store:
        def __init__(self):
            self.snapshot, self.results, self.lock = snapshot, [], Lock()

        def snapshot_for_analysis(self, case_id):
            with self.lock:
                return deepcopy(self.snapshot)

        def complete_assessment(self, run_id, revision, result):
            with self.lock:
                if self.snapshot["case"]["analysis_revision"] != revision:
                    result["assessment"]["status"] = "stale"
                self.results.append(deepcopy(result))
                return result

    class Script:
        def __init__(self, run_id):
            self.run_id = run_id
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            started.set()
            assert proceed.wait(3)
            calls = [("get_case", {}), ("list_evidence", {}),
                     ("resolve_question", {"question_id": f"{self.run_id}:question:1", "status": "resolved",
                                           "conclusion": "Authorized reviewer verified the test observation.",
                                           "basis": "inferred", "evidence_ids": ["inspection"]}),
                     ("calculate_valuation", {}),
                     ("draft_notice", {"title": "Test update", "body": "Review remains in progress.", "source_ids": ["inspection"]}),
                     ("finish", {"headline": "Review the repair scenario", "summary": "Conditional estimate ready for review."})]
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id=str(i), name=name, input=args) for i, (name, args) in enumerate(calls)])

    store = Store()
    service = AssessmentService(store, lambda frozen: (valuation_inputs(inventory, frozen, financial()), None),
                                agent_factory=lambda frozen, args, **kw: RecoveryAgent(frozen, args, client=Script(frozen["run_id"]), **kw))
    try:
        pending = service.launch({"run_id": "run-test", "case_id": "case-test", "base_analysis_revision": 2})
        assert started.wait(3)
        with store.lock:
            store.snapshot["case"]["analysis_revision"] = 3
            store.snapshot["reports"].append({**snapshot["reports"][0], "report_id": "new-report", "status": "reported"})
        proceed.set()
        result = pending.result(3)
        assert set(result["assessment"]) == fields("Assessment")
        assert result["assessment"]["status"] == "stale"
        assert result["assessment"]["base_analysis_revision"] == 2
        assert result["assessment"]["published_at"] is None
        assert result["assessment"]["valuation"]["current_condition"]["low"] == 997787.4
        assert result["draft_notices"][0]["requires_owner_review"] is True
        assert len(store.results) == 1 and snapshot["current_assessment_id"] is None
        assert_valuation_wire(result["assessment"]["valuation"], snapshot["evidence"])
    finally:
        proceed.set()
        service.close()
