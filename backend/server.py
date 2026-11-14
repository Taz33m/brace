"""HTTP API for the web app: scenarios, the ranked portfolio, building bundles, imagery, and live plans."""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import threading
import time
from collections import Counter

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from PIL import Image
from sse_starlette.sse import EventSourceResponse

from . import clock, hazards, matterport, openings, portfolio as portfolio_data, screen, site_model, vexcel, voice
from .agent import VIEW_TO_OBLIQUE, Planner
from .building import BuildingError, Site, building_dir
from .config import DATA_DIR, MATTERPORT_SDK_KEY

app = FastAPI(title="Brace")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
                   allow_methods=["*"], allow_headers=["*"])


def _warm_standing_risk() -> None:
    """Fill the flood and fire zoning cache for the whole portfolio, in this process so writes cannot collide.

    The ranking only reads what is cached, so its flood and fire reasons fill in as this runs.
    """
    try:
        points = [(b["lat"], b["lon"]) for b in portfolio_data.buildings()]
        for i in range(0, len(points), 150):
            if hazards.warm_static(points[i:i + 150], log=lambda *_: None):
                screen.rank.cache_clear()  # newly cached zones change the reasons and the order
    except Exception as e:  # a public service being down must not take the app down
        print(f"standing-risk warm-up stopped: {e}")


@app.on_event("startup")
def _startup() -> None:
    if os.environ.get("BRACE_SKIP_WARMUP") != "1":
        threading.Thread(target=_warm_standing_risk, daemon=True).start()


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
    from .preparation_notices import correct_plan_notices
    return correct_plan_notices(json.loads(p.read_text())) if p.exists() else None


@app.get("/api/config")
def config() -> dict:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    return {"sdk_key": MATTERPORT_SDK_KEY, "agent_ready": has_key, "voice_ready": voice.ready()}


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
    sold = [r["last_sale"] for r in view if r.get("last_sale")]
    return {
        # What is exposed, not what would be lost: the last recorded sale price of each touched building.
        "value": {"buildings_with_sale": len(sold), "last_sale_total": sum(x["price"] for x in sold),
                  "allocated_share": sum(1 for x in sold if x["portfolio"]),
                  "oldest_sale": min((x["date"] for x in sold), default=None)},
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
    return {**s.d, "threat": threat, "reasons": reasons, "last_sale": portfolio_data.building(property_id).get("last_sale"),
            "rent": portfolio_data.rent(property_id), "ground": site_model.ground(property_id),
            "plan": _plan(property_id, _plan_key(scenario, step_id))}


@app.get("/api/buildings/{property_id}/plans")
def saved_plans(property_id: int, scenario: str) -> dict:
    """Every forecast step of a scenario that has a saved plan for this building, earliest forecast first.

    This is what lets the clock be moved in a demo: each entry is the plan the agent made for that step.
    """
    sc = _scenario(scenario)
    out = []
    for st in sc["steps"]:
        plan = _plan(property_id, _plan_key(scenario, st["id"]))
        if plan:
            out.append({"step": st["id"], "label": st["label"], "hours_left": (plan.get("threat") or {}).get("hours_left"),
                        "headline": plan.get("headline"), "totals": plan.get("totals"),
                        "actions": [{k: a.get(k) for k in ("id", "title", "timing", "hours_of_work", "cost_low", "cost_high")}
                                    for a in plan.get("actions") or []]})
    return {"plans": out}


# The opening of the pitch descends from the whole city to one roof. Each step is a real aerial photo of a
# square this many metres from its middle to its edge, all centred on the building's own aerial.
DESCENT_BUFFERS_M = (10_000, 2_560, 640, 160)


def _descent_centre(site: Site) -> tuple[float, float]:
    west, south, east, north = site.d["aerial"]["bounds"]
    return (west + east) / 2, (south + north) / 2


def _descent_image(site: Site, level: int):
    lon, lat = _descent_centre(site)
    try:
        return vexcel.ortho(f"POINT({lon} {lat})", buffer_m=DESCENT_BUFFERS_M[level], max_px=(1600, 1600))
    except vexcel.VexcelError as e:
        raise HTTPException(502, str(e))


@app.get("/api/buildings/{property_id}/descent")
def descent(property_id: int) -> dict:
    """The aerial photos for the descent onto a building, widest first, each with the ground it covers and its dates."""
    s = _site(property_id)
    lon, lat = _descent_centre(s)
    levels = []
    for level in range(len(DESCENT_BUFFERS_M)):
        _, info = _descent_image(s, level)
        levels.append({"level": level, "bounds": info.get("bounds"), "first_capture": info.get("first_capture"),
                       "last_capture": info.get("last_capture"), "url": f"/api/buildings/{property_id}/descent/{level}.jpg"})
    return {"focus": {"lon": lon, "lat": lat}, "levels": levels,
            "site": {"bounds": s.d["aerial"]["bounds"], "captured": s.d["aerial"].get("captured"), "url": f"/api/buildings/{property_id}/aerial.jpg"}}


@app.get("/api/buildings/{property_id}/descent/{level}.jpg")
def descent_image(property_id: int, level: int) -> FileResponse:
    if level not in range(len(DESCENT_BUFFERS_M)):
        raise HTTPException(404, "no such step in the descent")
    path, _ = _descent_image(_site(property_id), level)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/buildings/{property_id}/clock")
def clock_change(property_id: int, scenario: str, earlier: str, later: str) -> dict:
    """What became of each job between the plans saved for two forecast steps. A comparison, not a new run."""
    sc = _scenario(scenario)
    plans = [_plan(property_id, _plan_key(scenario, _step(sc, step))) for step in (earlier, later)]
    if not all(plans):
        raise HTTPException(404, "no saved plan for one of these forecast steps")
    return clock.changes(plans[0], plans[1])


@app.get("/api/buildings/{property_id}/facing")
def facing_openings(property_id: int, scenario: str, step: str | None = None) -> dict:
    """For each outside action in the saved plan: which measured windows and outside doors of the nearest scanned space face it."""
    sc = _scenario(scenario)
    plan = _plan(property_id, _plan_key(scenario, _step(sc, step)))
    if not plan:
        return {"plans": {}, "actions": {}}
    try:
        return openings.for_plan(_site(property_id).d, plan)
    except matterport.MatterportError as e:
        raise HTTPException(502, str(e))


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


@app.get("/api/buildings/{property_id}/pano/{scan_id}/{sweep_id}/{face}.jpg")
def pano_face(property_id: int, scan_id: str, sweep_id: str, face: int, size: int = Query(1024, ge=256, le=2048)) -> Response:
    """One cube face of a scan position (0 up, 1-4 sides clockwise from the sweep's heading, 5 down), for the headset view."""
    s = _site(property_id)
    scan = s.scans.get(scan_id)
    if scan is None or face not in range(6) or not any(x["id"] == sweep_id for x in scan["sweeps"]):
        raise HTTPException(404, "no such panorama")
    try:
        path = matterport.face_image(scan_id, sweep_id, face)
    except matterport.MatterportError as e:
        raise HTTPException(502, str(e))
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        return _jpeg(im, quality=80)


# --- headset link ----------------------------------------------------------------
# One phone-in-a-headset follows the laptop. The laptop posts where the agent is looking; the phone
# posts back where it is standing and looking, and what its wearer approved. Held in memory: this is
# a two-device demo link.
TARGET_KEYS = ("building", "scan_id", "sweep_id", "bearing", "action_id", "lon", "lat", "label", "image", "kind")
POSE_KEYS = ("building", "scan_id", "sweep_id", "bearing", "action_id")
VR: dict[str, dict] = {"target": {"rev": 0}, "pose": {"at": 0.0}, "approved": {}}


@app.get("/api/lan")
def lan() -> dict:
    """This machine's address on the local network, so a phone can be pointed at it."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))  # no packet is sent; this only picks the outbound interface
            ip = sock.getsockname()[0]
    except OSError:
        ip = None
    # The phone needs a secure page for its motion sensors and microphone; this is the port that serves one.
    return {"ip": ip, "vr_port": int(os.environ.get("BRACE_VR_PORT") or 5175)}


@app.get("/api/vr/target")
def vr_target() -> dict:
    return VR["target"]


@app.post("/api/vr/target")
def set_vr_target(body: dict) -> dict:
    """Where the agent is looking: a scan position, a point outside (lon, lat), or only a line to say."""
    VR["target"] = {**{k: body.get(k) for k in TARGET_KEYS}, "rev": VR["target"]["rev"] + 1}
    return VR["target"]


@app.get("/api/vr/pose")
def vr_pose() -> dict:
    import time
    return {**VR["pose"], "age": round(time.time() - VR["pose"]["at"], 1)}


@app.post("/api/vr/pose")
def set_vr_pose(body: dict) -> dict:
    import time
    VR["pose"] = {**{k: body.get(k) for k in POSE_KEYS}, "at": time.time()}
    return {"ok": True}


@app.get("/api/vr/approvals")
def vr_approvals(building: int, scenario: str | None = None, step: str | None = None) -> dict:
    """Actions the headset's wearer approved for one building, oldest first."""
    context = None
    if scenario is not None:
        sc = _scenario(scenario)
        context = _plan_key(sc["id"], _step(sc, step))
    mine = sorted((at, aid) for (b, key, aid), at in VR["approved"].items()
                  if b == building and (context is None or context == key))
    return {"action_ids": list(dict.fromkeys(aid for _, aid in mine))}


@app.post("/api/vr/approve")
def vr_approve(body: dict, request: Request) -> dict:
    """Approve a saved action; a linked resident notice is published before success."""
    import time
    building, action_id = body.get("building"), body.get("action_id")
    sc = _scenario(str(body.get("scenario")))
    step = _step(sc, body.get("step"))
    key = _plan_key(sc["id"], step)
    plan = _plan(building, key) if isinstance(building, int) else None
    if not plan or not any(a["id"] == action_id for a in plan["actions"]):
        return {"ok": False, "say": voice.UNKNOWN_SAY}
    if any(m.get("kind") == "notice" and action_id in m.get("action_ids", [])
           for m in plan.get("messages", [])):
        from .recovery.preparation_approval import approve_notice
        result = approve_notice(request, building=building, scenario=sc["id"],
                                step=step, action_id=action_id, plan=plan)
    else:
        result = {"ok": True, "delivery": None,
                  "say": "Action marked approved. No resident notice is linked to this action; work orders remain drafts."}
    VR["approved"].setdefault((building, key, action_id), time.time())
    return result


@app.post("/api/vr/reset")
def vr_reset() -> dict:
    """Clear the link for the next person: where the headset was sent, where it was, and what was approved."""
    VR["target"] = {"rev": VR["target"]["rev"] + 1}
    VR["pose"] = {"at": 0.0}
    VR["approved"] = {}
    return {"ok": True}


def _voice_brief(building: int, scenario: str, step: str | None) -> tuple[dict, dict, dict | None, list[dict]]:
    """What the voice is told about one building at one forecast step: the record, the threat, the saved plan, the scans."""
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    s = _site(building)
    try:
        threat = screen.threat_for(scenario, step_id, s.d["record"])
    except hazards.HazardError as e:
        raise HTTPException(502, str(e))
    return s.d["record"], threat, _plan(building, _plan_key(scenario, step_id)), s.d["scans"]


def _measured(building: int, plan: dict | None) -> dict[str, list[dict]]:
    """For each action of a plan, the site model's measurements that bear on it. Empty when there is no plan."""
    if not plan:
        return {}
    model = _site_model(building)
    found = {a["id"]: site_model.measured_for(model, a) for a in plan.get("actions") or []}
    return {k: v for k, v in found.items() if v}


def _site_model(building: int) -> dict:
    try:
        return site_model.build(building)
    except KeyError:
        raise HTTPException(404, "this building has not been gathered yet")


@app.get("/api/scenarios/{scenario_id}/forecast.{kind}")
def forecast_download(scenario_id: str, kind: str, step: str | None = None):
    """The forecast as data: one row per building, keyed by the CoStar property id. `step=all` gives every forecast step."""
    from . import forecast_export
    sc = _scenario(scenario_id)
    if kind not in ("csv", "json"):
        raise HTTPException(404, "forecast.csv or forecast.json")
    which = "all" if step == "all" else _step(sc, step)
    try:
        table = forecast_export.table(sc["id"], which)
    except hazards.HazardError as e:
        raise HTTPException(502, str(e))
    if kind == "json":
        return {"scenario": sc["id"], "step": which, "columns": forecast_export.COLUMNS, "rows": table}
    name = f"brace-forecast-{sc['id']}-{'all-steps' if which == 'all' else which or 'now'}.csv"
    return Response(forecast_export.to_csv(table), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/buildings/{building_id}/scene")
def building_scene(building_id: int) -> dict:
    """The site in three dimensions: height grid, photo, roof outlines and the measured tall things."""
    _site_model(building_id)
    found = site_model.scene(building_id)
    if found is None:
        raise HTTPException(404, "this site has no height model yet")
    return found


@app.get("/api/buildings/{building_id}/heights.png")
def building_heights(building_id: int) -> FileResponse:
    """Height above ground on a half-metre grid, packed two bytes to a cell. See /scene for how to read it."""
    path = site_model.OPEN / "reconstruct" / str(building_id) / "heights.png"
    if not path.exists():
        raise HTTPException(404, "this site has no height model yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "max-age=3600"})


# --- a room as it was, cleared, and furnished again ----------------------------------------------
FURNISHING: dict[str, dict] = {}     # scan id -> the model-making run in progress, if any


def _furnish_scene(building_id: int, scan_id: str) -> dict:
    from .openproblems import furnish3d
    s = _site(building_id)
    if scan_id not in s.scans:
        raise HTTPException(404, "no such scan at this building")
    found = furnish3d.scene(scan_id)
    if found is None:
        raise HTTPException(404, "the furniture in this scan has not been read yet")
    return {**found, "making": FURNISHING.get(scan_id)}


@app.get("/api/buildings/{building_id}/furnish/{scan_id}")
def furnish_scene(building_id: int, scan_id: str) -> dict:
    """One room in three states: as scanned, cleared, and furnished again with generated models where the furniture stood."""
    return _furnish_scene(building_id, scan_id)


@app.get("/api/buildings/{building_id}/furnish/{scan_id}/cleared/{sweep_id}/{face}.jpg")
def furnish_cleared_face(building_id: int, scan_id: str, sweep_id: str, face: int, size: int = Query(1024, ge=256, le=2048)) -> Response:
    """One cube face of Matterport's defurnished view at a scan position."""
    from .openproblems import furnish3d
    s = _site(building_id)
    scan = s.scans.get(scan_id)
    if scan is None or face not in range(6) or not any(x["id"] == sweep_id for x in scan["sweeps"]):
        raise HTTPException(404, "no such panorama")
    try:
        path = furnish3d.cleared_face(scan_id, sweep_id, face)
    except (furnish3d.Furnish3dError, matterport.MatterportError) as e:
        raise HTTPException(502, str(e))
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        return _jpeg(im, quality=82)


@app.get("/api/furnish/models/{key}.glb")
def furnish_model(key: str) -> FileResponse:
    from .openproblems import furnish3d
    path = furnish3d.MODELS / f"{key}.glb"
    if not re.fullmatch(r"[0-9a-f]{14}", key) or not path.exists():
        raise HTTPException(404, "no such model")
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "max-age=3600"})


@app.post("/api/buildings/{building_id}/furnish/{scan_id}/make")
def furnish_make(building_id: int, scan_id: str) -> dict:
    """Make a model for each piece that has none, in the background. Paid, capped, and needs the text-to-3D key."""
    from .openproblems import furnish3d
    scene = _furnish_scene(building_id, scan_id)
    if not scene["can_generate"]:
        raise HTTPException(409, f"models cannot be made: set {furnish3d.KEY_ENV} in .env, or the limit of {furnish3d.MAX_MODELS} has been reached")
    if (FURNISHING.get(scan_id) or {}).get("running"):
        return {"started": False, "running": True}

    def work() -> None:
        try:
            done = furnish3d.furnish(scan_id)
            FURNISHING[scan_id] = {"running": False, "made": done["made"], "stopped": done["stopped"]}
        except Exception as e:  # reported on the scene, not lost in a thread
            FURNISHING[scan_id] = {"running": False, "made": [], "stopped": str(e)}

    FURNISHING[scan_id] = {"running": True, "made": [], "stopped": None}
    threading.Thread(target=work, daemon=True).start()
    return {"started": True}


# --- a scanned building as a place to find your way in -------------------------------------------
def _place(model_id: str) -> dict:
    from . import wayfind
    if not re.fullmatch(r"[A-Za-z0-9]{6,20}", model_id) or not (matterport.MP_CACHE / model_id / "model.json").exists():
        raise HTTPException(404, "this scan is not on this computer")
    return wayfind.place(model_id)


@app.get("/api/places/{model_id}")
def place(model_id: str) -> dict:
    """A scanned building as a walkable place: levels, typed rooms, and every scan position with what it sees."""
    from . import wayfind, wayfind_look
    where = _place(model_id)
    try:
        wayfind.measured_ways(where, wayfind_look.lifts(where), wayfind.walls(model_id))     # measured once, kept for every question
    except matterport.MatterportError:
        pass
    return where


@app.get("/api/places/{model_id}/find")
def place_find(model_id: str, q: str, start: str | None = None, mover: str = "walking", chair_in: float = Query(27.0, ge=18, le=40)) -> dict:
    """Where something is in this building, and the way there from a scan position, on foot or in a wheelchair."""
    from . import wayfind
    _place(model_id)
    if mover not in ("walking", "wheelchair"):
        raise HTTPException(400, "mover is walking or wheelchair")
    return wayfind.find(model_id, q, start, mover, chair_in)


@app.get("/api/flood")
def flood_sites(water_ft: float = Query(4.0, ge=0, le=12)) -> dict:
    """Every Houston site the flood test can run on, with what that depth of water costs each if nothing is done."""
    from . import flood
    rows = []
    for s in flood.sites():
        r = flood.test(s["property_id"], water_ft)
        rows.append({"property_id": s["property_id"], "name": s["name"], "homes": s["homes"], "sale": s["sale"], "loss": r["do_nothing"]["loss"], "buildings_wet": r["do_nothing"]["buildings_wet"]})
    rows.sort(key=lambda r: -(r["loss"] or 0))
    return {"water_ft": water_ft, "sites": rows, "loss": sum(r["loss"] or 0 for r in rows)}


@app.get("/api/flood/{property_id}/scenario")
def flood_scenario(property_id: int, water_ft: float = Query(4.0, ge=0, le=12), budget: float = Query(500_000, ge=0),
                   hours: float = Query(48, ge=0, le=240), crews: int = Query(3, ge=1, le=12)) -> dict:
    """One run of the flood test in the shape the team's screens read: property, flood, budget, loss before and after, and each fix with where it goes."""
    from . import flood
    try:
        return flood.scenario(property_id, water_ft, budget, hours, crews)
    except flood.FloodError as e:
        raise HTTPException(404, str(e))


@app.get("/api/flood/{property_id}")
def flood_test(property_id: int, water_ft: float = Query(4.0, ge=0, le=12), budget: float | None = Query(None, ge=0),
               hours: float | None = Query(None, ge=0, le=240), crews: int = Query(3, ge=1, le=12)) -> dict:
    """A flood stress test for one site: the loss if nothing is done at a depth of water, and the plan a budget and the hours left buy."""
    from . import flood
    try:
        return flood.test(property_id, water_ft, budget, hours, crews)
    except flood.FloodError as e:
        raise HTTPException(404, str(e))


@app.get("/api/flood/{property_id}/water.png")
def flood_water(property_id: int, water_ft: float = Query(4.0, ge=0, le=12)) -> Response:
    """Where that depth of water would stand on the site, as a see-through layer on the aerial photo's bounds."""
    from . import flood
    try:
        return Response(flood.water_png(property_id, round(water_ft, 1)), media_type="image/png", headers={"Cache-Control": "max-age=3600"})
    except flood.FloodError as e:
        raise HTTPException(404, str(e))


# The rendered shots the show plays between the live pages. They sit under data/, which is never committed:
# some of them carry sponsor imagery.
FILM_DIR = DATA_DIR / "film"


@app.get("/api/film")
def film_clips() -> dict:
    """Which shots have been rendered, so the show plays a clip where there is one and the live page where there is not."""
    return {"clips": sorted(p.stem for p in FILM_DIR.glob("*.mp4"))} if FILM_DIR.is_dir() else {"clips": []}


@app.get("/api/film/{name}.mp4")
def film_clip(name: str) -> FileResponse:
    if not re.fullmatch(r"[a-z0-9_]{1,40}", name) or not (FILM_DIR / f"{name}.mp4").is_file():
        raise HTTPException(404, "no such shot")
    return FileResponse(FILM_DIR / f"{name}.mp4", media_type="video/mp4")


# What the person in the headset is seeing, for a second screen to show alongside. One per building; newest wins.
PLACE_LIVE: dict[str, dict] = {}


@app.post("/api/places/{model_id}/live")
def place_live_set(model_id: str, body: dict) -> dict:
    """The headset says where it is, which way it is looking and what it was last told."""
    _place(model_id)
    kept = {k: body.get(k) for k in ("position", "yaw", "pitch", "mover", "chair_in", "answer")}
    PLACE_LIVE[model_id] = {**kept, "rev": (PLACE_LIVE.get(model_id) or {}).get("rev", 0) + 1, "at": time.time()}
    return {"ok": True}


@app.get("/api/places/{model_id}/live")
def place_live(model_id: str) -> dict:
    """What the headset last said, for the second screen."""
    return PLACE_LIVE.get(model_id) or {"rev": 0}


@app.get("/api/places/{model_id}/pano/{sweep_id}/{face}.jpg")
def place_pano(model_id: str, sweep_id: str, face: int, size: int = Query(1024, ge=256, le=2048)) -> Response:
    """One cube face of a scan position (0 up, 1-4 sides clockwise from the position's heading, 5 down)."""
    where = _place(model_id)
    if face not in range(6) or not any(p["id"] == sweep_id for p in where["positions"]):
        raise HTTPException(404, "no such panorama")
    try:
        path = matterport.face_image(model_id, sweep_id, face)
    except matterport.MatterportError as e:
        raise HTTPException(502, str(e))
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.LANCZOS)
        return _jpeg(im, quality=80)


@app.post("/api/places/{model_id}/voice")
def place_voice(model_id: str) -> dict:
    """A short-lived key for the guide's voice in this building."""
    from . import wayfind
    where = _place(model_id)
    if not voice.ready():
        raise HTTPException(503, "voice is not configured on this machine")
    try:
        return voice.mint(voice.place_session(where, [e for e in wayfind.events() if e.get("model_id") == model_id]))
    except voice.VoiceError as e:
        raise HTTPException(502, str(e))


@app.get("/api/desk")
def storm_desk(scenario: str, step: str | None = None) -> dict:
    """What the storm desk decided for the whole portfolio at one forecast step, and the crew schedule as it stands now.

    The saved run is the agent's work: briefs, what it put to the owner, its statement. The schedule is recomputed
    on every read from the saved plans, so it is never staler than they are.
    """
    from . import desk
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    rows = []
    for r in desk.portfolio(sc["id"], step_id):
        if not r["plan_saved"]:
            continue
        record = portfolio_data.building(r["building_id"])
        # Where it is, and what its homes rent for, so the desk can be drawn on the ground.
        rows.append({**r, "lat": record.get("lat"), "lon": record.get("lon"), "rent": portfolio_data.rent(r["building_id"])})
    return {"scenario": sc["id"], "step": step_id, "run": desk.load(sc["id"], step_id), "schedule": desk.schedule(sc["id"], step_id), "buildings": rows}


@app.get("/api/site-model/board")
def site_model_board() -> dict:
    """Each of the six stages across every gathered building: how many sites it has run for, and its number."""
    return site_model.board()


@app.get("/api/buildings/{building_id}/site-model")
def building_site_model(building_id: int, request: Request) -> dict:
    """Everything known about one address, each fact with the sources it rests on."""
    model = _site_model(building_id)
    from . import report_check
    # Each report carries its check against the scan. Reading the site model never pays for a look: one already made is shown.
    model["reports"] = [{**row, "check": report_check.checked(building_id, row, look=False)}
                        for row in _resident_reports(building_id, request, model["reports"])]
    from . import response
    # What residents said becomes work, and a household that cannot stay needs somewhere to go.
    return {**model, "facts": site_model.facts(model), "responses": response.from_residents(model["reports"]),
            "homes_available": portfolio_data.homes_available_near(building_id)}


def _resident_reports(building_id: int, request: Request, filed: list[dict]) -> list[dict]:
    """What residents reported at a building, oldest first: the reports filed here and those sent through its case, each placed."""
    from .recovery.site_activity import case_activity
    return sorted(filed + site_model.place(building_id, case_activity(request, building_id)), key=lambda row: row["at"])


def _resident_report(building_id: int, report_id: str, request: Request) -> dict:
    _site_model(building_id)
    found = next((row for row in _resident_reports(building_id, request, site_model.load_reports(building_id)) if row["id"] == report_id), None)
    if found is None:
        raise HTTPException(404, "no such report at this building")
    return found


@app.get("/api/buildings/{building_id}/reports/{report_id}/check")
def building_report_check(building_id: int, report_id: str, request: Request) -> dict:
    """Whether one report fits the scan made before the storm, and what the scan's photograph showed there then.

    The verdict is worked out by code. The first read of a report also shows the photograph to the vision model, once."""
    from . import report_check
    return report_check.checked(building_id, _resident_report(building_id, report_id, request))


@app.get("/api/buildings/{building_id}/reports/{report_id}/before.jpg")
def building_report_before(building_id: int, report_id: str, request: Request) -> Response:
    """The scan's own photograph from the report's position, facing the way the report points: the picture the look is made from."""
    from . import report_check
    view = report_check.check(building_id, _resident_report(building_id, report_id, request))["view"]
    if not view or view.get("bearing_deg") is None:
        raise HTTPException(404, "the scan has no view for this report")
    image = report_check.photograph(building_id, view)
    if image is None:
        raise HTTPException(404, "the scan has no photograph in that direction")
    return _jpeg(image)


@app.get("/api/buildings/{building_id}/find")
def building_find(building_id: int, q: str) -> dict:
    """Find a thing in this building's scans by describing it. Answers only from what was indexed."""
    from .openproblems import search
    try:
        return {"query": q, "said": search.count(building_id, q)["statement"], "hits": search.search(building_id, q, k=8)}
    except search.SearchError:
        return {"query": q, "said": "This building's scans have not been indexed yet.", "hits": []}


@app.get("/api/buildings/{building_id}/measured")
def building_measured(building_id: int, scenario: str, step: str | None = None) -> dict:
    """The measurements that bear on each action of the saved plan, with their sources."""
    sc = _scenario(scenario)
    return {"actions": _measured(building_id, _plan(building_id, _plan_key(sc["id"], _step(sc, step))))}


@app.post("/api/buildings/{building_id}/reports")
def building_report(building_id: int, body: dict) -> dict:
    """File what a resident reports against the scanned room it names. It is recorded as reported, not judged."""
    _site_model(building_id)
    try:
        return site_model.add_report(building_id, str(body.get("text") or ""), body.get("scan_id") or None)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/buildings/{building_id}/reports")
def building_reports_clear(building_id: int) -> dict:
    site_model.clear_reports(building_id)
    return {"ok": True}


@app.post("/api/voice/session")
def voice_session(building: int, scenario: str, step: str | None = None, view: str = "headset") -> dict:
    """A short-lived key for the voice, already told about this building's saved plan. `view` is headset or screen."""
    if not voice.ready():
        raise HTTPException(503, "voice is not configured on this machine")
    try:
        brief = _voice_brief(building, scenario, step)
        return voice.mint(voice.session(*brief, view, measured=_measured(building, brief[2])))
    except voice.VoiceError as e:
        raise HTTPException(502, str(e))


@app.get("/api/voice/notes")
def voice_notes(building: int, scenario: str, step: str | None = None, view: str = "headset") -> dict:
    """The notes for another forecast step, so a conversation already under way can be told the plan has changed."""
    brief = _voice_brief(building, scenario, step)
    return {"instructions": voice.instructions(*brief, view, measured=_measured(building, brief[2]))}


# --- plan runs -------------------------------------------------------------------
class Run:
    """A live plan: a worker thread appending events that any number of streams can follow."""

    def __init__(self, site: Site, threat: dict, resident_reports: list[dict]):
        self.events: list[dict] = []
        self.done = False
        self.lock = threading.Lock()
        threading.Thread(target=self._work, args=(site, threat, resident_reports), daemon=True).start()

    def _work(self, site: Site, threat: dict, resident_reports: list[dict]) -> None:
        try:
            Planner(site, threat, emit=self._emit, resident_reports=resident_reports).run()
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
def start_plan(property_id: int, scenario: str, request: Request, step: str | None = None) -> dict:
    sc = _scenario(scenario)
    step_id = _step(sc, step)
    s = _site(property_id)
    key = (property_id, _plan_key(scenario, step_id))
    run = RUNS.get(key)
    if run is None or run.done:
        from .recovery.site_activity import case_activity

        threat = screen.threat_for(scenario, step_id, s.d["record"])
        reports = case_activity(request, property_id, scenario=scenario, reports_only=True, replay=bool(threat.get("replay")))
        reports = sorted(reports, key=lambda row: row["at"], reverse=True)[:20]
        inputs = [{"id": row["id"], "reported_at": row["at"], "text": row["text"][:1000],
                   "review_status": row["status"]} for row in reports]
        RUNS[key] = Run(s, threat, inputs)
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


# Recovery is opt-in while teammates finish the owner/resident workspaces.
# Enabling it also protects every legacy API; owner login has no default secret.
if os.environ.get("BRACE_RECOVERY_ENABLED") == "1":
    from .recovery.local import install_local_recovery

    install_local_recovery(app)
