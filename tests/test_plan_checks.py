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
    assert plan["complete"] and plan["checks"] == {"earlier_plan_read": False, "finish_refused": 1, "open_gaps": []}


def test_a_gap_the_planner_never_closes_is_recorded_on_the_plan_not_hidden(imagery, threat):
    pine = tool("add_action", lead_id="L1", title="Tree crew: assess the tall pine beside S1", hazard="wind", timing="after_event", hours_of_work=4,
                crew="tree crew", cost_low=800, cost_high=2500, why="Residents on that side are covered in the notice.", basis="record", structure="S1")
    plan, _ = _run(imagery, threat, [
        turn(tool("open_lead", title="Tall pine beside S1", hazard="wind", why="Measured.")), turn(pine),
        turn(tool("draft_message", kind="notice", to="Residents", subject="Storm", body="- Close your windows.", action_ids=["A1"])),
        turn(tool("finish", headline="h", summary="s")), turn(tool("finish", headline="h", summary="s")), turn(tool("finish", headline="h", summary="s")),
    ])
    assert plan["complete"] and plan["checks"]["finish_refused"] == agent_mod.MAX_FINISH_REFUSALS
    assert plan["checks"]["open_gaps"] and "never mentions a tree" in plan["checks"]["open_gaps"][0]


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


def test_a_gust_speed_is_found_but_the_forecasts_own_sentence_is_not():
    assert plan_checks.gust_figures("Sustained winds up to about 45 mph at the site, gusts about 55–60 mph.")
    assert plan_checks.gust_figures("Gusts: they run roughly 20 to 30 percent higher, so about 55 to 60 mph.")
    assert not plan_checks.gust_figures("Sustained wind is estimated at up to about 55 mph. " + plan_checks.GUST_SENTENCE)
    assert not plan_checks.gust_figures("The site estimate is sustained winds near 55 mph; this is not a gust estimate. About 7.5 hours remained before winds of 39 mph.")
    assert not plan_checks.gust_figures("Tropical-storm winds (55 mph sustained, higher gusts) arrive tonight.")


def test_taking_the_gust_speed_out_leaves_the_rest_of_the_line():
    assert plan_checks.drop_gust_figures("For Beryl (sustained winds up to about 45 mph at the site, gusts about 55–60 mph), the main job is the trees.") \
        == "For Beryl (sustained winds up to about 45 mph at the site), the main job is the trees."
    assert plan_checks.drop_gust_figures("- Gusts: the short bursts above the steady wind run roughly 20 to 30 percent higher, so about 55 to 60 mph.\n- Close your windows.") \
        == "- Gusts: the short bursts above the steady wind run roughly 20 to 30 percent higher.\n- Close your windows."
    assert plan_checks.drop_gust_figures("- Sustained winds up to about 45 mph.") == "- Sustained winds up to about 45 mph."


def test_finishing_is_refused_while_the_headline_gives_a_gust_speed(imagery, threat):
    plan, script = _run(imagery, threat, [
        turn(tool("finish", headline="Winds of 45 mph, gusts about 55 to 60 mph.", summary="s")),
        turn(tool("finish", headline="Sustained winds of about 45 mph; gusts run higher.", summary="s")),
    ])
    refused = next(iter(results_of(script.requests[1]).values()))
    assert refused.get("is_error") and "gust speed in mph" in refused["content"]
    assert plan["headline"] == "Sustained winds of about 45 mph; gusts run higher." and plan["checks"]["finish_refused"] == 1


def test_what_an_action_is_about_is_read_from_its_title_not_its_reasons():
    balcony = {"id": "A8", "title": "Ask residents to bring in balcony and patio furniture", "crew": "residents",
               "why": "A chair blown into a sliding glass door breaks it."}
    assert plan_checks.notice_gaps([balcony], [notice("- Clear your balcony or patio.", ["A8"])]) == []


def test_a_notice_line_that_is_only_a_heading_is_found():
    body = "Resident preparation:\n- Clear your balcony or patio\n- If you live next to one of our two large trees\n- Close and latch all windows.\n\nDo not bring grills indoors."
    assert plan_checks.unfinished_lines([notice(body, [])]) == ["Clear your balcony or patio", "If you live next to one of our two large trees"]
    assert plan_checks.unfinished_lines([notice("- Close and latch all windows.\n- Bring in chairs (only if conditions allow).", [])]) == []


def test_a_notice_is_for_the_people_in_the_building_and_staff_get_a_work_order(imagery, threat):
    assert plan_checks.is_staff_audience("On-site maintenance and leasing team") and plan_checks.is_staff_audience("Tree crew")
    assert not plan_checks.is_staff_audience("All residents and tenants, The Parker at Ellington") and not plan_checks.is_staff_audience("Residents")
    plan, script = _run(imagery, threat, [
        turn(tool("draft_message", kind="notice", to="Residents", subject="Storm", body="- Close your windows.", action_ids=[])),
        turn(tool("draft_message", kind="notice", to="On-site maintenance team", subject="Jobs", body="- Stack the pool chairs.", action_ids=[])),
        turn(tool("finish", headline="h", summary="s")),
    ])
    refused = next(iter(results_of(script.requests[2]).values()))
    assert refused.get("is_error") and "work_order" in refused["content"]
    assert [(m["to"], "Close your windows" in m["body"]) for m in plan["messages"]] == [("Residents", True)]     # the residents' notice was not overwritten


def test_only_the_last_draft_to_each_trade_is_kept():
    drafts = [notice("a", []), {"id": "M2", "kind": "work_order", "to": "Staff"}, {"id": "M3", "kind": "work_order", "to": "Tree crew"},
              {"id": "M4", "kind": "work_order", "to": "HVAC contractor"}, {"id": "M5", "kind": "work_order", "to": "tree crew"}]
    assert [m["id"] for m in plan_checks.without_superseded(drafts)] == ["M1", "M2", "M4", "M5"]
