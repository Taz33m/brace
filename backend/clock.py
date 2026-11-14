"""What changes in a building's plan when the forecast clock moves.

Each saved plan was made by the planner for one forecast step. Moving the clock does not re-run the
planner: it compares the plan made for one step with the plan made for another, so a person can see
which jobs still fit before the weather arrives and which were put off, and why.

The two plans were written independently, so the same job has different ids and wording in each. Jobs
are paired by who does them and what they say, never by id.
"""
from __future__ import annotations

import re

from .agent import CREW_STANDDOWN_HOURS

# Words that say nothing about which job it is.
_DULL = {"the", "and", "all", "any", "every", "from", "into", "over", "with", "that", "this", "them", "then", "they", "their",
         "after", "before", "once", "back", "away", "keep", "storm", "check", "again", "each", "what", "still", "site"}


def _words(text: str | None) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _DULL}


def _alike(a: dict, b: dict) -> float:
    """How likely two actions from different plans are the same job, 0 to about 1.5."""
    ta, tb = _words(a.get("title")), _words(b.get("title"))
    title = len(ta & tb) / max(1, min(len(ta), len(tb)))
    ca, cb = _words(a.get("crew")), _words(b.get("crew"))
    crew = len(ca & cb) / max(1, min(len(ca), len(cb)))
    return title + 0.5 * crew


def _brief(a: dict) -> dict:
    return {k: a.get(k) for k in ("id", "title", "timing", "crew", "hours_of_work", "cost_low", "cost_high")}


def _safe_hours(plan: dict) -> float | None:
    """Working time outdoor crews have left at this step: the hours until conditions arrive, less their stand-down."""
    left = (plan.get("threat") or {}).get("hours_left")
    return None if left is None else max(0.0, round(left - CREW_STANDDOWN_HOURS, 1))


def changes(earlier: dict, later: dict) -> dict:
    """Row by row, what became of each job between the plan made for an earlier step and for a later one."""
    was, now = list(earlier.get("actions") or []), list(later.get("actions") or [])
    # Pair the most alike first; a job is only paired when it is clearly the same one.
    scored = sorted(((_alike(a, b), i, j) for i, a in enumerate(was) for j, b in enumerate(now)), reverse=True)
    pair: dict[int, int] = {}
    taken: set[int] = set()
    for score, i, j in scored:
        if score < 0.6:
            break
        if i not in pair and j not in taken:
            pair[i] = j
            taken.add(j)

    safe = _safe_hours(later)
    rows = []
    for i, a in enumerate(was):
        b = now[pair[i]] if i in pair else None
        if b is None:
            rows.append({"change": "dropped", "before": _brief(a), "after": None,
                         "reason": "The plan made for this step does not include it."})
        elif a.get("timing") == "before_arrival" and b.get("timing") != "before_arrival":
            needs = a.get("hours_of_work")
            if safe is not None and needs is not None and needs > safe:
                why = (f"It needs about {needs:g} hours of work. About {safe:g} hours of safe working time remain"
                       f" once crews stand down {CREW_STANDDOWN_HOURS} hours before conditions arrive.")
            else:
                why = "The planner filed it for after the event at this step."
            rows.append({"change": "deferred", "before": _brief(a), "after": _brief(b), "reason": why})
        elif a.get("timing") != "before_arrival" and b.get("timing") == "before_arrival":
            rows.append({"change": "brought_forward", "before": _brief(a), "after": _brief(b), "reason": None})
        else:
            smaller = (b.get("hours_of_work") or 0) < (a.get("hours_of_work") or 0)
            rows.append({"change": "still_fits", "before": _brief(a), "after": _brief(b),
                         "reason": "Cut down to what staff can do in the time left." if smaller and b.get("timing") == "before_arrival" else None})
    for j, b in enumerate(now):
        if j not in taken:
            rows.append({"change": "new", "before": None, "after": _brief(b), "reason": "Added in the plan made for this step."})

    def before_arrival(plan: dict) -> dict:
        t = ((plan.get("totals") or {}).get("before_arrival")) or {}
        return {"count": t.get("count", 0), "cost_low": t.get("cost_low", 0), "cost_high": t.get("cost_high", 0)}

    notice = next((m for m in later.get("messages") or [] if m.get("kind") == "notice"), None)
    return {
        "replay": True,
        "note": "Each plan was made by the planner for its own forecast step. This compares the two; it is not a new inspection.",
        "from": {"step": (earlier.get("threat") or {}).get("step_id"), "label": (earlier.get("threat") or {}).get("label"),
                 "hours_left": (earlier.get("threat") or {}).get("hours_left"), "before_arrival": before_arrival(earlier)},
        "to": {"step": (later.get("threat") or {}).get("step_id"), "label": (later.get("threat") or {}).get("label"),
               "hours_left": (later.get("threat") or {}).get("hours_left"), "safe_working_hours": safe, "before_arrival": before_arrival(later)},
        "rows": rows,
        "notice": None if notice is None else {"subject": notice.get("subject"), "action_ids": notice.get("action_ids") or []},
    }
