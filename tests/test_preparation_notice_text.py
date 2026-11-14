from copy import deepcopy

from backend.preparation_notices import correct_notice, correct_plan_notices


def notice(body):
    return {"id": "M1", "kind": "notice", "to": "Residents", "subject": "Prepare by tomorrow evening", "body": body, "action_ids": ["A1"]}


def hurricane():
    return {"name": "Hurricane Beryl", "kind": "hurricane", "replay": True, "forecast_issued": "2024-07-06T21:00:00Z",
            "hours_left": 38.8, "at_this_site": {"peak_wind_mph": 45, "hours_until_tropical_storm_wind": 38.8}}


def test_forecast_is_sustained_source_number_and_issue_relative_not_invented_deadline():
    out = correct_notice(notice("Gusts could reach 45 mph.\nPlease finish by tomorrow evening.\n1. Close and lock your sliding glass door and windows."), hurricane())
    assert "sustained winds near 45 mph" in out["body"]
    assert "2024-07-06T21:00:00Z" in out["body"]
    assert "38.8 hours remained" in out["body"]
    assert "SCENARIO EXERCISE" in out["body"]
    assert "tomorrow" not in out["body"] + out["subject"]
    assert "Gusts could reach" not in out["body"]
    assert "sliding glass door" in out["body"]


def test_removes_unconfirmed_operations_and_parking_but_retains_specific_resident_actions():
    body = """What building staff are doing this weekend
- Placing sandbags at the lobby.
- Closing the fitness center and training room.
What we ask of you
1. Windows: close your blinds near the south-facing glass.
2. Park on a middle level of the parking garage. The covered parking is fine to use.
3. The pools and clubhouse are closed until further notice. Pool furniture will be put away.
4. Staff: plan for your people to work from home Monday and until we confirm the building has reopened.
5. Floors: lift computers and files off the floor.
"""
    out = correct_notice(notice(body), hurricane())["body"]
    for forbidden in ("Placing sandbags", "Closing the fitness", "fine to use", "middle level", "are closed", "Staff are", "work from home", "furniture will be put away"):
        assert forbidden not in out
    assert "south-facing glass" in out and "lift computers and files" in out


def test_grill_fuel_rule_is_noncontradictory_and_idempotent():
    body = """1. Bring everything inside from patios, balconies and stair landings: chairs, grills, plants, bikes and toys.
2. Move anything stored against the wood fences (boxes, bins, propane cylinders) to a safe spot away from the building, or bring it inside.
3. Close and lock windows.
"""
    out = correct_notice(notice(body), hurricane())
    assert "chairs, plants, bikes and toys" in out["body"]
    assert "or bring it inside" not in out["body"]
    assert "Do not bring grills, fuel or propane cylinders indoors." in out["body"]
    assert correct_notice(out, hurricane()) == out


def test_wildfire_keeps_gust_semantics_and_conditional_warning():
    threat = {"kind": "wildfire", "name": "Santa Ana", "replay": True, "forecast_issued": "2025-01-05T22:40:00Z",
              "at_this_site": {"gust_mph": 80, "in_warning": True, "hours_until_warning": 43.3}}
    out = correct_notice(notice("1. Keep shared courtyard walkways clear.\n2. Follow official evacuation orders right away."), threat)
    assert "gusts up to 80 mph" in out["body"]
    assert "43.3 hours remained" in out["body"]
    assert "does not establish that a fire is burning" in out["body"]
    assert "sustained" not in out["body"]
    assert "shared courtyard walkways" in out["body"]


def test_missing_forecast_is_not_zero_or_a_new_deadline():
    out = correct_notice(notice("1. Charge your phone."), {"kind": "hurricane", "at_this_site": {"peak_wind_mph": float("nan")}})
    assert "estimate is unavailable" in out["body"]
    assert "0 mph" not in out["body"] and "hours remained" not in out["body"]
    assert "SCENARIO EXERCISE" not in out["body"]


def test_plan_replay_matches_preview_without_mutating_cache_or_work_orders():
    msg = notice("1. Bring everything in from your balcony: chairs, tables, grills, plants.")
    work = {"id": "M2", "kind": "work_order", "body": "Proposed roofer scope"}
    plan = {"threat": hurricane(), "messages": [msg, work], "events": [{"type": "message", "t": 1, "message": deepcopy(msg)}, {"type": "message", "t": 2, "message": deepcopy(work)}]}
    original = deepcopy(plan)
    out = correct_plan_notices(plan)
    assert out["events"][0]["message"] == out["messages"][0] == correct_notice(msg, hurricane())
    assert out["messages"][0]["id"] == "M1" and out["messages"][0]["action_ids"] == ["A1"]
    assert out["messages"][1] == work
    assert plan == original
    assert correct_plan_notices(out) == out


def test_cover_is_not_a_grill_and_loose_item_list_remains_grammatical():
    msg = notice("1. Clear your balcony or patio. Bring inside every chair, table, grill cover, planter, bike, decoration and anything else that could blow away.")
    out = correct_notice(msg, hurricane())
    assert "Bring inside chairs, tables, grill covers, planters, bikes, decorations and other small loose items that could blow away" in out["body"]
    assert "table cover" not in out["body"] and "small loose items else" not in out["body"]
    assert correct_notice(out, hurricane()) == out
