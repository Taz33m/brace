"""The figure a total is led with: the middle of every line's range, and a band that is never wider than the two ends."""
import math

from backend import schedule


def unit(*lines):
    return {"rooms": [{"items": [{"what": w, "low": lo, "high": hi} for w, lo, hi in lines]}]}


def test_lines_of_different_kinds_partly_cancel_and_lines_of_one_kind_do_not():
    two_kinds = schedule._band(unit(("Toilet", 300, 700), ("Flooring", 600, 1000)))
    assert math.isclose(two_kinds, 0.5 * math.sqrt(400 ** 2 + 400 ** 2) / 1300)          # less than the 400 either side that the ends give
    one_kind = schedule._band(unit(("Flooring", 300, 700), ("Flooring", 600, 1000)))
    assert math.isclose(one_kind, 400 / 1300)                                                # the same price twice: nothing cancels


def test_the_band_sits_inside_the_two_ends_and_unknown_money_gives_no_figure():
    band = schedule._band(unit(("Toilet", 300, 700), ("Flooring", 600, 1000), ("Door", None, None)))
    got = schedule._figure({"low": 900, "high": 1700}, band)
    assert got["middle"] == 1300 and 900 < got["likely_low"] < 1300 < got["likely_high"] < 1700 and (got["low"], got["high"]) == (900, 1700)
    assert schedule._figure({"low": None, "high": None}, band)["middle"] is None and schedule._band(unit(("Door", None, None))) is None


def test_what_is_said_about_the_whole_uses_the_band():
    s = {"total": {"low": 900, "high": 1700, "middle": 1300, "likely_low": 1100, "likely_high": 1500}, "home": {"total": {"low": 9, "high": 17, "middle": 13, "likely_low": 11, "likely_high": 15}},
         "kinds_of_home": [{"low": 900, "high": 1700, "middle": 1300, "likely_low": 1100, "likely_high": 1500, "per_home": {"low": 9, "high": 17, "middle": 13, "likely_low": 11, "likely_high": 15}}]}
    b = schedule.banded(s)
    assert (b["total"]["low"], b["total"]["high"]) == (1100, 1500) and (b["kinds_of_home"][0]["per_home"]["low"], b["home"]["total"]["high"]) == (11, 15) and s["total"]["low"] == 900
