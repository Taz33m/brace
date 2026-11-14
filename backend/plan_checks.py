"""Checks a plan must pass before the planner may finish, so the plan and its messages agree with each other.

These are rules in code, not judgement: they read the plan's own words and compare them.
"""
from __future__ import annotations

import re

# What an action can be about, and the words a notice must use for a resident to recognise the same thing.
SUBJECTS: list[tuple[str, re.Pattern, re.Pattern]] = [
    ("a tree", re.compile(r"\b(tree|pine|evergreen|limb|branch)", re.I), re.compile(r"\b(tree|pine|limb|branch)", re.I)),
    ("balconies and patios", re.compile(r"\b(balcon|patio)", re.I), re.compile(r"\b(balcon|patio)", re.I)),
    ("windows and glass doors", re.compile(r"\b(window|sliding|glass door)", re.I), re.compile(r"\b(window|sliding|glass)", re.I)),
]
_SAYS_NOTICE = re.compile(r"\bnotice\b", re.I)
_RESIDENTS = re.compile(r"\bresidents?\b|\btenants?\b", re.I)


def relies_on_notice(action: dict) -> bool:
    """An action leans on the notice when residents are the ones doing it, or when its own words say the notice covers it."""
    return bool(_RESIDENTS.search(str(action.get("crew") or "")) or _SAYS_NOTICE.search(f"{action.get('title') or ''} {action.get('why') or ''}"))


def notice_gaps(actions: list[dict], messages: list[dict]) -> list[str]:
    """Where an action says the notice covers something and the notice does not say it. Empty when they agree."""
    notice = next((m for m in reversed(messages) if m.get("kind") == "notice"), None)
    leaning = [a for a in actions if relies_on_notice(a)]
    if not leaning:
        return []
    if notice is None:
        return [f"{a['id']} relies on a notice to the people in the building, and none is drafted." for a in leaning]
    body = f"{notice.get('subject') or ''}\n{notice.get('body') or ''}"
    gaps = []
    for a in leaning:
        if a["id"] not in (notice.get("action_ids") or []):
            gaps.append(f"{a['id']} relies on the notice, but the notice does not list it under action_ids.")
        said = f"{a.get('title') or ''} {a.get('why') or ''}"
        for name, in_action, in_notice in SUBJECTS:
            if in_action.search(said) and not in_notice.search(body):
                gaps.append(f"{a['id']} is about {name} and relies on the notice, but the notice never mentions {name}. "
                            f"Say it in the notice in words a resident would recognise (not a structure id), or stop saying the notice covers it.")
    return gaps
