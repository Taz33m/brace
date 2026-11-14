"""Drives the agent loop with a scripted stand-in for the model: tools, the time rule,
evidence rules, messages, events and the saved plan are tested without any API call."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from backend import agent as agent_mod
from backend import matterport, vexcel, vision
from tests.conftest import ll


def tool(name, **args):
    return SimpleNamespace(type="tool_use", id=f"tu_{name}_{id(args)}", name=name, input=args)


def turn(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class Script:
    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.messages = SimpleNamespace(create=self._vision)

    def _create(self, **kw):
        # The agent keeps appending to its message list, so keep a snapshot of what was sent.
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return self.turns.pop(0)

    def _vision(self, **kw):
        body = {"glass": "mostly glass", "level": "ground", "floor_level_items": ["server rack"], "exterior_doors": "glass doors",
                "note": "Ground-floor suite with a glass storefront."}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])


@pytest.fixture
def imagery(site, monkeypatch, tmp_path):
    face = tmp_path / "face.jpg"
    Image.new("RGB", (256, 256), (200, 200, 190)).save(face)
    monkeypatch.setattr(matterport, "face_image", lambda model, sweep, f: face)
    monkeypatch.setattr(matterport, "download_faces", lambda model, sweeps, faces: 0)
    c = ll(-30, 10)
    box = f"POLYGON(({c[0] - 1e-5} {c[1] - 1e-5},{c[0] + 1e-5} {c[1] - 1e-5},{c[0] + 1e-5} {c[1] + 1e-5},{c[0] - 1e-5} {c[1] + 1e-5},{c[0] - 1e-5} {c[1] - 1e-5}))"
    monkeypatch.setattr(vexcel, "detect", lambda wkt, labels, **k: [{"label": labels[0], "confidence": 0.8, "bbox_wkt": box}])
    return site


def results_of(request):
    return {r["tool_use_id"]: r for r in request["messages"][-1]["content"]}


def test_full_run_builds_a_plan_with_messages(imagery, threat):
    site = imagery
    cell = site.cell_of(*ll(-30, 10))
    strap = tool("add_action", lead_id="L1", title="Check and strap the six rooftop units on S1", hazard="wind", timing="before_arrival",
                 hours_of_work=6, crew="Mechanical contractor", cost_low=900, cost_high=2400, why="Six units sit on the roof.",
                 basis="seen", structure="S1", site_cell=cell)
    move = tool("add_action", lead_id="L2", title="Move the server rack in Suite 100 off the floor", hazard="flood", timing="before_arrival",
                hours_of_work=2, crew="Tenant", cost_low=0, cost_high=300, why="The suite is at ground level in a flood zone.",
                basis="seen", scan_id="SCAN1", sweep_id="w1", direction="east")
    script = Script([
        turn(tool("get_building"), tool("get_threat"), tool("get_site_facts"), tool("view_site", view="overhead"), tool("list_scans")),
        turn(tool("open_lead", title="Six rooftop units on S1", hazard="wind", why="Roof analysis counts six."),
             tool("open_lead", title="Ground-floor suite in a flood zone", hazard="flood", why="FEMA zone AE."),
             tool("open_lead", title="Trees over S2", hazard="wind", why="Check canopy.")),
        turn(tool("find_on_site", labels=["rooftop air conditioner"]), tool("survey_scan", scan_id="SCAN1"), tool("look", scan_id="SCAN1", sweep_id="w1", direction="east")),
        turn(strap, move, tool("close_lead", lead_id="L3", outcome="not_a_concern", note="No canopy over either roof.")),
        turn(tool("draft_message", kind="notice", to="All tenants", subject="Storm preparation", body="Please move equipment off the floor by Sunday noon.", action_ids=["A2"]),
             tool("draft_message", kind="work_order", to="Mechanical contractor", subject="Rooftop units", body="Strap six units on S1.", action_ids=["A1"])),
        turn(tool("finish", headline="Two jobs before landfall.", summary="Strap the rooftop units and clear the ground floor.")),
    ])
    events = []
    plan = agent_mod.Planner(site, threat, emit=events.append, client=script).run()

    assert plan["complete"] and plan["stop"] == "finished" and plan["headline"] == "Two jobs before landfall."
    assert [a["id"] for a in plan["actions"]] == ["A1", "A2"]            # costliest first within a timing group
    a1, a2 = plan["actions"]
    assert a1["structure"] == "S1" and a1["site"]["cell"] == cell and (site.dir / a1["site"]["image"]).exists()
    assert a2["interior"]["scan_name"] == "Suite 100" and (site.dir / a2["interior"]["image"]).exists()
    assert plan["totals"]["before_arrival"] == {"count": 2, "cost_low": 900, "cost_high": 2700, "hours": 8.0}
    assert [l["status"] for l in plan["leads"]] == ["actions", "actions", "not_a_concern"]
    assert [m["kind"] for m in plan["messages"]] == ["notice", "work_order"]

    # The detector result was mapped onto the grid and the structure it sits on.
    found = results_of(script.requests[3])
    rows = json.loads(next(v for v in found.values() if isinstance(v["content"], list))["content"][0]["text"])
    assert rows[0]["cell"] == cell and rows[0]["on_or_beside"] == "S1"
    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "done" and "message" in kinds
    look = next(e for e in events if e["type"] == "step" and e["tool"] == "look")
    assert look["focus"]["scan_id"] == "SCAN1" and (site.dir / look["image"]).exists()
    saved = json.loads((site.dir / "plans" / "test-storm__t36.json").read_text())
    assert saved["actions"][0]["id"] == "A1" and all(e["type"] != "done" for e in saved["events"])


def test_time_and_evidence_rules(imagery, threat):
    base = dict(lead_id="L1", hazard="wind", crew="Roofer", cost_low=100, cost_high=200, why="x")
    too_long = tool("add_action", title="Re-roof S1", timing="before_arrival", hours_of_work=40, basis="record", **base)
    no_place = tool("add_action", title="Patch the roof", timing="before_arrival", hours_of_work=4, basis="seen", **base)
    later = tool("add_action", title="Re-roof S1", timing="after_event", hours_of_work=40, basis="record", **base)
    early = tool("finish", headline="x", summary="y")
    script = Script([
        turn(tool("open_lead", title="Roof on S1", hazard="wind", why="Condition 2 of 5.")),
        turn(too_long, no_place, early),
        turn(later),
        turn(tool("finish", headline="x", summary="y")),                                  # blocked: no notice yet
        turn(tool("draft_message", kind="notice", to="All tenants", subject="s", body="b")),
        turn(tool("finish", headline="Done.", summary="Later.")),
    ])
    plan = agent_mod.Planner(imagery, threat, client=script).run()
    res = results_of(script.requests[2])
    assert res[too_long.id]["is_error"] and "24 usable crew hours" in res[too_long.id]["content"]   # 30 h left minus 6 h stand-down
    assert res[no_place.id]["is_error"] and "place you looked at" in res[no_place.id]["content"]
    assert res[early.id]["is_error"] and "L1" in res[early.id]["content"]
    blocked = results_of(script.requests[4])
    assert next(iter(blocked.values()))["is_error"] and "notice" in next(iter(blocked.values()))["content"]
    assert plan["complete"] and [a["timing"] for a in plan["actions"]] == ["after_event"]


def test_no_deadline_when_arrival_time_unknown(imagery, threat):
    threat = {**threat, "hours_left": None}
    long_job = tool("add_action", lead_id="L1", title="Clear brush", hazard="fire", timing="before_arrival", hours_of_work=40,
                    crew="Brush crew", cost_low=1, cost_high=2, why="x", basis="record")
    script = Script([turn(tool("open_lead", title="Brush", hazard="fire", why="w")), turn(long_job),
                     turn(tool("draft_message", kind="notice", to="Residents", subject="s", body="b")),
                     turn(tool("finish", headline="h", summary="s"))])
    plan = agent_mod.Planner(imagery, threat, client=script).run()
    assert plan["complete"] and len(plan["actions"]) == 1


def test_bad_input_is_returned_not_raised_and_refusal_stops(imagery, threat):
    bad = [tool("look", scan_id="nope", sweep_id="w1", direction="north"), tool("view_site", view="from-south"),
           tool("view_site", view="overhead", zoom_cell="Z9"), tool("draft_message", kind="notice", to="x", subject="s", body="b", action_ids=["A9"])]
    script = Script([turn(*bad), turn(SimpleNamespace(type="text", text=""), stop="refusal")])
    events = []
    plan = agent_mod.Planner(imagery, threat, emit=events.append, client=script).run()
    assert all(r["is_error"] for r in results_of(script.requests[1]).values())
    assert plan["stop"] == "refusal" and not plan["complete"] and any(e["type"] == "error" for e in events)


def test_request_shape_and_tools(imagery, threat):
    script = Script([turn(tool("finish", headline="h", summary="s"))])
    agent_mod.Planner(imagery, threat, client=script).run()
    req = script.requests[0]
    assert req["thinking"]["type"] == "adaptive" and "tool_choice" not in req and "temperature" not in req
    assert req["fallbacks"] == "default" and req["betas"] == ["server-side-fallback-2026-07-01"]
    names = [t["name"] for t in req["tools"]]
    assert len(names) == len(set(names)) and all(hasattr(agent_mod.Planner, f"t_{n}") for n in names)
    assert "30 hours remain" in req["messages"][0]["content"]


def test_scan_survey_caches(imagery):
    first = vision.survey(imagery, "SCAN1", Script([]))
    assert [r["sweep_id"] for r in first] == ["w1", "w2"] and first[0]["glass"] == "mostly glass"
    assert vision.survey(imagery, "SCAN1", SimpleNamespace()) == first   # served from cache, no client needed
