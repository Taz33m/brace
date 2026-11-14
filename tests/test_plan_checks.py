"""The plan and its notice must agree; a later plan must read the earlier one. Both are enforced before the planner may finish."""
import json

from backend import agent as agent_mod
from backend import hazards, plan_checks
from tests.test_agent import Script, imagery, results_of, tool, turn  # noqa: F401  (imagery is a fixture)

PINE = {"id": "A3", "title": "Tree crew: assess the tall pine at the south wall", "crew": "tree crew",
        "why": "Nothing safe can be done before the winds, so the residents on that side are covered in the notice."}
BALCONY = {"id": "A7", "title": "Residents bring in balcony and patio furniture", "crew": "residents", "why": "Only residents can clear them."}
STAFF = {"id": "A6", "title": "Stack the pool chairs", "crew": "on-site staff", "why": "Loose chairs become debris."}


def notice(body, ids):
    return {"id": "M1", "kind": "notice", "to": "Residents", "subject": "Storm", "body": body, "action_ids": ids}


def test_an_action_that_says_the_notice_covers_it_must_be_in_the_notice():
    gaps = plan_checks.notice_gaps([PINE, BALCONY, STAFF], [notice("Clear your balcony or patio.", ["A7"])])
    assert len(gaps) == 2 and all(g.startswith("A3") for g in gaps)
    assert "does not list it" in gaps[0] and "never mentions a tree" in gaps[1]


def test_a_notice_that_says_it_in_a_residents_words_closes_the_gap():
    body = "Clear your balcony or patio. If you live beside the tall pine at the south end, sleep in a room away from that wall."
    assert plan_checks.notice_gaps([PINE, BALCONY, STAFF], [notice(body, ["A7", "A3"])]) == []


def test_work_done_by_staff_needs_nothing_from_the_notice():
    assert plan_checks.notice_gaps([STAFF], [notice("Charge your phone.", [])]) == []
    assert plan_checks.notice_gaps([STAFF], []) == []


def test_relying_on_a_notice_that_was_never_drafted_is_a_gap():
    assert plan_checks.notice_gaps([BALCONY], []) == ["A7 relies on a notice to the people in the building, and none is drafted."]


def _run(site, threat, turns):
    script = Script(turns)
    plan = agent_mod.Planner(site, threat, client=script).run()
    return plan, script


def test_finishing_is_refused_until_the_notice_says_what_the_action_claims(imagery, threat):
    pine = tool("add_action", lead_id="L1", title="Tree crew: assess the tall pine beside S1", hazard="wind", timing="after_event", hours_of_work=4,
                crew="tree crew", cost_low=800, cost_high=2500, why="It cannot be cut in time, so residents on that side are covered in the notice.",
                basis="record", structure="S1")
    plan, script = _run(imagery, threat, [
        turn(tool("open_lead", title="Tall pine beside S1", hazard="wind", why="Measured.")),
        turn(pine),
        turn(tool("draft_message", kind="notice", to="Residents", subject="Storm", body="- Close your windows.", action_ids=[])),
        turn(tool("finish", headline="h", summary="s")),
        turn(tool("draft_message", kind="notice", to="Residents", subject="Storm",
                  body="- Close your windows.\n- If you live beside the tall pine at the south end, sleep in a room away from that wall.", action_ids=["A1"])),
        turn(tool("finish", headline="h", summary="s")),
    ])
    refused = next(iter(results_of(script.requests[4]).values()))
    assert refused.get("is_error") and "never mentions a tree" in refused["content"]
    notices = [m for m in plan["messages"] if m["kind"] == "notice"]
    assert len(notices) == 1 and notices[0]["id"] == "M1" and "tall pine" in notices[0]["body"]      # the redraft replaced the first
    assert plan["complete"] and plan["checks"] == {"earlier_plan_read": False, "notice_redrafts_asked": 1, "notice_gaps": []}


def test_a_gap_the_planner_never_closes_is_recorded_on_the_plan_not_hidden(imagery, threat):
    pine = tool("add_action", lead_id="L1", title="Tree crew: assess the tall pine beside S1", hazard="wind", timing="after_event", hours_of_work=4,
                crew="tree crew", cost_low=800, cost_high=2500, why="Residents on that side are covered in the notice.", basis="record", structure="S1")
    plan, _ = _run(imagery, threat, [
        turn(tool("open_lead", title="Tall pine beside S1", hazard="wind", why="Measured.")), turn(pine),
        turn(tool("draft_message", kind="notice", to="Residents", subject="Storm", body="- Close your windows.", action_ids=["A1"])),
        turn(tool("finish", headline="h", summary="s")), turn(tool("finish", headline="h", summary="s")), turn(tool("finish", headline="h", summary="s")),
    ])
    assert plan["complete"] and plan["checks"]["notice_redrafts_asked"] == agent_mod.MAX_FINISH_REFUSALS
    assert plan["checks"]["notice_gaps"] and "never mentions a tree" in plan["checks"]["notice_gaps"][0]


def test_a_later_step_must_read_the_plan_made_at_the_earlier_step_and_never_a_later_one(imagery, threat, monkeypatch):
    scenario, step = threat["scenario_id"], threat["step_id"]
    monkeypatch.setattr(hazards, "scenarios", lambda include_live=True: [{"id": scenario, "steps": [{"id": "early"}, {"id": step}, {"id": "late"}]}])
    plans = imagery.dir / "plans"
    plans.mkdir(exist_ok=True)
    saved = {"complete": True, "threat": {"label": "36 hours before landfall", "hours_left": 38.8}, "headline": "Trim the tree.",
             "leads": [{"id": "L1", "title": "Carports", "hazard": "wind", "status": "not_a_concern", "note": "Roofs complete in the photos.", "action_ids": []},
                       {"id": "L2", "title": "Courtyard tree", "hazard": "wind", "status": "actions", "why": "Over the roof.", "action_ids": ["A1"]}],
             "actions": [{"id": "A1", "title": "Cut back the limbs", "timing": "before_arrival", "hours_of_work": 6, "crew": "tree crew", "cost_low": 1200, "cost_high": 3000}]}
    (plans / f"{scenario}__early.json").write_text(json.dumps(saved))
    (plans / f"{scenario}__late.json").write_text(json.dumps({**saved, "headline": "FROM THE FUTURE"}))
    plan, script = _run(imagery, threat, [
        turn(tool("finish", headline="h", summary="s")),
        turn(tool("get_earlier_plan")),
        turn(tool("finish", headline="h", summary="s")),
    ])
    refused = next(iter(results_of(script.requests[1]).values()))
    assert refused.get("is_error") and "have not read it" in refused["content"]
    told = json.loads(next(iter(results_of(script.requests[2]).values()))["content"])
    assert told["made_for"] == "36 hours before landfall" and told["headline"] == "Trim the tree."
    assert [(d["concern"], d["outcome"]) for d in told["decisions"]] == [("Carports", "looked at and set aside"), ("Courtyard tree", "in the plan")]
    assert told["decisions"][1]["actions"][0]["hours_of_work"] == 6 and "FUTURE" not in json.dumps(told)
    assert plan["complete"] and plan["checks"]["earlier_plan_read"] is True


def test_the_first_step_has_no_earlier_plan_and_finishes_without_one(imagery, threat, monkeypatch):
    monkeypatch.setattr(hazards, "scenarios", lambda include_live=True: [{"id": threat["scenario_id"], "steps": [{"id": threat["step_id"]}]}])
    plan, script = _run(imagery, threat, [turn(tool("get_earlier_plan")), turn(tool("finish", headline="h", summary="s"))])
    assert "No plan has been made" in next(iter(results_of(script.requests[1]).values()))["content"]
    assert plan["complete"]


def test_a_work_order_drafted_again_for_the_same_trade_replaces_the_first(imagery, threat):
    plan, _ = _run(imagery, threat, [
        turn(tool("draft_message", kind="work_order", to="Tree crew", subject="Trim", body="About 1.5 days.", action_ids=[]),
             tool("draft_message", kind="work_order", to="Roofer", subject="Inspect", body="After the storm.", action_ids=[])),
        turn(tool("draft_message", kind="work_order", to="tree crew", subject="Trim (corrected)", body="About 6 hours.", action_ids=[])),
        turn(tool("finish", headline="h", summary="s")),
    ])
    assert [(m["id"], m["to"], m["body"]) for m in plan["messages"]] == [("M1", "tree crew", "About 6 hours."), ("M2", "Roofer", "After the storm.")]
