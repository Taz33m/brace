"""The storm desk as a deep agent: one agent that takes a whole portfolio through one forecast step.

Built on LangChain's deepagents. The desk reads the forecast for every building, hands each building
with a plan to an inspector (a subagent with its own context), keeps its notes in files, asks the
crew rule in `desk.py` for the order of work, and puts what only the owner can decide in front of the
owner. It has no tool that sends, books or publishes anything: approval is a stop by construction.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from . import desk, site_model
from .config import AGENT_MODEL

MAX_STEPS = 120

DESK_PROMPT = """You are Brace's storm desk. You work for one owner who has many buildings in the path of a storm or a fire-weather warning, at one forecast step. A plan already exists for some buildings. Your job is the whole portfolio: what happens first, where the scarce crews go, and what only the owner can decide.

How to work
1. Call forecast to see the buildings this step touches and which have a saved plan.
2. For every building with a saved plan, give it to an inspector with the task tool. Send them together, in one turn. Tell each inspector the building id and name.
3. Save each inspector's brief with write_file as /briefs/<building id>.md.
4. Call schedule_crews for those buildings. The order of work is a rule in code; report it, do not change it.
5. If work is left for after the storm because a crew ran out of daylight, call schedule_crews again with one more crew of that trade to see what it would cover. If it covers more people, put that to the owner with ask_owner: what a second crew buys, in people and jobs.
6. For each building whose plan has a notice waiting, call request_approval, in order of least time left.
7. Write /desk.md: the order of the day in ten lines or fewer, and finish with a statement to the owner of five lines or fewer.

Rules
- Say only what a tool returned. Never estimate a height, a time, a cost or a count.
- Nothing is sent, booked or published by you. A crew is "proposed", never "coming".
- Wind is the sustained wind the forecast gives. Do not state a gust speed.
- A replay is a replay of a real forecast. Say so once.
- Write plainly. No jargon, no risk scores."""

INSPECTOR_PROMPT = """You are an inspector on Brace's storm desk. You are given one building. Read its saved plan, its measurements and anything its residents have reported, then return a brief of six lines or fewer for the desk:
- the one thing at this building that matters most before the storm, with a measurement if there is one
- each job an outside trade must do before the storm, with its hours
- what the people on site and the residents are asked to do, in one line
- anything a resident has reported, and whether the plan already covers it
- whether a notice to residents is waiting for the owner's approval
Say only what the tools return. If a tool has nothing, say so in a few words."""


class DeskRun:
    """What one run of the desk saw, asked and left for the owner."""

    def __init__(self, scenario: str, step: str | None, crews: dict[str, int] | None = None):
        self.scenario, self.step, self.crews = scenario, step, dict(crews or {})
        self.events: list[dict] = []
        self.schedules: list[dict] = []
        self.questions: list[dict] = []
        self.approvals: list[dict] = []
        self.t0 = time.time()

    def note(self, kind: str, **data: Any) -> None:
        self.events.append({"t": round(time.time() - self.t0, 1), "kind": kind, **data})

    # --- what the desk and its inspectors can do --------------------------------------------------
    def tools(self) -> dict[str, Any]:
        run = self

        def forecast(limit: int = 12) -> str:
            """The buildings this forecast step touches, most pressing first: hours left, safe crew hours, homes, tenants, and whether a plan is saved."""
            rows = desk.portfolio(run.scenario, run.step)
            shown = [r for r in rows if r["plan_saved"]] + [r for r in rows if not r["plan_saved"]][:max(0, limit)]
            run.note("forecast", touched=len(rows), with_plan=sum(r["plan_saved"] for r in rows))
            return json.dumps({"buildings_touched": len(rows), "with_a_saved_plan": sum(r["plan_saved"] for r in rows),
                               "can_be_inspected": sum(r["inspectable"] for r in rows),
                               "buildings": [{k: r[k] for k in ("building_id", "name", "type", "homes", "tenants", "rank", "hours_left", "safe_crew_hours", "plan_saved")} for r in shown]})

        def building_plan(building_id: int) -> str:
            """The saved plan for one building at this step: its jobs, who does each, what was set aside, and the notice waiting."""
            brief = desk.plan_brief(building_id, run.scenario, run.step)
            run.note("plan", building_id=building_id, found=brief is not None)
            return json.dumps(brief) if brief else "No plan is saved for this building at this forecast step."

        def measurements(building_id: int) -> str:
            """Measured facts about one building, each with its source: roof heights, the tallest thing beside each roof, which roof each scan is under."""
            try:
                model = site_model.build(building_id)
            except KeyError:
                return "This building has not been gathered, so nothing is measured."
            run.note("measurements", building_id=building_id)
            tall = sorted((st for st in model["structures"] if (st.get("tallest_beside_it") or {}).get("value")),
                          key=lambda st: -st["tallest_beside_it"]["value"]["above_roof_m"])[:4]
            return json.dumps({"stages": [{"stage": s["key"], "result": s["headline"]} for s in model["stages"]],
                               "measured": site_model.measured_notes(model, [st["id"] for st in tall])[:10]})

        def resident_messages(building_id: int) -> str:
            """What residents of one building have reported, each with the room it was placed in when its words named one."""
            rows = site_model.place(building_id, site_model.load_reports(building_id))
            run.note("residents", building_id=building_id, messages=len(rows))
            return json.dumps([{"at": r["at"], "text": r["text"], "room": (r.get("where") or {}).get("room"), "status": r.get("status")} for r in rows]) if rows else "No resident has reported anything for this building."

        def schedule_crews(building_ids: list[int], extra_crews: dict[str, int] | None = None) -> str:
            """The order of work for each scarce outside trade across these buildings, by Brace's rule. extra_crews sets how many crews of a trade there are, for example {"tree crew": 2}; without it each trade has the owner's current number."""
            crews = {**run.crews, **(extra_crews or {})}
            got = desk.schedule(run.scenario, run.step, building_ids, crews)
            run.schedules.append({"crews": crews, "building_ids": building_ids, **got})
            run.note("schedule", crews=crews, scheduled=sum(len(t["scheduled"]) for t in got["trades"]), deferred=sum(len(t["deferred"]) for t in got["trades"]))
            return json.dumps(got)

        def ask_owner(question: str, what_it_buys: str, building_ids: list[int]) -> str:
            """Put a decision that only the owner can make in front of the owner, with what a yes would buy. Nothing happens until the owner answers."""
            run.questions.append({"question": question, "what_it_buys": what_it_buys, "building_ids": building_ids})
            run.note("question", question=question)
            return "Recorded for the owner. Nothing has been booked."

        def request_approval(building_id: int, job_id: str, why_now: str) -> str:
            """Ask the owner to approve the residents' notice linked to a job. The desk cannot publish it."""
            brief = desk.plan_brief(building_id, run.scenario, run.step)
            notice = (brief or {}).get("notice_waiting")
            if not notice or job_id not in notice["covers_jobs"]:
                return "No notice is waiting for that job at that building."
            run.approvals.append({"building_id": building_id, "job_id": job_id, "subject": notice["subject"], "why_now": why_now})
            run.note("approval", building_id=building_id)
            return "Waiting for the owner. Nothing has been published."

        return {f.__name__: f for f in (forecast, building_plan, measurements, resident_messages, schedule_crews, ask_owner, request_approval)}

    def record(self, statement: str, files: dict[str, str], usage: dict, stop: str) -> dict:
        rows = desk.portfolio(self.scenario, self.step)
        first = self.schedules[0] if self.schedules else None
        return {
            "scenario": self.scenario, "step": self.step, "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - self.t0, 1), "model": AGENT_MODEL, "stop": stop,
            "buildings_touched": len(rows), "buildings": [r for r in rows if r["plan_saved"]],
            "schedule": first, "what_more_crews_buy": self.schedules[1:],
            "for_the_owner": {"questions": self.questions, "approvals": self.approvals},
            "briefs": {k: v for k, v in files.items() if k.startswith("/briefs/")}, "order_of_the_day": files.get("/desk.md"),
            "statement": statement, "events": self.events, "usage": usage,
        }


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text").strip()


def _file_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    content = data.get("content") if isinstance(data, dict) else None
    return "\n".join(content) if isinstance(content, list) else str(content or "")


def build(run: DeskRun, model: Any = None):
    """The desk and its inspector, wired to one run's tools."""
    from deepagents import create_deep_agent
    if model is None:
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(model=AGENT_MODEL, max_tokens=8000)
    t = run.tools()
    inspector = {"name": "inspector", "description": "Reads one building's saved plan, measurements and resident reports and returns a six-line brief. Give it one building id and name.",
                 "system_prompt": INSPECTOR_PROMPT, "tools": [t["building_plan"], t["measurements"], t["resident_messages"]]}
    return create_deep_agent(model=model, system_prompt=DESK_PROMPT, subagents=[inspector], name="brace-storm-desk",
                             tools=[t["forecast"], t["schedule_crews"], t["ask_owner"], t["request_approval"]])


def run_desk(scenario: str, step: str | None, crews: dict[str, int] | None = None, model: Any = None, save: bool = True) -> dict:
    """Run the desk once for a forecast step and save what it decided."""
    run = DeskRun(scenario, step, crews)
    agent = build(run, model)
    sc = desk.hazards.scenario(scenario, step)
    ask = (f"{sc['name']}, {sc.get('label') or 'current forecast'}"
           f"{' (a replay of the real forecast as issued)' if not sc.get('live') else ''}. Run the desk for this step.")
    stop, statement, files, usage = "finished", "", {}, {"input_tokens": 0, "output_tokens": 0}
    try:
        out = agent.invoke({"messages": [{"role": "user", "content": ask}]}, config={"recursion_limit": MAX_STEPS})
        statement = next((_text(m.content) for m in reversed(out["messages"]) if getattr(m, "type", "") == "ai" and _text(m.content)), "")
        files = {path: _file_text(data) for path, data in (out.get("files") or {}).items()}
        for m in out["messages"]:
            meta = getattr(m, "usage_metadata", None) or {}
            for k in usage:
                usage[k] += meta.get(k, 0) or 0
    except Exception as e:  # a failed run is recorded as failed, with what it had done so far
        stop, statement = "error", f"The desk stopped: {e}"
    record = run.record(statement, files, usage, stop)
    if save and stop == "finished":
        desk.save(record)
    return record
