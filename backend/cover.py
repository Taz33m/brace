"""Is the owner's cover enough for the fit-out the schedule counted? Arithmetic only: no file, no network, no model.

The assumption, stated plainly. Commercial property policies usually carry a coinsurance clause: the amount insured
has to be at least a stated share of what the property is worth at the time of a loss. If it is less, a claim is not
paid in full. It is paid in the proportion

    amount insured / (share x value)

and never more than the amount insured. So with a value of 4,000,000, a share of 80% and cover of 2,000,000, the
clause asks for 3,200,000, the proportion is 0.625, and a loss of 1,000,000 is paid as 625,000.

The share is a parameter. It is 80% here unless the caller gives another, because 80% is the common one; the owner's
policy may state 90%, 100%, or have no such clause at all. The value is the schedule's figure for the fit-out inside
the homes, which is a range, so the check is made at both ends of it. The schedule leaves out the structure, the
common areas and anything a tenant owns, and the owner's cover may be for more than the fit-out; the check compares
only the two figures it is given. A deductible is not taken off.

Nothing here is advice. It is a sum the owner can take to their broker, and `note` drafts the words to take with it.
"""
from __future__ import annotations

import math

ENDS = ("low", "high")


def spoken(amount: float | None) -> str:
    """An amount of money as it would be said aloud: '3.3 million dollars', '620 thousand dollars'. Unknown money is 'not known', never zero."""
    if amount is None:
        return "not known"
    if amount >= 999_500:
        return f"{amount / 1e6:.1f}".removesuffix(".0") + " million dollars"
    if amount >= 10_000:
        return f"{round(amount / 1e3):,} thousand dollars"
    return f"{round(amount):,} dollars"


def _written(amount: float | None) -> str:
    """An amount of money as it is written in a letter. Unknown money is 'not known', never '$0'."""
    return "not known" if amount is None else f"${amount:,.0f}"


def _range(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "not known"
    return _written(low) if low == high else f"{_written(low)} to {_written(high)}"


def _percent(part: float | None) -> str:
    """A share as a percentage, without a trailing '.0': 0.8 is '80', 0.625 is '62.5'."""
    return "not known" if part is None else f"{part * 100:.1f}".removesuffix(".0")


def _amount(x) -> bool:
    """A real amount above zero: a number, not a word, not missing, not endless."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def check(total: dict, cover: float, share: float = 0.8, loss: float | None = None) -> dict:
    """Check an amount of cover against the schedule's total, at both ends of its range.

    `total` is the schedule's `total`: `{"low": ..., "high": ...}`. `cover` is the amount insured, `share` the share of
    the value the policy asks for, `loss` the size of the example claim (the smaller of 1,000,000 and the low figure
    when not given). At each end: what the clause asks for, whether the cover meets it, how far short it is, and the
    share of a claim that is paid. Money that cannot be worked out is refused, not returned as zero.
    """
    low, high = (total or {}).get("low"), (total or {}).get("high")
    if not _amount(low) or not _amount(high):
        raise ValueError("the schedule has no priced total to check the cover against")
    low, high = min(low, high), max(low, high)
    if not _amount(cover):
        raise ValueError("the cover must be an amount of money above zero")
    if not _amount(share) or share > 1:
        raise ValueError("the share must be above 0 and no more than 1, for example 0.8 for 80%")
    if loss is None:
        loss = min(1_000_000, low)
    if not _amount(loss):
        raise ValueError("the example loss must be an amount of money above zero")

    ends, paid = {}, {}
    for end, value in zip(ENDS, (low, high)):
        required = share * value
        part = min(1.0, cover / required)
        ends[end] = {"value": round(value), "required": round(required), "enough": cover >= required, "short_by": round(max(0.0, required - cover)), "paid_share": round(part, 3)}
        paid[end] = round(min(loss * part, cover))

    short = [end for end in ENDS if not ends[end]["enough"]]
    verdict = "covers the whole range" if not short else "short across the range" if len(short) == 2 else "short at the top of the range"
    if not short:
        say = f"Cover of {spoken(cover)} is at least {_percent(share)} percent of the value at both ends of the range, so the usual clause takes nothing off a claim."
    elif low == high:
        say = f"Cover of {spoken(cover)} is {spoken(ends['low']['short_by'])} short of the {spoken(ends['low']['required'])} the usual clause asks for, so a claim is paid at {_percent(ends['low']['paid_share'])} percent."
    elif len(short) == 2:
        say = (f"Cover of {spoken(cover)} is short across the range, by {spoken(ends['low']['short_by'])} at the low end and {spoken(ends['high']['short_by'])} at the high end, "
               f"so a claim is paid at between {_percent(ends['high']['paid_share'])} and {_percent(ends['low']['paid_share'])} percent.")
    else:
        say = f"Cover of {spoken(cover)} is enough at the low end of the range but {spoken(ends['high']['short_by'])} short at the high end, where a claim is paid at {_percent(ends['high']['paid_share'])} percent."
    return {"cover": round(cover), "share": share, **ends, "example": {"loss": round(loss), **paid}, "verdict": verdict, "say": say}


def note(schedule: dict, result: dict) -> str:
    """A short draft from the owner to their broker: the figure, how it was reached, the cover, what the check found, and what is not counted.

    It is a draft and says so. `schedule` is what `schedule.schedule` returned and `result` what `check` returned; anything
    missing from either is written as 'not known'.
    """
    schedule, result = schedule or {}, result or {}
    prop, total, example = schedule.get("property") or {}, schedule.get("total") or {}, result.get("example") or {}
    name, share = prop.get("name") or "the property", result.get("share")
    of_value = f"{_percent(share)}%" if _amount(share) else "a share that is not known"
    lines = [f"To the broker for {name}" + (f", {prop['address']}" if prop.get("address") else ""), "",
             f"The fit-out inside the homes at {name} is put at {_range(total.get('low'), total.get('high'))} to replace."
             + (f" That is for {prop['homes']:,} homes." if prop.get("homes") else ""), "",
             "How the figure was reached"]
    kinds = schedule.get("kinds_of_home") or []
    for k in kinds:
        how = "the scanned home" if k.get("scanned") else "scaled from the scanned home by floor area" if "scaled" in (k.get("basis") or "") else "taken to be like the scanned home"
        per = k.get("per_home") or {}
        homes = f"{k['homes']:,} homes" if k.get("homes") is not None else "Homes not known"
        lines.append(f"- {homes}, {k.get('name') or 'kind not known'}: {how}. A home: {_range(per.get('low'), per.get('high'))}. In all: {_range(k.get('low'), k.get('high'))}.")
    if not kinds:
        lines.append("- not known")
    lines += ["", f"Cover stated: {_written(result.get('cover'))}", "", "What the check found",
              f"The usual coinsurance clause asks for cover of at least {of_value} of the value at the time of a loss. When cover is less, a claim is paid in the proportion cover / (share x value)."]
    for end in ENDS:
        e = result.get(end) or {}
        found = ("The cover meets it." if e.get("enough") else f"The cover is {_written(e.get('short_by'))} short, and a claim is paid at {_percent(e.get('paid_share'))}%." if e.get("enough") is False else "Whether the cover meets it is not known.")
        lines.append(f"- At the {end} figure, {_written(e.get('value'))}: the clause asks for {_written(e.get('required'))}. {found}")
    lines += [f"- For example, on a loss of {_written(example.get('loss'))}: {_written(example.get('low'))} is paid at the low figure and {_written(example.get('high'))} at the high figure.",
              "In short: " + ("not known." if not result.get("verdict") else "the cover meets the clause across the whole range." if not str(result["verdict"]).startswith("short") else f"the cover is {result['verdict']}."),
              f"The share is taken as {of_value}. The policy may state another, or have no such clause. Please confirm the share and the amount insured for the fit-out.",
              "This is arithmetic on the figures above, not advice.", "",
              "Not counted in the figure"]
    lines += [f"- {x}" for x in schedule.get("not_counted") or ["not known"]]
    lines += ["", "Draft. Nothing is sent until the owner sends it."]
    return "\n".join(lines)
