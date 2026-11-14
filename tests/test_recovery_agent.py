"""Exercise real tool sequencing without spending on model calls."""
from __future__ import annotations

import copy
import json
import sys
from types import SimpleNamespace

import pytest

from backend.recovery.domain.agent import RecoveryAgent


def tool(name, **args):
    return SimpleNamespace(type="tool_use", id=f"{name}-{id(args)}", name=name, input=args)


def turn(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class Script:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        return self.turns.pop(0)


@pytest.fixture
def snapshot():
    location = {"location_id": "space-1", "label": "Representative apartment",
                "structure_id": None, "scan_id": "scan-1", "sweep_id": "sweep-1", "room_id": "room-1",
                "unit_label": None, "binding": "representative_layout", "longitude": None,
                "latitude": None, "bearing_degrees": None}
    evidence = []
    for identity, kind in (("record-1", "costar_record"), ("aerial-1", "vexcel_image"), ("inside-1", "matterport_view")):
        evidence.append({"evidence_id": identity, "kind": kind, "source_id": f"source:{identity}",
                         "source_label": identity, "captured_at": None, "effective_at": None,
                         "available_at": None, "received_at": "2026-11-14T12:00:00Z", "model_created_at": None,
                         "location": location if kind == "matterport_view" else None, "media": None,
                         "summary": "Source description", "limitations": ["Capture date unknown"]})
    return {"run_id": "run-1", "case": {"case_id": "case-1", "analysis_revision": 5,
            "mode": "scenario_exercise", "assessment_as_of": "2026-11-14", "incident_at": "2024-07-08"},
            "evidence": evidence,
            "observations": [{"observation_id": "observation-1", "status": "reported", "location": location,
                              "evidence_ids": ["inside-1"], "title": "Reported water", "basis": "reported"}],
            "reports": [{"report_id": "report-1", "household_id": "household-1", "status": "reported",
                         "category": "water", "text": "Water by my door", "location": None}],
            "household_labels": [{"household_id": "household-1", "unit_label": "101"}]}


@pytest.fixture
def valuation(monkeypatch):
    # Keep this suite independent of financial implementation; integration tests
    # exercise the real evaluator. Assert precisely what crosses the boundary.
    calls = []
    result = {"basis": "insufficient_evidence", "limitations": ["No supported current value"]}

    def evaluate(inputs, observations, context):
        calls.append((copy.deepcopy(inputs), copy.deepcopy(observations), copy.deepcopy(context)))
        return copy.deepcopy(result)

    monkeypatch.setitem(sys.modules, "backend.recovery.domain.valuation", SimpleNamespace(evaluate_valuation=evaluate))
    return calls, result


def test_full_investigation_uses_images_and_produces_only_drafts(snapshot, valuation):
    script = Script([
        turn(tool("get_case"), tool("list_evidence")),
        turn(tool("read_evidence", evidence_id="record-1"), tool("inspect_view", evidence_id="aerial-1"),
             tool("inspect_view", evidence_id="inside-1")),
        turn(tool("resolve_question", question_id="run-1:question:1", status="needs_verification",
                  conclusion="The report needs inspection; the scan does not identify this home.", basis="inferred",
                  evidence_ids=["inside-1"])),
        turn(tool("calculate_valuation"), tool("propose_task", kind="verification", title="Inspect reported water entry",
                  scope="Arrange an authorized inspection with the reporting resident.", report_ids=["report-1"])),
        turn(tool("draft_notice", title="Recovery review", body="Reports are being reviewed. Work is proposed and awaits owner review.")),
        turn(tool("finish", headline="Verify reported water before pricing repairs", summary="The inside view is a representative layout. No damage or value change is verified.")),
    ])
    images = []

    def image(identity):
        images.append(identity)
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "test-image"}}]

    original = copy.deepcopy(snapshot)
    agent = RecoveryAgent(snapshot, {"subject": {"id": 1}}, client=script, inspect_image=image)
    snapshot["case"]["analysis_revision"] = 99
    result = agent.run()
    assert result["assessment"]["status"] == "draft"
    assert result["assessment"]["base_analysis_revision"] == 5
    assert result["assessment"]["published_at"] is None
    assert result["assessment"]["valuation"] == valuation[1]
    assert len(valuation[0]) == 1 and valuation[0][0][2]["analysis_revision"] == 5
    assert images == ["aerial-1", "inside-1"]
    task = result["proposed_tasks"][0]
    assert task["status"] == "proposed" and task["household_ids"] == ["household-1"]
    assert task["confirmed_schedule"] is None and task["confirmation_source"] is None
    assert result["draft_notices"][0]["requires_owner_review"] is True
    assert result["assessment"]["unresolved_questions"]
    assert agent.snapshot == original
    assert script.requests[0]["thinking"]["type"] == "adaptive"


@pytest.mark.parametrize("name,args,error", [
    ("read_evidence", {"evidence_id": "made-up"}, "Unknown evidence"),
    ("propose_task", {"kind": "repair", "title": "Repair", "scope": "Dry wall", "observation_ids": ["observation-1"], "evidence_ids": ["inside-1"]}, "verified observations"),
    ("resolve_question", {"question_id": "run-1:question:1", "status": "resolved", "conclusion": "Confirmed", "basis": "inferred", "evidence_ids": ["inside-1"]}, "unverified resident"),
    ("propose_task", {"kind": "verification", "title": "Inspect", "scope": "Door", "report_ids": ["report-1"], "status": "verified"}, "allowed fields"),
    ("calculate_valuation", {"damage_percent": 20}, "allowed fields"),
    ("publish_notice", {"body": "Hello"}, "Unknown recovery tool"),
    ("inspect_view", {"evidence_id": "record-1"}, "not a visual"),
    ("propose_task", {"kind": "verification", "title": "Inspect", "scope": "Door", "report_ids": ["report-1"], "location_id": "space-1"}, "not tied"),
])
def test_bad_references_and_forbidden_authority_rejected(snapshot, name, args, error):
    agent = RecoveryAgent(snapshot, {})
    result = agent._call_tool(name, args)
    assert result["is_error"] and error in result["content"]
    assert not agent.tasks and not agent.notices


def test_missing_images_never_count_as_inspected(snapshot):
    agent = RecoveryAgent(snapshot, {})
    assert agent._call_tool("inspect_view", {"evidence_id": "inside-1"})["is_error"]
    question = agent.t_open_question("Is the door damaged?", ["inside-1"])
    result = agent._call_tool("resolve_question", {"question_id": question["question_id"], "status": "resolved",
                                                   "conclusion": "Door damage visible", "basis": "observed", "evidence_ids": ["inside-1"]})
    assert result["is_error"] and "Inspect" in result["content"]
    assert agent.inspected == set()


def test_finish_requires_reading_calculation_notice_and_report_disposition(snapshot, valuation):
    agent = RecoveryAgent(snapshot, {})
    finish = {"headline": "Done", "summary": "Review"}
    assert "Read the case" in agent._call_tool("finish", finish)["content"]
    agent.t_get_case(); agent.t_list_evidence()
    assert "calculate_valuation" in agent._call_tool("finish", finish)["content"]
    agent.t_calculate_valuation()
    assert "resident notice" in agent._call_tool("finish", finish)["content"]
    agent.t_draft_notice("Update", "Reports remain under review")
    assert "Address open questions" in agent._call_tool("finish", finish)["content"]


def test_repair_requires_verified_observation_and_exact_scan_binding(snapshot):
    snapshot["observations"][0]["status"] = "verified"
    agent = RecoveryAgent(snapshot, {})
    args = dict(kind="repair", title="Repair door", scope="Scope based on inspection",
                observation_ids=["observation-1"], evidence_ids=["inside-1"], location_id="space-1")
    result = agent._call_tool("propose_task", args)
    assert result["is_error"] and "verified space binding" in result["content"]
    assert agent._call_tool("propose_task", {k: v for k, v in args.items() if k != "location_id"})["is_error"]
    for row in snapshot["observations"] + snapshot["evidence"]:
        if row.get("location"):
            row["location"]["binding"] = "verified_space"
    agent = RecoveryAgent(snapshot, {})
    result = agent._call_tool("propose_task", args)
    assert not result["is_error"]
    assert json.loads(result["content"])["status"] == "proposed"


def test_missing_layers_seed_questions_and_cannot_be_silently_omitted(snapshot, valuation):
    snapshot["evidence"] = []
    snapshot["observations"] = []
    snapshot["reports"] = []
    agent = RecoveryAgent(snapshot, {})
    assert len(agent.questions) == 3
    assert all(q["status"] == "open" for q in agent.questions)


def test_bounded_no_tools_failure_and_hidden_thinking_not_emitted(snapshot):
    script = Script([turn(SimpleNamespace(type="thinking", thinking="private internal thought"),
                         SimpleNamespace(type="text", text="unreviewed model prose"), stop="end_turn")])
    events = []
    result = RecoveryAgent(snapshot, {}, client=script, emit=events.append, max_turns=1).run()
    assert result["assessment"]["status"] == "failed"
    assert "turn limit" in result["assessment"]["failure_reason"]
    assert "private internal" not in json.dumps(events)
    assert "unreviewed model" not in json.dumps(result)


def test_provider_failure_sanitized(snapshot):
    def fail(**_):
        raise RuntimeError("secret-token private-report-body")
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fail)))
    result = RecoveryAgent(snapshot, {}, client=client).run()
    assert result["assessment"]["status"] == "failed"
    assert "secret-token" not in json.dumps(result)


def test_tool_rejection_can_be_corrected_in_next_turn(snapshot, valuation):
    script = Script([
        turn(tool("get_case"), tool("list_evidence"), tool("read_evidence", evidence_id="bad")),
        turn(tool("resolve_question", question_id="run-1:question:1", status="needs_verification", conclusion="Await inspection", basis="reported"),
             tool("calculate_valuation"), tool("draft_notice", title="Review", body="An inspection is being proposed.")),
        turn(tool("finish", headline="Review needed", summary="No verified change in value")),
    ])
    result = RecoveryAgent(snapshot, {}, client=script).run()
    assert result["assessment"]["status"] == "draft"
    tool_results = script.requests[1]["messages"][-1]["content"]
    assert any(r["is_error"] for r in tool_results)
    assert any(e["type"] == "tool.rejected" for e in result["trace"])


def test_spatial_tool_preserves_room_geometry_and_candidate_bindings(snapshot):
    loc = copy.deepcopy(snapshot["evidence"][2]["location"])
    scan = {"id": "scan-1", "name": "Model layout", "rooms": [{"id": "room-1", "polygon": [[0, 0], [1, 0], [1, 1], [0, 0]]}],
            "sweeps": [{"id": "sweep-1", "room_id": "room-1"}]}
    inputs = {"scans": [scan], "structures": [{"id": "S1", "polygon": [[0, 0], [1, 0], [1, 1], [0, 0]]}], "locations": [loc]}
    agent = RecoveryAgent(snapshot, inputs)
    info = agent.t_get_spatial_context("scan", "scan-1")
    assert info["scan"]["rooms"][0]["polygon"] == scan["rooms"][0]["polygon"]
    assert info["scan"]["sweeps"][0]["room_id"] == "room-1"
    assert info["locations"][0]["binding"] == "representative_layout"
    assert info["evidence_ids"] == ["inside-1"]
    assert "candidate" in info["limitation"]
    assert agent._call_tool("get_spatial_context", {"kind": "scan", "source_id": "fake"})["is_error"]
    assert "scans" not in agent.t_get_case()
    loc["binding"] = "verified_unit"
    with pytest.raises(ValueError, match="Conflicting location"):
        RecoveryAgent(snapshot, {**inputs, "locations": [loc]})


def test_full_loop_with_real_valuation_engine_preserves_missing_values(snapshot):
    script = Script([
        turn(tool("get_case"), tool("list_evidence"), tool("get_spatial_context", kind="inventory")),
        turn(tool("resolve_question", question_id="run-1:question:1", status="needs_verification", conclusion="An authorized inspection is needed.", basis="reported"),
             tool("calculate_valuation")),
        turn(tool("draft_notice", title="Review in progress", body="Reports are being reviewed; proposed inspections await approval.")),
        turn(tool("finish", headline="Inspection needed", summary="No current value is supported by the available financial evidence.")),
    ])
    result = RecoveryAgent(snapshot, {"subject": {"id": 1}, "sales": [], "evidence": snapshot["evidence"]}, client=script).run()
    assert result["assessment"]["status"] == "draft"
    value = result["assessment"]["valuation"]
    assert value["basis"] == "insufficient_evidence"
    assert value["current_condition"]["low"] is None
    assert value["repair_cost"]["low"] is None
    assert any("unverified" in text for text in value["limitations"])


def test_valuation_tool_bounds_real_kit_scale_while_retaining_full_output(snapshot, monkeypatch):
    comps = [{"comp_id": str(i), "included": i < 15, "reason": "Eligible" if i < 15 else "Outside market",
              "price_usd": 1000000 + i} for i in range(6120)]
    result = {"comparables": comps, "basis": "conditional", "repair_lines": [], "assumptions": [], "limitations": []}
    monkeypatch.setitem(sys.modules, "backend.recovery.domain.valuation", SimpleNamespace(evaluate_valuation=lambda *_: result))
    agent = RecoveryAgent(snapshot, {})
    compact = agent.t_calculate_valuation()
    assert len(compact["comparables"]) == 24
    assert compact["comparable_counts"] == {"total": 6120, "included": 15, "excluded": 6105}
    assert compact["exclusion_reasons"] == {"Outside market": 6105}
    assert len(json.dumps(compact)) < 10000
    assert len(agent.valuation["comparables"]) == 6120
    assert agent.t_read_comparable("6119")["comparables"][0]["comp_id"] == "6119"
    assert agent._call_tool("read_comparable", {"comp_id": "invented"})["is_error"]


def test_image_availability_preflight_avoids_unavailable_provider_calls(snapshot):
    calls = []

    def load(identity):
        calls.append(identity)
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "cached-bytes"}}]

    inputs = {"image_availability": {"aerial-1": "metadata_only", "inside-1": "requires_fetch"}}
    agent = RecoveryAgent(snapshot, inputs, inspect_image=load)
    listed = {e["evidence_id"]: e for e in agent.t_list_evidence()["evidence"]}
    assert listed["aerial-1"]["image_status"] == "metadata_only"
    assert listed["inside-1"]["image_status"] == "requires_fetch"
    assert "metadata_only" in agent.t_list_evidence()["image_guidance"]
    assert "metadata only" in agent._call_tool("inspect_view", {"evidence_id": "aerial-1"})["content"]
    assert "disabled" in agent._call_tool("inspect_view", {"evidence_id": "inside-1"})["content"]
    assert calls == [] and agent.inspected == set()
    enabled = RecoveryAgent(snapshot, {**inputs, "source_fetch_allowed": True}, inspect_image=load)
    assert not enabled._call_tool("inspect_view", {"evidence_id": "inside-1"})["is_error"]
    assert calls == ["inside-1"]
    cached = RecoveryAgent(snapshot, {"image_availability": {"inside-1": "cached"}}, inspect_image=load)
    assert not cached._call_tool("inspect_view", {"evidence_id": "inside-1"})["is_error"]


def test_usage_and_actual_models_are_traced_without_provider_thinking(snapshot):
    response = turn(SimpleNamespace(type="thinking", thinking="private provider reasoning"), stop="end_turn")
    response.model = "resolved-provider-model"
    response.usage = SimpleNamespace(input_tokens=100, output_tokens=40, cache_read_input_tokens=25,
                                    cache_creation_input_tokens=10)
    result = RecoveryAgent(snapshot, {}, client=Script([response]), max_turns=1).run()
    model = next(event for event in result["trace"] if event["type"] == "model.completed")
    completed = result["trace"][-1]
    assert model["used_model"] == "resolved-provider-model"
    assert completed["used_models"] == ["resolved-provider-model"]
    assert completed["request_count"] == 1
    assert completed["usage"] == {"input_tokens": 100, "output_tokens": 40,
                                  "cache_read_input_tokens": 25, "cache_creation_input_tokens": 10}
    assert "private provider reasoning" not in json.dumps(result)
    assert "usage" not in result["assessment"]


def paired_inputs(snapshot):
    before = copy.deepcopy(snapshot["evidence"][1])
    before.update(evidence_id="aerial-before", source_id="source:aerial-before", captured_at="2023-12-07")
    snapshot["evidence"].append(before)
    return {"subject": {"id": 1}, "sales": [], "evidence": snapshot["evidence"],
            "image_availability": {"aerial-before": "cached", "aerial-1": "cached"},
            "capture_pairs": {
                "before": {"evidence_id": "aerial-before", "collection": "before", "first_date": "2023-12-03", "last_date": "2023-12-07"},
                "after": {"evidence_id": "aerial-1", "collection": "after", "first_date": "2024-08-07", "last_date": "2024-09-28"}}}


def image_block():
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "test-image"}}]


def test_selected_pair_cannot_finish_or_resolve_comparison_until_both_images_inspected(snapshot):
    inputs = paired_inputs(snapshot)
    script = Script([
        turn(tool("get_case"), tool("list_evidence"), tool("calculate_valuation"),
             tool("draft_notice", title="Review in progress", body="Source images are being reviewed. No repairs or schedule are confirmed.")),
        turn(tool("resolve_question", question_id="run-1:question:1", status="needs_verification", conclusion="Resident report needs authorized review.", basis="reported"),
             tool("resolve_question", question_id="run-1:question:2", status="resolved", conclusion="Compared source images", basis="observed", evidence_ids=["aerial-before", "aerial-1"]),
             tool("finish", headline="Review needed", summary="No verified damage.")),
        turn(tool("inspect_view", evidence_id="aerial-before"),
             tool("finish", headline="Review needed", summary="No verified damage.")),
        turn(tool("inspect_view", evidence_id="aerial-1"),
             tool("resolve_question", question_id="run-1:question:2", status="needs_verification", conclusion="Both images inspected. Their capture windows are months apart; any apparent difference needs review and is not verified disaster damage.", basis="observed", evidence_ids=["aerial-before", "aerial-1"]),
             tool("finish", headline="Review needed", summary="Both dated aerials were inspected. Damage, causation and costs remain unverified.")),
    ])
    inspected = []
    original = copy.deepcopy(snapshot)
    agent = RecoveryAgent(snapshot, inputs, client=script, inspect_image=lambda identity: (inspected.append(identity), image_block())[1])
    result = agent.run()
    assert result["assessment"]["status"] == "draft"
    assert inspected == ["aerial-before", "aerial-1"]
    assert agent._pair_context()["ready_to_compare"] is True
    assert agent._pair_context()["after"]["first_date"] == "2024-08-07"
    assert any("both selected aerials" in item["content"] for item in script.requests[2]["messages"][-1]["content"] if item["is_error"])
    assert any("Inspect available selected aerials" in item["content"] for item in script.requests[3]["messages"][-1]["content"] if item["is_error"])
    assert result["assessment"]["valuation"]["current_condition"]["point"] is None
    assert result["assessment"]["valuation"]["repair_cost"]["point"] is None
    assert result["proposed_tasks"] == []
    assert snapshot == original


def test_failed_selected_image_stays_an_explicit_gap_without_blocking_draft_forever(snapshot):
    inputs = paired_inputs(snapshot)

    def inspect(identity):
        if identity == "aerial-1":
            raise RuntimeError("private-url-or-provider-secret")
        return image_block()

    agent = RecoveryAgent(snapshot, inputs, inspect_image=inspect)
    agent.t_get_case(); agent.t_list_evidence(); agent.t_calculate_valuation()
    agent.t_draft_notice("Review", "Source images are under review; no repairs are scheduled.")
    agent.t_resolve_question("run-1:question:1", "needs_verification", "Await review", "reported")
    agent.t_inspect_view("aerial-before")
    error = agent._call_tool("inspect_view", {"evidence_id": "aerial-1"})
    assert error["is_error"] and "private-url" not in error["content"]
    assert agent.inspected == {"aerial-before"}
    assert agent.pair_question["status"] == "needs_verification"
    assert not agent._pair_context()["ready_to_compare"]
    assert agent.t_finish("Partial review", "After image unavailable; no paired comparison or damage finding.")["status"] == "draft"
    assert "could not both be inspected" in agent.pair_question["conclusion"]


def test_missing_or_reused_pair_evidence_never_becomes_a_complete_comparison(snapshot):
    inputs = paired_inputs(snapshot)
    inputs["capture_pairs"]["after"]["evidence_id"] = "foreign-evidence"
    agent = RecoveryAgent(snapshot, inputs, inspect_image=lambda _: image_block())
    pair = agent.t_list_evidence()["pair_inspection"]
    assert pair["after"] is None and pair["ready_to_compare"] is False
    agent.t_inspect_view("aerial-before")
    result = agent._call_tool("resolve_question", {"question_id": agent.pair_question["question_id"], "status": "resolved",
        "conclusion": "Comparison complete", "basis": "observed", "evidence_ids": ["aerial-before"]})
    assert result["is_error"]
    inputs["capture_pairs"]["after"]["evidence_id"] = "aerial-before"
    same = RecoveryAgent(snapshot, inputs, inspect_image=lambda _: image_block())
    same.t_inspect_view("aerial-before")
    assert same._pair_context()["ready_to_compare"] is False
