"""What changes in a plan when the forecast clock moves: a comparison of two saved plans, not a new run."""
from backend import clock


def action(aid, title, timing, crew, hours, low=0, high=0):
    return {"id": aid, "title": title, "timing": timing, "crew": crew, "hours_of_work": hours, "cost_low": low, "cost_high": high}


EARLY = {
    "threat": {"step_id": "t36", "label": "36 hours before landfall", "hours_left": 38.8},
    "totals": {"before_arrival": {"count": 4, "cost_low": 2700, "cost_high": 9700}},
    "actions": [
        action("A2", "Check the tie-downs on every rooftop condenser on S1 and S4", "before_arrival", "roofer or HVAC contractor", 8, 1500, 6000),
        action("A1", "Cut back limbs over the S18 and S16 roofs", "before_arrival", "tree crew", 8, 1200, 3000),
        action("A3", "Stack and lock away the lounge chairs, umbrellas and tables at the pools", "before_arrival", "on-site maintenance staff", 3),
        action("A4", "Notify residents to bring in everything from balconies and patios", "before_arrival", "on-site staff and residents", 4),
        action("A9", "Repaint the fence", "capital", "painter", 12),
    ],
}
LATE = {
    "threat": {"step_id": "t12", "label": "12 hours before landfall", "hours_left": 7.5},
    "totals": {"before_arrival": {"count": 3, "cost_low": 0, "cost_high": 550}},
    "actions": [
        action("A1", "Bring in or stack and tie down all pool chairs, tables and umbrellas", "before_arrival", "on-site maintenance staff", 1.5),
        action("A2", "Warn residents of S18 and S16 to keep away from the courtyard-side rooms", "before_arrival", "on-site staff", 0.5),
        action("A5", "Ask all residents to bring in everything from balconies and patios", "before_arrival", "residents", 1),
        action("A4", "After the storm, check every condenser in the roof wells on S1", "after_event", "HVAC contractor", 6),
        action("A3", "Prune back limbs over S18's roof and the south side of S16", "after_event", "tree crew", 8),
    ],
    "messages": [{"kind": "work_order", "subject": "x"}, {"kind": "notice", "subject": "Bring in balcony items tonight", "action_ids": ["A5", "A2"]}],
}


def rows_by_before(result):
    return {r["before"]["id"]: r for r in result["rows"] if r["before"]}


def test_jobs_are_paired_by_what_they_are_not_by_their_ids():
    got = rows_by_before(clock.changes(EARLY, LATE))
    assert got["A1"]["after"]["id"] == "A3"      # the tree work: A1 in one plan, A3 in the other
    assert got["A2"]["after"]["id"] == "A4"      # the condensers
    assert got["A3"]["after"]["id"] == "A1"      # the pool furniture
    assert got["A4"]["after"]["id"] == "A5"      # the balcony notice, not the new courtyard warning


def test_a_job_that_no_longer_fits_is_deferred_with_the_time_rule_as_the_reason():
    tree = rows_by_before(clock.changes(EARLY, LATE))["A1"]
    assert tree["change"] == "deferred"
    assert tree["reason"] == ("It needs about 8 hours of work. About 1.5 hours of safe working time remain"
                              " once crews stand down 6 hours before conditions arrive.")


def test_a_job_that_still_fits_says_when_it_was_cut_down():
    got = rows_by_before(clock.changes(EARLY, LATE))
    assert got["A3"]["change"] == "still_fits" and got["A3"]["reason"] == "Cut down to what staff can do in the time left."


def test_new_and_dropped_jobs_are_listed_as_such():
    result = clock.changes(EARLY, LATE)
    assert rows_by_before(result)["A9"]["change"] == "dropped"
    new = [r for r in result["rows"] if r["change"] == "new"]
    assert [r["after"]["id"] for r in new] == ["A2"] and new[0]["before"] is None


def test_it_reports_the_clock_the_costs_and_the_notice_and_says_it_is_a_replay():
    result = clock.changes(EARLY, LATE)
    assert result["replay"] is True and "not a new inspection" in result["note"]
    assert result["from"]["before_arrival"] == {"count": 4, "cost_low": 2700, "cost_high": 9700}
    assert result["to"]["before_arrival"] == {"count": 3, "cost_low": 0, "cost_high": 550}
    assert result["to"]["safe_working_hours"] == 1.5 and result["to"]["hours_left"] == 7.5
    assert result["notice"] == {"subject": "Bring in balcony items tonight", "action_ids": ["A5", "A2"]}


def test_moving_the_clock_back_brings_work_forward():
    got = {r["before"]["id"]: r for r in clock.changes(LATE, EARLY)["rows"] if r["before"]}
    assert got["A3"]["change"] == "brought_forward" and got["A3"]["after"]["id"] == "A1"
