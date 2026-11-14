"""The storm desk: what one owner's whole portfolio needs done before a storm, and who can do it in time.

A plan is written for one building. An owner has many buildings and one tree crew. This module holds the
part of the desk that is arithmetic, not judgement: which buildings the forecast touches, what each saved
plan asks of an outside trade, and the order a scarce crew should work in. The agent in `desk_agent.py`
reads these and decides what to look at; it cannot change the rule.

The rule for a scarce crew (in `allocate`):
  1. Only work that must be done before the storm by an outside trade competes for a crew. Work the
     on-site team or residents do does not: they are already there.
  2. Jobs are taken in order of people protected per crew hour, most first.
  3. A job is given to the crew that is free soonest. It is scheduled only if that crew can finish it
     before the building's safe working time ends (hours until conditions arrive, less the stand-down
     the planner uses). Moving between buildings costs travel time.
  4. Crews work in daylight, 07:00 to 19:00 where the building is. Hours of darkness do not count.
  5. A job that does not fit is not dropped. It moves to after the storm, with the reason.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import hazards, screen
from .building import building_dir
from .clock import CREW_STANDDOWN_HOURS
from .config import CACHE_DIR

DESK_DIR = CACHE_DIR / "desk"
TRAVEL_HOURS = 1.0          # moving a crew from one building to the next, door to door
CREWS_ASSUMED = 1           # crews of each trade the owner can call on, unless the owner says otherwise
DAY_START, DAY_END = 7, 19  # the hours of the day, local time, an outside crew works
ZONES = {"Houston": "America/Chicago", "Los Angeles": "America/Los_Angeles"}

# An outside trade is someone who has to be booked and has to travel. Checked in this order.
_TRADES: list[tuple[str, re.Pattern]] = [
    ("tree crew", re.compile(r"\b(tree|arbor)", re.I)),
    ("landscape crew", re.compile(r"\b(landscap|brush)", re.I)),
    ("roofer", re.compile(r"\b(roof|gutter)", re.I)),
    ("mechanical contractor", re.compile(r"\b(hvac|mechanical|electrician|plumber|glazier|contractor)", re.I)),
]
_ON_SITE = re.compile(r"\b(on-?site|staff|maintenance|leasing|manager|engineer|resident|tenant|owner)", re.I)


def trade(crew: str | None) -> str | None:
    """The outside trade a job needs, or None when the people already at the building do it."""
    who = re.split(r"[(;]", crew or "")[0]
    if _ON_SITE.search(who):
        return None
    for name, pattern in _TRADES:
        if pattern.search(who):
            return name
    return None


def _plan_path(property_id: int, scenario: str, step: str | None) -> Path:
    return building_dir(property_id) / "plans" / f"{scenario}__{step or 'now'}.json"


def saved_plan(property_id: int, scenario: str, step: str | None) -> dict | None:
    path = _plan_path(property_id, scenario, step)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def portfolio(scenario: str, step: str | None, limit: int | None = None) -> list[dict]:
    """The buildings this forecast step touches, most pressing first, with what Brace already holds for each."""
    out = []
    for row in screen.rank(scenario, step):
        gathered = (building_dir(row["id"]) / "building.json").exists()
        left = row.get("hours_left")
        out.append({
            "building_id": row["id"], "name": row["name"], "type": row["type_label"], "homes": row.get("units") or 0, "tenants": row.get("tenant_count") or 0,
            "rank": row["rank"], "hours_left": left, "safe_crew_hours": None if left is None else max(0.0, round(left - CREW_STANDDOWN_HOURS, 1)),
            "reasons": row.get("reasons") or [], "scans": row.get("scans") or 0,
            "inspectable": gathered, "plan_saved": _plan_path(row["id"], scenario, step).exists(),
        })
        if limit and len(out) >= limit:
            break
    return out


def jobs(scenario: str, step: str | None, building_ids: list[int] | None = None) -> list[dict]:
    """Every job the saved plans ask of an outside trade before the storm, one row a job."""
    rows = {r["building_id"]: r for r in portfolio(scenario, step)}
    out = []
    for pid in building_ids if building_ids is not None else [pid for pid, r in rows.items() if r["plan_saved"]]:
        plan, row = saved_plan(pid, scenario, step), rows.get(pid)
        if not plan or not row:
            continue
        for a in plan.get("actions") or []:
            needs = trade(a.get("crew"))
            if needs and a.get("timing") == "before_arrival":
                out.append({"building_id": pid, "building": row["name"], "job_id": a["id"], "title": a["title"], "trade": needs,
                            "hours": float(a.get("hours_of_work") or 0), "cost_low": a.get("cost_low") or 0, "cost_high": a.get("cost_high") or 0,
                            "people": row["homes"] + row["tenants"], "safe_until_h": row["safe_crew_hours"]})
    return out


def work_windows(issued: datetime, zone: str, horizon_h: float) -> list[tuple[float, float]]:
    """The stretches of daylight working time after a forecast is issued, as hours from that moment."""
    local = issued.astimezone(ZoneInfo(zone))
    out, day = [], local.replace(hour=0, minute=0, second=0, microsecond=0)
    while (day - local).total_seconds() / 3600 < horizon_h:
        a = max(0.0, (day.replace(hour=DAY_START) - local).total_seconds() / 3600)
        b = min(horizon_h, (day.replace(hour=DAY_END) - local).total_seconds() / 3600)
        if b > a:
            out.append((round(a, 2), round(b, 2)))
        day += timedelta(days=1)
    return out


def _worked(clock_h: float, windows: list[tuple[float, float]] | None) -> float:
    """Working hours that have passed by a clock hour."""
    if windows is None:
        return clock_h
    return sum(max(0.0, min(clock_h, b) - a) for a, b in windows)


def _clock(worked_h: float, windows: list[tuple[float, float]] | None, starting: bool = False) -> float:
    """The clock hour at which that many working hours have passed. A job that starts exactly when a day
    ends starts the next morning; one that ends exactly then ends that evening."""
    if windows is None:
        return worked_h
    done = 0.0
    for a, b in windows:
        room = b - a
        if worked_h < done + room - 1e-9 or (not starting and worked_h <= done + room + 1e-9):
            return a + (worked_h - done)
        done += room
    return windows[-1][1] if windows else worked_h


def allocate(job_rows: list[dict], crews: dict[str, int] | None = None, travel_h: float = TRAVEL_HOURS,
             windows: list[tuple[float, float]] | None = None, issued_local: datetime | None = None) -> dict:
    """Give each scarce crew an order of work, by the rule at the top of this file. Pure arithmetic.

    `windows` are the daylight stretches crews can work in, as hours from the forecast; without them the
    clock runs straight through. Crew time is counted in working hours, then turned back into clock hours.
    """
    crews = crews or {}
    when = (lambda h: (issued_local + timedelta(hours=h)).strftime("%a %H:%M")) if issued_local else (lambda h: None)
    by_trade: dict[str, list[dict]] = {}
    for j in job_rows:
        by_trade.setdefault(j["trade"], []).append(j)
    trades = []
    for name in sorted(by_trade):
        n = max(1, int(crews.get(name, CREWS_ASSUMED)))
        free = [0.0] * n                       # when each crew is next free, in hours from the forecast
        at: list[int | None] = [None] * n      # the building each crew is at
        scheduled, deferred = [], []
        # Most people protected per crew hour first; ties go to the shorter job, then by building for a stable order.
        order = sorted(by_trade[name], key=lambda j: (-(j["people"] / max(j["hours"], 0.25)), j["hours"], j["building_id"], j["job_id"]))
        for j in order:
            k = min(range(n), key=lambda i: free[i] + (travel_h if at[i] not in (None, j["building_id"]) else 0.0))
            start = free[k] + (travel_h if at[k] not in (None, j["building_id"]) else 0.0)
            end = start + j["hours"]
            limit = None if j["safe_until_h"] is None else _worked(j["safe_until_h"], windows)   # in working hours
            if limit is not None and end <= limit + 1e-9:
                free[k], at[k] = end, j["building_id"]
                a, b = _clock(start, windows, starting=True), _clock(end, windows)
                scheduled.append({**j, "crew": k + 1, "start_h": round(a, 1), "end_h": round(b, 1), "start_local": when(a), "end_local": when(b)})
            else:
                why = ("No arrival time is forecast for this building, so no deadline can be set." if limit is None else
                       f"Needs {j['hours']:g} working hours. The {name} would have {max(0.0, limit - start):g} left for it "
                       f"before safe working time at this building ends" + (f" ({when(j['safe_until_h'])})." if issued_local else "."))
                deferred.append({**j, "reason": why})
        hours = sum(j["hours"] for j in by_trade[name])
        trades.append({"trade": name, "crews": n, "crews_assumed": name not in crews, "jobs": len(by_trade[name]), "hours_asked": hours,
                       "scheduled": sorted(scheduled, key=lambda s: (s["crew"], s["start_h"])), "deferred": deferred,
                       "people_covered": sum(s["people"] for s in {s["building_id"]: s for s in scheduled}.values()),
                       "cost_low": sum(s["cost_low"] for s in scheduled), "cost_high": sum(s["cost_high"] for s in scheduled)})
    return {
        "rule": "Most people protected per crew hour first. A job is scheduled only if a crew can finish it before that building's "
                f"safe working time ends ({CREW_STANDDOWN_HOURS} hours before conditions arrive). Otherwise it moves to after the storm.",
        "assumptions": {"travel_between_buildings_h": travel_h, "crews_per_trade_unless_set": CREWS_ASSUMED,
                        "working_day": f"{DAY_START:02d}:00 to {DAY_END:02d}:00 local" if windows is not None else "the clock runs straight through"},
        "trades": trades,
    }


def schedule(scenario: str, step: str | None, building_ids: list[int] | None = None, crews: dict[str, int] | None = None) -> dict:
    """The crew schedule for the buildings with a saved plan at this step, in daylight working hours."""
    rows = jobs(scenario, step, building_ids)
    sc = hazards.scenario(scenario, step)
    zone = ZONES.get(sc.get("city") or "")
    if not sc.get("issued") or not zone:
        return allocate(rows, crews)
    issued = datetime.fromisoformat(sc["issued"].replace("Z", "+00:00"))
    horizon = max([r["safe_until_h"] or 0 for r in rows] + [0.0])
    out = allocate(rows, crews, windows=work_windows(issued, zone, horizon), issued_local=issued.astimezone(ZoneInfo(zone)))
    out["forecast_issued_local"] = issued.astimezone(ZoneInfo(zone)).strftime("%a %d %b %H:%M")
    return out


def plan_brief(property_id: int, scenario: str, step: str | None) -> dict | None:
    """One saved plan in as few words as carry it: the jobs, who does each, and the notice waiting for approval."""
    plan = saved_plan(property_id, scenario, step)
    if not plan:
        return None
    notice = next((m for m in plan.get("messages") or [] if m.get("kind") == "notice"), None)
    return {
        "building_id": property_id, "headline": plan.get("headline"), "hours_left": (plan.get("threat") or {}).get("hours_left"),
        "jobs": [{"id": a["id"], "title": a["title"], "timing": a.get("timing"), "who": a.get("crew"), "outside_trade": trade(a.get("crew")),
                  "hours": a.get("hours_of_work"), "cost": [a.get("cost_low"), a.get("cost_high")], "basis": a.get("basis")} for a in plan.get("actions") or []],
        "set_aside": [{"concern": l["title"], "why": l.get("note")} for l in plan.get("leads") or [] if l.get("status") == "not_a_concern"],
        "notice_waiting": None if notice is None else {"subject": notice.get("subject"), "covers_jobs": notice.get("action_ids") or []},
        "checks": plan.get("checks"),
    }


def save(record: dict) -> Path:
    DESK_DIR.mkdir(parents=True, exist_ok=True)
    path = DESK_DIR / f"{record['scenario']}__{record.get('step') or 'now'}.json"
    path.write_text(json.dumps(record, indent=1))
    return path


def load(scenario: str, step: str | None) -> dict | None:
    try:
        return json.loads((DESK_DIR / f"{scenario}__{step or 'now'}.json").read_text())
    except (OSError, ValueError):
        return None
