"""What changes because a resident said something.

A plan is made before the storm. Residents then tell the property team things the plan could not know:
that someone needs help getting out, that water is coming in at a door. Each of those becomes work, placed
ahead of the planned jobs, so the response follows what people on the ground report.

The rules are here, in code, and they are deliberately small. A request for help is a person to reach
first. A report that fits the scan is something to inspect, at the place the scan puts it. A report the
scan cannot place is a call to make. Nothing here prices the work or judges how bad the damage is: the
scan was made before the storm and cannot know.
"""
from __future__ import annotations

import re

_SUPPORT = re.compile(r"^Support request \(([^)]*)\):\s*")


def from_residents(reports: list[dict]) -> list[dict]:
    """The work residents' words add, in the order it should be done: people first, then things to inspect, then calls to make."""
    people, inspect, call = [], [], []
    for r in reports:
        said = _SUPPORT.sub("", r.get("text") or "")
        asked = _SUPPORT.match(r.get("text") or "")
        check, where = r.get("check") or {}, r.get("where") or {}
        base = {"report_id": r["id"], "said": said, "src": r.get("src") or ["resident:report"]}
        if asked:
            what = "getting out" if asked.group(1) == "access" else "housing" if asked.group(1) == "housing" else asked.group(1)
            people.append({**base, "kind": "person", "title": f"Reach the resident who asked for help with {what}", "who": "on-site staff", "when": "first"})
        elif check.get("verdict") == "fits":
            place = " in the ".join(x for x in (where.get("thing"), (where.get("room") or "").lower()) if x)
            inspect.append({**base, "kind": "inspect", "title": f"Inspect the {place}" + (f", {where['scan_name']}" if where.get("scan_name") else ""),
                            "who": "on-site maintenance", "when": "before the planned jobs", "because": check.get("says")})
        elif check.get("verdict") == "wrong_place":
            call.append({**base, "kind": "call", "title": "Ask the resident which room they mean", "who": "the property team", "when": "today", "because": check.get("says")})
        else:
            call.append({**base, "kind": "call", "title": "Call the resident: the scan cannot place this report", "who": "the property team", "when": "today", "because": check.get("says")})
    out = people + inspect + call
    return [{**item, "id": f"R{i + 1}"} for i, item in enumerate(out)]
