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
        # What the action is about is read from its title; its reasons can mention many things in passing.
        for name, in_action, in_notice in SUBJECTS:
            if in_action.search(str(a.get("title") or "")) and not in_notice.search(body):
                gaps.append(f"{a['id']} is about {name} and relies on the notice, but the notice never mentions {name}. "
                            f"Say it in the notice in words a resident would recognise (not a structure id), or stop saying the notice covers it.")
    return gaps


# --- gusts -----------------------------------------------------------------------------------------------
# The forecast gives sustained wind for the site. Its only word on gusts is that they run 20 to 30 percent
# higher. A gust speed in miles an hour is therefore our arithmetic, not the forecast's, and is not stated.
GUST_SENTENCE = "Gusts run roughly 20 to 30 percent higher than the sustained wind."
_GUST_FIGURE = re.compile(r"gusts?\b(?! estimate)[^.\n]{0,140}?\d{2,3}\s*mph", re.I)
_GUST_CLAUSE = re.compile(r"[,;]?\s*(?:and\s+|so\s+|with\s+)?(?:expect\s+)?(?:some\s+)?gusts?\b(?! estimate)[^.,;()\n]{0,60}?\d{2,3}\s*(?:(?:to|-|–)\s*\d{2,3}\s*)?mph", re.I)
_SO_FIGURE = re.compile(r",\s*so\s+(?:about|around|roughly|near)?\s*\d{2,3}\s*(?:(?:to|-|–)\s*\d{2,3}\s*)?mph", re.I)


def gust_figures(text: str | None) -> list[str]:
    """Places where a gust speed is given as a number. The sentence that gusts run higher is not one."""
    return [m.group(0) for m in _GUST_FIGURE.finditer(text or "")]


def drop_gust_figures(text: str) -> str:
    """Take a stated gust speed out of a line, leaving the rest of the line as written."""
    out = []
    for line in text.split("\n"):
        if gust_figures(line):
            line = _SO_FIGURE.sub("", _GUST_CLAUSE.sub("", line))
        out.append(line)
    return "\n".join(out)


# --- a notice a resident can act on ------------------------------------------------------------------------
_STAFF_AUDIENCE = re.compile(r"\b(staff|maintenance|leasing (?:team|office)|on-?site team|crew|contractor)\b", re.I)


def is_staff_audience(to: str | None) -> bool:
    """A notice goes to the people in the building. Instructions to staff or a trade are a work order."""
    return bool(_STAFF_AUDIENCE.search(to or "")) and not _RESIDENTS.search(to or "")


def unfinished_lines(messages: list[dict]) -> list[str]:
    """Lines of the resident notice that are a heading with no instruction after it: a checklist line that is
    not a finished sentence. A notice is read line by line, and a line may be copied on its own."""
    notice = next((m for m in reversed(messages) if m.get("kind") == "notice"), None)
    if notice is None:
        return []
    return [line.strip()[2:].strip() for line in (notice.get("body") or "").split("\n")
            if line.strip().startswith("- ") and not re.search(r"[.!?)\u201d\"]$", line.strip())]


def without_superseded(messages: list[dict]) -> list[dict]:
    """One notice to the building and one work order per trade: where one was drafted again, only the last is kept."""
    last: dict[tuple, int] = {}
    for i, m in enumerate(messages):
        last[(m.get("kind"), "" if m.get("kind") == "notice" else str(m.get("to") or "").strip().lower())] = i
    return [m for i, m in enumerate(messages) if i in last.values()]
