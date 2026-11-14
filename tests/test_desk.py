"""The storm desk's arithmetic: which work competes for a scarce crew, and the order that crew works in."""
from datetime import datetime, timezone

from backend import desk


def job(building_id, job_id, hours, people, safe=30.0, trade="tree crew"):
    return {"building_id": building_id, "building": f"B{building_id}", "job_id": job_id, "title": f"job {job_id}", "trade": trade,
            "hours": hours, "cost_low": 100, "cost_high": 300, "people": people, "safe_until_h": safe}


def test_only_an_outside_trade_is_scarce():
    assert desk.trade("Tree crew") == "tree crew" and desk.trade("roofer / renovation contractor") == "roofer"
    assert desk.trade("HVAC contractor") == "mechanical contractor"
    for crew in ("on-site maintenance (HVAC contractor to strap any found loose)", "residents (notice from the leasing office)",
                 "Building engineer", "On-site staff / landscaping", "tenant", None):
        assert desk.trade(crew) is None, crew


def test_the_crew_goes_first_where_an_hour_protects_most_people():
    got = desk.allocate([job(1, "A1", 6, 60), job(2, "A1", 3, 300), job(3, "A1", 4, 100)])
    tree = got["trades"][0]
    assert [(s["building_id"], s["start_h"], s["end_h"]) for s in tree["scheduled"]] == [(2, 0.0, 3.0), (3, 4.0, 8.0), (1, 9.0, 15.0)]   # an hour of travel between buildings
    assert tree["deferred"] == [] and tree["crews_assumed"] is True and tree["people_covered"] == 460


def test_work_that_cannot_finish_in_time_moves_to_after_the_storm_and_says_why():
    got = desk.allocate([job(1, "A1", 6, 300, safe=8), job(2, "A1", 5, 100, safe=8)])
    tree = got["trades"][0]
    assert [s["building_id"] for s in tree["scheduled"]] == [1]
    late = tree["deferred"][0]
    assert late["building_id"] == 2 and "Needs 5 working hours" in late["reason"] and "would have 1 left" in late["reason"]
    assert "moves to after the storm" in got["rule"]


def test_a_second_crew_is_the_owners_to_add_and_changes_what_fits():
    jobs = [job(1, "A1", 6, 300, safe=8), job(2, "A1", 5, 100, safe=8)]
    two = desk.allocate(jobs, crews={"tree crew": 2})["trades"][0]
    assert sorted((s["building_id"], s["crew"]) for s in two["scheduled"]) == [(1, 1), (2, 2)] and two["crews_assumed"] is False and two["deferred"] == []


def test_two_jobs_at_one_building_cost_no_travel_and_trades_do_not_compete():
    got = desk.allocate([job(1, "A1", 3, 100), job(1, "A2", 2, 100), job(1, "A3", 4, 100, trade="roofer")])
    tree, = [t for t in got["trades"] if t["trade"] == "tree crew"]
    roof, = [t for t in got["trades"] if t["trade"] == "roofer"]
    assert [(s["job_id"], s["start_h"], s["end_h"]) for s in tree["scheduled"]] == [("A2", 0.0, 2.0), ("A1", 2.0, 5.0)]
    assert roof["scheduled"][0]["start_h"] == 0.0


def test_crews_work_in_daylight_and_the_night_does_not_count():
    issued = datetime(2024, 7, 6, 21, 0, tzinfo=timezone.utc)                     # 16:00 in Houston
    windows = desk.work_windows(issued, "America/Chicago", 32.8)
    assert windows == [(0.0, 3.0), (15.0, 27.0)]                                  # Saturday 16:00 to 19:00, Sunday 07:00 to 19:00
    got = desk.allocate([job(1, "A1", 5, 500, safe=32.8), job(2, "A1", 9, 300, safe=32.8), job(3, "A1", 4, 10, safe=32.8)],
                        windows=windows, issued_local=issued.astimezone(desk.ZoneInfo("America/Chicago")))
    tree = got["trades"][0]
    first, second = tree["scheduled"]
    assert (first["start_local"], first["end_local"]) == ("Sat 16:00", "Sun 09:00")      # three hours on Saturday, two on Sunday morning
    assert (second["start_local"], second["end_local"]) == ("Sun 10:00", "Sun 19:00")    # an hour of travel, then nine hours
    assert [d["building_id"] for d in tree["deferred"]] == [3] and "would have 0 left" in tree["deferred"][0]["reason"]
    assert got["assumptions"]["working_day"] == "07:00 to 19:00 local"


# --- the desk's tools: what the agent can see and ask, and what it cannot do ------------------------
import json  # noqa: E402

import pytest  # noqa: E402

from backend import desk_agent  # noqa: E402


@pytest.fixture
def run(monkeypatch):
    rows = [{"building_id": 1, "name": "Gulf Court", "type": "Apartments", "homes": 300, "tenants": 0, "rank": 1, "hours_left": 14.0, "safe_crew_hours": 8.0,
             "reasons": [], "scans": 2, "inspectable": True, "plan_saved": True},
            {"building_id": 2, "name": "Far Court", "type": "Office", "homes": 0, "tenants": 9, "rank": 2, "hours_left": 15.0, "safe_crew_hours": 9.0,
             "reasons": [], "scans": 0, "inspectable": False, "plan_saved": False}]
    plan = {"headline": "Trim the pine.", "threat": {"hours_left": 14.0}, "leads": [{"title": "Carports", "status": "not_a_concern", "note": "Roofs complete."}],
            "actions": [{"id": "A1", "title": "Cut back the pine", "timing": "before_arrival", "crew": "tree crew", "hours_of_work": 6, "cost_low": 800, "cost_high": 2000, "basis": "seen"},
                        {"id": "A2", "title": "Residents clear balconies", "timing": "before_arrival", "crew": "residents", "hours_of_work": 1, "cost_low": 0, "cost_high": 0, "basis": "seen"}],
            "messages": [{"kind": "notice", "subject": "Storm preparation", "action_ids": ["A2"]}]}
    monkeypatch.setattr(desk, "portfolio", lambda scenario, step, limit=None: rows)
    monkeypatch.setattr(desk, "saved_plan", lambda pid, scenario, step: plan if pid == 1 else None)
    monkeypatch.setattr(desk.hazards, "scenario", lambda scenario, step=None: {"name": "Hurricane Test", "city": "Nowhere", "issued": None})
    return desk_agent.DeskRun("storm", "s12")


def test_the_desk_sees_the_whole_portfolio_and_which_buildings_have_a_plan(run):
    seen = json.loads(run.tools()["forecast"]())
    assert seen["buildings_touched"] == 2 and seen["with_a_saved_plan"] == 1 and seen["can_be_inspected"] == 1
    assert [b["building_id"] for b in seen["buildings"]] == [1, 2]
    brief = json.loads(run.tools()["building_plan"](1))
    assert [(j["id"], j["outside_trade"]) for j in brief["jobs"]] == [("A1", "tree crew"), ("A2", None)]
    assert brief["notice_waiting"] == {"subject": "Storm preparation", "covers_jobs": ["A2"]} and brief["set_aside"][0]["concern"] == "Carports"
    assert run.tools()["building_plan"](2).startswith("No plan is saved")


def test_the_desk_reports_the_crew_rule_and_can_ask_what_a_second_crew_buys(run):
    one = json.loads(run.tools()["schedule_crews"]([1]))
    assert one["trades"][0]["trade"] == "tree crew" and one["trades"][0]["crews"] == 1 and len(one["trades"][0]["scheduled"]) == 1
    two = json.loads(run.tools()["schedule_crews"]([1], {"tree crew": 2}))
    assert two["trades"][0]["crews"] == 2 and two["trades"][0]["crews_assumed"] is False
    assert [s["crews"] for s in run.schedules] == [{}, {"tree crew": 2}]


def test_the_desk_can_only_ask_the_owner_and_never_publishes(run):
    t = run.tools()
    assert set(t) == {"forecast", "building_plan", "measurements", "resident_messages", "schedule_crews", "ask_owner", "request_approval"}
    assert "Nothing has been booked" in t["ask_owner"]("Call a second tree crew?", "Covers 262 more people.", [1])
    assert "No notice is waiting" in t["request_approval"](1, "A1", "the pine")                 # A1 has no notice linked
    assert "Nothing has been published" in t["request_approval"](1, "A2", "seven hours left")
    record = run.record("Done.", {"/briefs/1.md": "Trim the pine.", "/desk.md": "Order of the day.", "/scratch.md": "x"}, {"input_tokens": 1, "output_tokens": 2}, "finished")
    assert record["for_the_owner"]["approvals"] == [{"building_id": 1, "job_id": "A2", "subject": "Storm preparation", "why_now": "seven hours left"}]
    assert record["for_the_owner"]["questions"][0]["question"] == "Call a second tree crew?"
    assert record["briefs"] == {"/briefs/1.md": "Trim the pine."} and record["order_of_the_day"] == "Order of the day."
    assert [b["building_id"] for b in record["buildings"]] == [1] and record["buildings_touched"] == 2
