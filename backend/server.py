"""HTTP API for the web app: scenarios, the ranked portfolio, building bundles, imagery, and live plans."""
from __future__ import annotations

import asyncio
import io
import json
import os
import threading
from collections import Counter

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from PIL import Image
from sse_starlette.sse import EventSourceResponse

from . import hazards, matterport, screen, vexcel
from .agent import VIEW_TO_OBLIQUE, Planner
from .building import BuildingError, Site, building_dir
from .config import MATTERPORT_SDK_KEY

app = FastAPI(title="Brace")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
                   allow_methods=["*"], allow_headers=["*"])


def _site(property_id: int) -> Site:
    try:
        return Site.load(property_id)
    except BuildingError as e:
        raise HTTPException(404 if "unknown" in str(e) else 422, str(e))
    except (vexcel.VexcelError, matterport.MatterportError) as e:
        raise HTTPException(502, str(e))


def _scenario(scenario_id: str) -> dict:
    sc = next((s for s in hazards.scenarios() if s["id"] == scenario_id), None)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    return sc


def _step(sc: dict, step_id: str | None) -> str | None:
    ids = [s["id"] for s in sc["steps"]]
    if step_id and step_id not in ids:
        raise HTTPException(404, "unknown step for this scenario")
    return step_id or (ids[-1] if ids else None)


def _plan_key(scenario_id: str, step_id: str | None) -> str:
    return f"{scenario_id}__{step_id or 'now'}"


def _plan(property_id: int, key: str) -> dict | None:
    p = building_dir(property_id) / "plans" / f"{key}.json"
    return json.loads(p.read_text()) if p.exists() else None


@app.get("/api/config")
def config() -> dict:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return {"sdk_key": MATTERPORT_SDK_KEY, "agent_ready": has_key}


@app.get("/api/scenarios")
def scenarios() -> list[dict]:
    try:
        return hazards.scenarios()
    except hazards.HazardError as e:
        raise HTTPException(502, str(e))


@app.get("/api/scenarios/{scenario_id}")
def scenario(scenario_id: str, step: str | None = None) -> dict:
    sc = _scenario(scenario_id)
    try:
        return {**sc, "step": _step(sc, step), "map": hazards.scenario(scenario_id, _step(sc, step))}
    except hazards.HazardError as e:
        raise HTTPException(502, str(e))


@app.get("/api/portfolio")
def portfolio(scenario: str, step: str | None = None, manager: str | None = None, kind: str | None = None, limit: int = 60) -> dict:
    """Buildings the forecast touches, most pressing first, plus every touched point for the map."""
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    rows = screen.rank(scenario, step_id)
    managers = Counter(r["manager"] for r in rows if r["manager"])
    types = Counter(r["type_label"] for r in rows)
    view = [r for r in rows if (not manager or r["manager"] == manager) and (not kind or r["type_label"] == kind)]
    key = _plan_key(scenario, step_id)
    top = []
    for r in view[:limit]:
        plan = _plan(r["id"], key) if (building_dir(r["id"]) / "plans" / f"{key}.json").exists() else None
        top.append({**r, "plan": {"actions": len(plan["actions"]), "headline": plan["headline"]} if plan else None})
    band = (lambda r: r["exposure"].get("wind_band")) if sc["kind"] == "hurricane" else (lambda r: "warning")
    return {
        "scenario": scenario, "step": step_id, "touched": len(rows), "shown": len(view),
        "homes": sum(r["units"] or 0 for r in view), "tenants": sum(r["tenant_count"] or 0 for r in view),
        "managers": [{"name": m, "buildings": n} for m, n in managers.most_common(40)],
        "types": [{"name": t, "buildings": n} for t, n in types.most_common()],
        "buildings": top,
        "points": [[r["id"], round(r["lat"], 5), round(r["lon"], 5), band(r), r["rank"]] for r in view],
    }


@app.get("/api/buildings/{property_id}")
def building(property_id: int, scenario: str, step: str | None = None) -> dict:
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    s = _site(property_id)
    try:
        threat = screen.threat_for(scenario, step_id, s.d["record"])
    except hazards.HazardError as e:
        raise HTTPException(502, str(e))
    facts = screen.site_facts().get(str(property_id))
    reasons = [x["text"] for x in screen.signals(sc["kind"], s.d["record"], facts, threat["standing_risk"])]
    return {**s.d, "threat": threat, "reasons": reasons, "plan": _plan(property_id, _plan_key(scenario, step_id))}


def _jpeg(im: Image.Image, quality: int = 85) -> Response:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/buildings/{property_id}/aerial.jpg")
def aerial(property_id: int) -> FileResponse:
    _site(property_id)
    return FileResponse(building_dir(property_id) / "aerial.jpg", media_type="image/jpeg")


@app.get("/api/buildings/{property_id}/oblique/{view}.jpg")
def oblique(property_id: int, view: str, structure: str | None = None) -> FileResponse:
    s = _site(property_id)
    if view not in VIEW_TO_OBLIQUE or VIEW_TO_OBLIQUE[view] not in s.d["aerial"]["obliques"]:
        raise HTTPException(404, "no such view here")
    sid = (structure or s.d["structures"][0]["id"]).upper()
    if sid not in s.polys:
        raise HTTPException(404, "no such structure")
    try:
        path, _ = vexcel.oblique(s.polys[sid].wkt, VIEW_TO_OBLIQUE[view], buffer_m=10)
    except vexcel.VexcelError as e:
        raise HTTPException(502, str(e))
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/buildings/{property_id}/file/{path:path}")
def run_file(property_id: int, path: str) -> FileResponse:
    base = building_dir(property_id).resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or target.suffix != ".jpg" or not target.exists():
        raise HTTPException(404, "not found")
    return FileResponse(target, media_type="image/jpeg")


# --- plan runs -------------------------------------------------------------------
class Run:
    """A live plan: a worker thread appending events that any number of streams can follow."""

    def __init__(self, site: Site, threat: dict):
        self.events: list[dict] = []
        self.done = False
        self.lock = threading.Lock()
        threading.Thread(target=self._work, args=(site, threat), daemon=True).start()

    def _work(self, site: Site, threat: dict) -> None:
        try:
            Planner(site, threat, emit=self._emit).run()
        except Exception as e:  # constructing the client can fail before the loop's own handling
            self._emit({"type": "error", "t": 0, "message": str(e)})
            self._emit({"type": "done", "t": 0, "stop": "error", "plan": None})
        finally:
            self.done = True

    def _emit(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)


RUNS: dict[tuple[int, str], Run] = {}


@app.post("/api/buildings/{property_id}/plan")
def start_plan(property_id: int, scenario: str, step: str | None = None) -> dict:
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    s = _site(property_id)
    key = (property_id, _plan_key(scenario, step_id))
    run = RUNS.get(key)
    if run is None or run.done:
        RUNS[key] = Run(s, screen.threat_for(scenario, step_id, s.d["record"]))
        return {"started": True}
    return {"started": False, "running": True}


@app.get("/api/buildings/{property_id}/plan/stream")
async def stream(property_id: int, scenario: str, step: str | None = None, replay: bool = False, speed: float = Query(5.0, gt=0)):
    """Server-sent events for a plan run. With replay=true, plays back the saved run at `speed`x."""
    sc = _scenario(scenario)
    key = _plan_key(scenario, _step(sc, step))
    if replay:
        saved = _plan(property_id, key)
        if not saved:
            raise HTTPException(404, "no saved plan for this building and forecast")

        async def play():
            last = 0.0
            for e in saved["events"]:
                await asyncio.sleep(min(max(e["t"] - last, 0) / speed, 1.2))
                last = e["t"]
                yield {"data": json.dumps(e)}
            yield {"data": json.dumps({"type": "done", "t": last, "stop": saved["stop"],
                                       "plan": {k: v for k, v in saved.items() if k != "events"}})}
        return EventSourceResponse(play())

    run = RUNS.get((property_id, key))
    if run is None:
        raise HTTPException(404, "no plan running for this building")

    async def live():
        i = 0
        while True:
            with run.lock:
                batch = run.events[i:]
            for e in batch:
                yield {"data": json.dumps(e)}
            i += len(batch)
            if run.done and i >= len(run.events):
                break
            await asyncio.sleep(0.25)
    return EventSourceResponse(live())
