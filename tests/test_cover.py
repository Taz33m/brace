"""The cover check is arithmetic that can be done by hand: cover against a share of the value, at both ends of the range."""
import pytest

from backend import cover


def test_cover_below_the_share_is_paid_in_proportion():
    r = cover.check({"low": 4_000_000, "high": 4_000_000}, 2_000_000, share=0.8, loss=1_000_000)
    for end in ("low", "high"):                                                             # 80% of 4,000,000 is 3,200,000; 2,000,000 / 3,200,000 is 0.625
        assert r[end] == {"value": 4_000_000, "required": 3_200_000, "enough": False, "short_by": 1_200_000, "paid_share": 0.625}
    assert r["example"] == {"loss": 1_000_000, "low": 625_000, "high": 625_000} and r["verdict"] == "short across the range"
    assert (r["cover"], r["share"]) == (2_000_000, 0.8)
    assert r["say"] == "Cover of 2 million dollars is 1.2 million dollars short of the 3.2 million dollars the usual clause asks for, so a claim is paid at 62.5 percent."


def test_cover_at_or_above_the_share_is_paid_in_full():
    r = cover.check({"low": 4_000_000, "high": 5_000_000}, 4_000_000, loss=1_000_000)       # the clause asks for 3,200,000 and 4,000,000; the cover is exactly the second
    assert r["low"]["enough"] and r["high"]["enough"] and r["high"]["required"] == 4_000_000
    assert (r["low"]["short_by"], r["high"]["short_by"], r["low"]["paid_share"], r["high"]["paid_share"]) == (0, 0, 1.0, 1.0)
    assert r["example"] == {"loss": 1_000_000, "low": 1_000_000, "high": 1_000_000} and r["verdict"] == "covers the whole range"
    assert "takes nothing off a claim" in r["say"] and "will" not in r["say"].split()


def test_a_range_can_be_covered_at_the_low_end_and_short_at_the_high_end():
    r = cover.check({"low": 2_000_000, "high": 5_000_000}, 2_000_000)                       # asks for 1,600,000 and 4,000,000
    assert r["low"]["enough"] and not r["high"]["enough"] and r["verdict"] == "short at the top of the range"
    assert r["high"] == {"value": 5_000_000, "required": 4_000_000, "enough": False, "short_by": 2_000_000, "paid_share": 0.5}
    assert r["example"] == {"loss": 1_000_000, "low": 1_000_000, "high": 500_000}                # the example loss is the smaller of 1,000,000 and the low figure
    assert r["say"] == "Cover of 2 million dollars is enough at the low end of the range but 2 million dollars short at the high end, where a claim is paid at 50 percent."


def test_the_share_is_the_callers_and_a_claim_is_never_paid_above_the_cover():
    assert cover.check({"low": 1_000_000, "high": 1_000_000}, 900_000, share=1.0)["low"] == {"value": 1_000_000, "required": 1_000_000, "enough": False, "short_by": 100_000, "paid_share": 0.9}
    assert cover.check({"low": 1_000_000, "high": 1_000_000}, 900_000, share=0.9)["verdict"] == "covers the whole range"
    r = cover.check({"low": 600_000, "high": 600_000}, 300_000, loss=5_000_000)             # asks for 480,000; 0.625 of the loss is 3,125,000, but the cover is 300,000
    assert r["low"]["paid_share"] == 0.625 and r["example"] == {"loss": 5_000_000, "low": 300_000, "high": 300_000}
    assert cover.check({"low": 600_000, "high": 900_000}, 300_000)["example"]["loss"] == 600_000      # a low figure under 1,000,000 is the example loss
    third = cover.check({"low": 3_000_000, "high": 3_000_000}, 2_000_000, loss=1_000_000)   # 2,000,000 / 2,400,000: the share shown is rounded, the money is not worked from the rounded share
    assert third["low"]["paid_share"] == 0.833 and third["example"]["low"] == 833_333


@pytest.mark.parametrize("total, amount, kw", [
    ({"low": None, "high": None}, 1_000_000, {}), ({"low": 1_000_000, "high": None}, 1_000_000, {}), ({}, 1_000_000, {}), (None, 1_000_000, {}), ({"low": 0, "high": 0}, 1_000_000, {}),
    ({"low": 1, "high": 2}, 0, {}), ({"low": 1, "high": 2}, -5, {}), ({"low": 1, "high": 2}, None, {}), ({"low": 1, "high": 2}, "2000000", {}), ({"low": 1, "high": 2}, float("nan"), {}),
    ({"low": 1, "high": 2}, 1, {"share": 0}), ({"low": 1, "high": 2}, 1, {"share": 1.2}), ({"low": 1, "high": 2}, 1, {"share": 80}), ({"low": 1, "high": 2}, 1, {"loss": 0}), ({"low": 1, "high": 2}, 1, {"loss": -1}),
])
def test_what_cannot_be_checked_is_refused_and_never_worked_out_as_zero(total, amount, kw):
    with pytest.raises(ValueError):
        cover.check(total, amount, **kw)


def test_a_schedule_with_no_priced_total_says_so():
    with pytest.raises(ValueError, match="no priced total"):
        cover.check({"low": None, "high": None}, 1_000_000)


def test_money_is_said_as_it_would_be_spoken_and_unknown_money_is_not_zero():
    assert [cover.spoken(n) for n in (3_300_000, 620_000, 4_000_000, 9_400, 999_600)] == ["3.3 million dollars", "620 thousand dollars", "4 million dollars", "9,400 dollars", "1 million dollars"]
    assert cover.spoken(None) == "not known"


SCHEDULE = {"property": {"name": "Hill Court", "address": "1 Hill Rd", "homes": 132}, "total": {"low": 3_300_000, "high": 8_300_000},
            "kinds_of_home": [{"name": "2 Bedroom", "homes": 73, "per_home": {"low": 25_715, "high": 64_730}, "low": 1_877_195, "high": 4_725_290, "scanned": True, "basis": "the scanned home"},
                              {"name": "1 Bedroom", "homes": 59, "per_home": {"low": None, "high": None}, "low": None, "high": None, "scanned": False,
                               "basis": "the scanned home's figure scaled by floor area (725 sq ft against 775); no home of this kind was scanned"}],
            "not_counted": ["Furniture and anything a tenant owns", "Ceilings"]}


def test_the_note_to_the_broker_carries_the_figures_how_they_were_reached_and_that_it_is_a_draft():
    text = cover.note(SCHEDULE, cover.check(SCHEDULE["total"], 3_000_000))
    lines = text.splitlines()
    assert lines[0] == "To the broker for Hill Court, 1 Hill Rd" and lines[-1] == "Draft. Nothing is sent until the owner sends it."
    assert "is put at $3,300,000 to $8,300,000 to replace. That is for 132 homes." in text and "Cover stated: $3,000,000" in lines
    assert "- 73 homes, 2 Bedroom: the scanned home. A home: $25,715 to $64,730. In all: $1,877,195 to $4,725,290." in lines
    assert "- 59 homes, 1 Bedroom: scaled from the scanned home by floor area. A home: not known. In all: not known." in lines      # unknown money is said to be unknown
    assert "- At the low figure, $3,300,000: the clause asks for $2,640,000. The cover meets it." in lines
    assert "- At the high figure, $8,300,000: the clause asks for $6,640,000. The cover is $3,640,000 short, and a claim is paid at 45.2%." in lines
    assert "- For example, on a loss of $1,000,000: $1,000,000 is paid at the low figure and $451,807 at the high figure." in lines
    assert "In short: the cover is short at the top of the range." in lines and "at least 80% of the value" in text and "not advice" in text
    assert lines[lines.index("Not counted in the figure") + 1:lines.index("Not counted in the figure") + 3] == ["- Furniture and anything a tenant owns", "- Ceilings"]
    assert "$0" not in text and " will " not in text


def test_the_note_never_writes_an_unknown_as_zero_dollars():
    bare = cover.note({}, {})                                                                 # nothing known at all: still a draft, still no made-up money
    assert "$0" not in bare and "None" not in bare and "not known" in bare and bare.endswith("Draft. Nothing is sent until the owner sends it.")
    record_only = {"property": {"name": "Hill Court"}, "total": {"low": None, "high": None}, "kinds_of_home": [{"name": "Every home on the record", "homes": 268, "per_home": {"low": None, "high": None},
                   "low": None, "high": None, "scanned": False, "basis": "the scanned home; the record does not say what kinds of home there are"}]}
    text = cover.note(record_only, cover.check({"low": 5_000_000, "high": 5_000_000}, 5_000_000))
    assert "is put at not known to replace." in text and "- 268 homes, Every home on the record: taken to be like the scanned home. A home: not known. In all: not known." in text
    assert "In short: the cover meets the clause across the whole range." in text and "$0" not in text
