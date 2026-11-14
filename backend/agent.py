"""The preparation agent: turns a forecast and one building into a fix list, notices and work orders.

A manual tool loop (rather than the SDK tool runner) because every step is streamed
to the UI and tool results carry images.
"""
from __future__ import annotations

import json
import time
import traceback
from typing import Any, Callable

import anthropic
from PIL import Image
from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon

from . import matterport, vexcel, vision
from .building import Site
from .config import AGENT_EFFORT, AGENT_MODEL, MAX_AGENT_TURNS
from .preparation_notices import NOTICE_RULES, correct_notice

Emit = Callable[[dict], None]
CREW_STANDDOWN_HOURS = 6  # outdoor crews stop this long before damaging conditions arrive

SYSTEM = """You are Brace. You prepare one commercial building for a specific storm or wildfire threat that is in the forecast right now, on behalf of its owner or property manager.

You are not producing a risk score. Owners distrust scores. You produce a short, specific list of things to do, each tied to something you can point at on this building, with a rough cost and who does it, plus the messages that get it done: a notice to tenants or residents and work orders for contractors.

What you have
- The record: building type, age, construction, size, manager, and who occupies it.
- The threat: what is forecast for this exact site and how many hours are left before damaging conditions arrive.
- The outside: an overhead photo of the site with each structure outlined and numbered (S1, S2...), roof analysis per structure, angled photos from four sides, and a detector you can point at the site.
- The inside: 3D scans of some spaces in the building. These are scans of individual leasable or shared spaces (a suite, an apartment unit, a leasing office, a gym, a warehouse bay), not of the whole building. There is no scan of plant rooms. Use them for what they do show: how much glass a space has and which way it faces, whether it is at ground level, what sits on or near the floor, exterior and roll-up doors. Say plainly when a risk depends on a space that was not scanned.

How to work
- Read the record, the threat, the site facts and the measurements, and look at the site from above before anything else. When you give a height or a distance, use a measurement and say it is measured.
- Open a lead for each specific vulnerability that this threat makes matter, then resolve every lead: add one or more actions, or close it as not a concern or as impossible to check. Let the threat pick the leads. Wind: roof coverings and edges, rooftop equipment, loose objects, trees over the building, large glass, roll-up doors, canopies and carports. Flooding: ground-level spaces and what sits on their floors, low entrances and docks, parking, drains. Wildfire: vegetation touching or near walls, debris on roofs and in gutters, combustible storage and fences against the building, vents, wood construction.
- Look before you write. The roof analysis and the detector are pointers and they are sometimes wrong or out of date; the scan survey is a first pass. Confirm with your own eyes, from more than one angle when it is unclear.
- Match the action to the clock. With 36 hours left nobody re-roofs a building. "before_arrival" actions must be things a crew or the on-site team can finish in the time left, allowing for crews leaving site six hours before conditions turn. Put real repairs under "after_event" (do it once this threat has passed, before the next one) or "capital" (plan and budget).
- Be specific about place: name the structure and the grid cell or the scanned space. "Secure the eleven rooftop units on S1" is useful; "secure rooftop equipment" is not.
- Report what you see, not what would make a longer list. Six actions someone will actually do beat twenty. A lead that turns out fine is a result.

Each action needs: timing, hours of work, who does it, a rough cost range in dollars, and one or two sentences on why, written for a property manager. Cost anchors: on-site staff tasks 0-500; tree crew for a day 800-3,000; strapping or checking rooftop units 150-400 per unit; temporary roof patching 500-3,000; boarding or filming a storefront 15-40 per square foot of glass; sandbags or a door flood barrier 300-2,500 per opening; moving ground-floor equipment and stock 200-2,000; brush clearing around a building 1,000-6,000; ember-resistant vent retrofit 150-300 per vent; full re-roof of a low-rise commercial building 8-20 per square foot of roof.

Mark each action's basis honestly: "seen" if you looked at the thing in a photo or scan and can point to it; "record" if it follows from the building record or the forecast alone.

Before you finish, write the messages. A notice to the people in the building (tenants for commercial, residents for apartments): plain, calm, specific to this building and this threat, what to do and by when. A work order for each outside trade your actions need: scope, location on site, deadline. Use only names and facts from the record; never invent a phone number, a person or a policy. Structure ids and grid cells are this tool's own labels: people in the building do not know them, so in a notice describe places in plain words (the courtyard beside the leasing office, the covered parking along the east drive). In a work order you may give the id and cell as well, since the marked site photo goes with it.

Site grid: the overhead photo carries a lettered grid (columns A, B, C... west to east; rows 1, 2, 3... north to south). Refer to places by structure id and cell, such as S2 at D14.

When every lead is resolved and the messages are drafted, call finish with a one-line headline and a short summary. Write plainly, without jargon. You cannot see structure, wiring, plumbing, drainage capacity or anything hidden; do not speculate about them."""

DIRECTIONS = ["up", "down", "north", "east", "south", "west"]
VIEWS = ["overhead", "from-north", "from-east", "from-south", "from-west"]
# "from-south" means the camera is south of the building looking north, which Vexcel calls oblique-north.
VIEW_TO_OBLIQUE = {"from-south": "oblique-north", "from-west": "oblique-east",
                   "from-north": "oblique-south", "from-east": "oblique-west"}
TIMINGS = ["before_arrival", "after_event", "capital"]

EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
SYSTEM += "\n" + NOTICE_RULES

TOOLS: list[dict[str, Any]] = [
    {"name": "get_building", "description": "The building record: type, age, construction, size, manager and owner if known, and the tenants recorded as occupying it now.", "input_schema": EMPTY},
    {"name": "get_threat", "description": "The threat at this site: what is forecast here, how many hours are left, and the site's standing flood and fire zoning.", "input_schema": EMPTY},
    {"name": "get_site_facts", "description": "Machine-read facts from the aerial imagery for each structure on the site: roof material, shape and condition (1 worst to 5 best), flagged roof defects, counted rooftop objects, tree cover over the roof and close to the walls; plus site-wide tree cover and the date of the analysis.", "input_schema": EMPTY},
    {"name": "get_measurements", "description": "Measurements of this site, each with the source it rests on: how high each roof stands and the tallest thing beside it (from the aerial surface model), which roof each scanned space is under, the windows and outside doors measured in each scan, and what is counted on the grounds. Use these numbers instead of estimating a height or a distance from a photo. A measurement says how big or how near something is, not what it is: look before calling a tall thing a tree.", "input_schema": EMPTY},
    {"name": "view_site",
     "description": "Look at the site from the air. 'overhead' is the straight-down photo with the grid and each structure outlined and labelled; zoom_cell enlarges the area around one cell. The four 'from-...' views are angled photos taken from that side (walls, glass, roof edges, equipment); structure picks which building they centre on (default the largest).",
     "input_schema": {"type": "object", "properties": {
         "view": {"type": "string", "enum": VIEWS},
         "zoom_cell": {"type": "string", "description": "Grid cell to enlarge, e.g. F7. Overhead only."},
         "structure": {"type": "string", "description": "Structure id such as S2, for angled views."}},
         "required": ["view"], "additionalProperties": False}},
    {"name": "find_on_site",
     "description": "Run an open-vocabulary detector over the overhead photo of the site. Give short, specific labels (for example 'rooftop air conditioner', 'cooling tower', 'dumpster', 'patio furniture', 'shade sail', 'carport canopy', 'propane tank', 'wood fence', 'tree touching building', 'roof drain', 'skylight'). Returns each detection's grid cell, structure and confidence, and a marked-up photo. Detections are pointers, not proof.",
     "input_schema": {"type": "object", "properties": {
         "labels": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6}},
         "required": ["labels"], "additionalProperties": False}},
    {"name": "list_scans", "description": "The 3D scans attached to this building: what each space is, its size, which structure it is in, its floor when known, and its scan position ids.", "input_schema": EMPTY},
    {"name": "survey_scan",
     "description": "A fast automated first pass over one scan: for a spread of positions, how much glass, ground or upper level, what sits near the floor, exterior doors. Use it to decide where to look yourself.",
     "input_schema": {"type": "object", "properties": {"scan_id": {"type": "string"}}, "required": ["scan_id"], "additionalProperties": False}},
    {"name": "look",
     "description": "Look from one position in a scan: toward a compass direction, or up or down. Returns the photo and the true bearing of the view.",
     "input_schema": {"type": "object", "properties": {
         "scan_id": {"type": "string"}, "sweep_id": {"type": "string"},
         "direction": {"type": "string", "enum": DIRECTIONS}},
         "required": ["scan_id", "sweep_id", "direction"], "additionalProperties": False}},
    {"name": "open_lead",
     "description": "Register a specific vulnerability worth checking before you investigate it. The manager sees the list and how each was resolved.",
     "input_schema": {"type": "object", "properties": {
         "title": {"type": "string", "description": "Short and specific, e.g. 'Eleven rooftop units on the garage roof (S1)'"},
         "hazard": {"type": "string", "enum": ["wind", "flood", "fire", "general"]},
         "why": {"type": "string", "description": "One sentence: what prompted this and what would settle it."}},
         "required": ["title", "hazard", "why"], "additionalProperties": False}},
    {"name": "add_action",
     "description": "Add one action to the plan under a lead. A lead may get several actions. 'before_arrival' actions must fit in the time left.",
     "input_schema": {"type": "object", "properties": {
         "lead_id": {"type": "string"},
         "title": {"type": "string", "description": "Imperative and specific: what to do and where."},
         "hazard": {"type": "string", "enum": ["wind", "flood", "fire", "general"]},
         "timing": {"type": "string", "enum": TIMINGS},
         "hours_of_work": {"type": "number", "description": "Elapsed hours a crew needs once on site."},
         "crew": {"type": "string", "description": "Who does it: on-site staff, roofer, tree crew, glazier, tenant..."},
         "cost_low": {"type": "integer"}, "cost_high": {"type": "integer"},
         "why": {"type": "string", "description": "One or two sentences for the manager: what you saw and what it prevents."},
         "basis": {"type": "string", "enum": ["seen", "record"]},
         "structure": {"type": "string", "description": "Structure id, if the action is at one building."},
         "site_cell": {"type": "string", "description": "Grid cell of the spot on the site, if any."},
         "aerial_view": {"type": "string", "enum": VIEWS, "description": "The aerial view that best shows it, if any."},
         "scan_id": {"type": "string"}, "sweep_id": {"type": "string"},
         "direction": {"type": "string", "enum": DIRECTIONS}},
         "required": ["lead_id", "title", "hazard", "timing", "hours_of_work", "crew", "cost_low", "cost_high", "why", "basis"],
         "additionalProperties": False}},
    {"name": "close_lead",
     "description": "Resolve a lead without an action: 'not_a_concern' if you checked and it is fine, 'cannot_check' if the imagery cannot settle it (say what was missing). A lead that has actions is already resolved.",
     "input_schema": {"type": "object", "properties": {
         "lead_id": {"type": "string"},
         "outcome": {"type": "string", "enum": ["not_a_concern", "cannot_check"]},
         "note": {"type": "string"}},
         "required": ["lead_id", "outcome", "note"], "additionalProperties": False}},
    {"name": "draft_message",
     "description": "Draft a message that gets the plan done: a notice to the people in the building, or a work order to one outside trade.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": ["notice", "work_order"]},
         "to": {"type": "string", "description": "Audience or trade, e.g. 'All tenants', 'Residents', 'Roofing contractor', 'Tree crew'."},
         "subject": {"type": "string"},
         "body": {"type": "string", "description": "The full message, ready to send. Plain text."},
         "action_ids": {"type": "array", "items": {"type": "string"}, "description": "The actions this message covers."}},
         "required": ["kind", "to", "subject", "body"], "additionalProperties": False}},
    {"name": "finish",
     "description": "End once every lead is resolved and the messages are drafted.",
     "input_schema": {"type": "object", "properties": {
         "headline": {"type": "string", "description": "One sentence the manager reads first."},
         "summary": {"type": "string", "description": "Three to five sentences: what to do first, what waits, what could not be checked."}},
         "required": ["headline", "summary"], "additionalProperties": False}},
]


class ToolError(Exception):
    """A problem the agent can act on; returned to it as an error result."""


class Planner:
    """One run of the agent over one building for one threat. Holds the run state and implements the tools."""

    def __init__(self, site: Site, threat: dict, emit: Emit | None = None, client: anthropic.Anthropic | None = None):
        self.site = site
        self.threat = threat
        self.client = client or anthropic.Anthropic()
        self._emit = emit or (lambda e: None)
        self.events: list[dict] = []
        self.leads: list[dict] = []
        self.actions: list[dict] = []
        self.messages: list[dict] = []
        self.result: dict | None = None
        self.views = 0
        self.focus: dict | None = None  # where the agent is looking, so the UI can follow along
        self.t0 = time.time()
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        self.key = f"{threat['scenario_id']}__{threat.get('step_id') or 'now'}"
        self.run_dir = site.dir / "plans" / self.key
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # --- plumbing --------------------------------------------------------------
    def emit(self, type_: str, **data: Any) -> None:
        event = {"type": type_, "t": round(time.time() - self.t0, 2), **data}
        self.events.append(event)
        self._emit(event)

    def _save(self, im: Image.Image, name: str | None = None) -> str:
        if name is None:
            self.views += 1
            name = f"view_{self.views:03d}.jpg"
        im = im.convert("RGB")
        im.thumbnail((1500, 1500), Image.LANCZOS)
        im.save(self.run_dir / name, "JPEG", quality=82)
        return f"plans/{self.key}/{name}"

    def _image_result(self, text: str, im: Image.Image) -> tuple[list[dict], str]:
        rel = self._save(im)
        return [{"type": "text", "text": text}, vision.image_block(self.site.dir / rel, max_side=1400)], rel

    def _lead(self, lead_id: str) -> dict:
        for lead in self.leads:
            if lead["id"] == lead_id:
                return lead
        raise ToolError(f"no lead with id {lead_id}; leads so far: {[l['id'] for l in self.leads]}")

    def _scan(self, scan_id: str) -> dict:
        if scan_id not in self.site.scans:
            raise ToolError(f"unknown scan_id {scan_id}; use list_scans")
        return self.site.scans[scan_id]

    def _structure_wkt(self, structure: str | None) -> tuple[str, str]:
        sid = (structure or self.site.d["structures"][0]["id"]).upper()
        if sid not in self.site.structures:
            raise ToolError(f"unknown structure {structure}; this site has {list(self.site.structures)}")
        return sid, self.site.polys[sid].wkt

    @property
    def hours_left(self) -> float | None:
        return self.threat.get("hours_left")

    # --- tools -----------------------------------------------------------------
    def t_get_building(self) -> tuple[Any, str, str | None]:
        d = self.site.d
        r = {k: v for k, v in d["record"].items() if k not in ("model_ids", "photo", "lat", "lon", "id") and v not in (None, {}, [])}
        r["tenants_now"] = [{k: v for k, v in t.items() if v} for t in d["tenants"][:25]]
        r["tenants_total"] = d["record"].get("tenant_count")
        return json.dumps(r, indent=1), "Reading the building record", None

    def t_get_threat(self) -> tuple[Any, str, str | None]:
        t = {k: v for k, v in self.threat.items() if k not in ("scenario_id", "step_id")}
        if self.hours_left is not None:
            t["usable_crew_hours_before_arrival"] = max(0, round(self.hours_left - CREW_STANDDOWN_HOURS, 1))
        return json.dumps(t, indent=1), "Reading the forecast for this site", None

    def t_get_site_facts(self) -> tuple[Any, str, str | None]:
        d = self.site.d
        out = {"site": {k: v for k, v in d["site"].items() if k != "parcel"},
               "aerial_photo_captured": d["aerial"]["captured"],
               "angled_views_available": [k for k, v in VIEW_TO_OBLIQUE.items() if v in d["aerial"]["obliques"]],
               "structures": [{k: v for k, v in s.items() if k not in ("polygon", "centroid")} | {"grid_cell": self.site.cell_of(*s["centroid"])}
                              for s in d["structures"]],
               "note": "Structure ids match the labels on the overhead photo. The roof analysis can be older than the photo."}
        return json.dumps(out, indent=1), "Reading the roof analysis", None

    def t_get_measurements(self) -> tuple[Any, str, str | None]:
        from . import site_model
        try:
            model = site_model.build(self.site.d["record"]["id"])
        except KeyError:
            return "No measurements have been assembled for this site.", "Reading the site's measurements", None
        out = {"stages": [{"stage": s["key"], "state": s["state"], "result": s["headline"]} for s in model["stages"]],
               "measurements": site_model.measured_notes(model),
               "note": "Each line names its source. Where a stage has not run for this site there is no measurement; do not fill one in."}
        return json.dumps(out, indent=1), "Reading the site's measurements", None

    def t_view_site(self, view: str, zoom_cell: str | None = None, structure: str | None = None) -> tuple[Any, str, str | None]:
        s = self.site
        if view == "overhead":
            im = s.render_aerial(grid=True, crop_cell=zoom_cell)
            text = (f"Overhead photo of the site. Grid columns A-{s.cell_name(s.cols - 1, 0)[0]} west to east, rows 1-{s.rows} north to south; "
                    f"each cell is about {s.d['aerial']['grid']['cell_m']:.0f} m. Yellow outlines: structures, labelled S1, S2...")
            if zoom_cell:
                lon, lat = s.cell_center(zoom_cell)
                self.focus = {"lon": lon, "lat": lat, "cell": zoom_cell.upper()}
                text += f" Enlarged around {zoom_cell.upper()}."
            content, rel = self._image_result(text, im)
            return content, "Looking at the site from above" + (f" near {zoom_cell.upper()}" if zoom_cell else ""), rel
        oblique = VIEW_TO_OBLIQUE[view]
        if oblique not in s.d["aerial"]["obliques"]:
            raise ToolError(f"no angled view {view} here; available: {[k for k, v in VIEW_TO_OBLIQUE.items() if v in s.d['aerial']['obliques']] or 'none'}")
        sid, wkt = self._structure_wkt(structure)
        path, _ = vexcel.oblique(wkt, oblique, buffer_m=10)
        with Image.open(path) as im:
            im = im.convert("RGB")
            if max(im.size) < 1000:
                f = min(3.0, 1200 / max(im.size))
                im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        side = view.split("-")[1]
        c = s.structures[sid]["centroid"]
        self.focus = {"lon": c[0], "lat": c[1], "structure": sid, "view": view}
        content, rel = self._image_result(f"Angled aerial photo of {sid} taken from the {side}; {sid} is in the centre of the frame.", im)
        return content, f"Looking at {sid} from the {side}", rel

    def t_find_on_site(self, labels: list[str]) -> tuple[Any, str, str | None]:
        s = self.site
        w, so, e, n = s.bounds
        area = Polygon([(w, so), (e, so), (e, n), (w, n)]).wkt
        dets = vexcel.detect(area, [l.strip().lower() for l in labels if l.strip()])
        rows, markers = [], []
        for i, det in enumerate(sorted(dets, key=lambda d: -d["confidence"])[:24], 1):
            c = shapely_wkt.loads(det["bbox_wkt"]).centroid
            st = s.structure_at(c.x, c.y)
            rows.append({"n": i, "label": det["label"], "confidence": det["confidence"], "cell": s.cell_of(c.x, c.y),
                         "on_or_beside": st["id"] if st else None})
            markers.append({"lon": c.x, "lat": c.y, "label": f"{i} {det['label']}", "color": (255, 64, 255, 255)})
        what = ", ".join(labels)
        if not rows:
            return f"Nothing detected for {labels}.", f"Scanning the site for {what}", None
        content, rel = self._image_result(json.dumps(rows, indent=1), s.render_aerial(grid=True, markers=markers))
        return content, f"Scanning the site for {what}", rel

    def t_list_scans(self) -> tuple[Any, str, str | None]:
        rows = [{"scan_id": sc["id"], "name": sc["name"], "kind": sc["kind"], "floor": sc["level"], "structure": sc.get("structure"),
                 "area_sqft": sc["area_sqft"], "captured_at": sc.get("captured_at"),
                 "model_created_at": sc.get("model_created_at"), "positions": len(sc["sweeps"]),
                 "sweep_ids": [x["id"] for x in sc["sweeps"]][:30]} for sc in self.site.d["scans"]]
        note = ("Scans cover individual spaces, not the whole building. Model creation is not capture time; "
                "structure associations from GPS are unverified candidates.") if rows else "No scans are attached to this building."
        return json.dumps({"scans": rows, "note": note}, indent=1), "Listing the scanned spaces", None

    def t_survey_scan(self, scan_id: str) -> tuple[Any, str, str | None]:
        sc = self._scan(scan_id)
        rows = vision.survey(self.site, scan_id, self.client)
        if not rows:
            raise ToolError("the survey could not read this scan; use look on individual positions instead")
        first = next((x for x in sc["sweeps"] if x["id"] == rows[0]["sweep_id"]), None)
        if first and first["lon"] is not None:
            self.focus = {"lon": first["lon"], "lat": first["lat"], "scan_id": scan_id, "sweep_id": first["id"], "direction": "north"}
        return json.dumps({"scan": sc["name"], "positions": rows}, indent=1), f"Surveying the scan: {sc['name']}", None

    def t_look(self, scan_id: str, sweep_id: str, direction: str) -> tuple[Any, str, str | None]:
        sc = self._scan(scan_id)
        sweep = next((x for x in sc["sweeps"] if x["id"] == sweep_id), None)
        if sweep is None:
            raise ToolError(f"unknown sweep_id {sweep_id} for this scan; valid ids come from list_scans or survey_scan")
        face, bearing = self.site.face_for(scan_id, sweep_id, direction)
        path = matterport.face_image(scan_id, sweep_id, face)
        text = f"View {direction} from a position in '{sc['name']}'."
        if bearing is not None:
            text += f" True compass bearing of this view: {bearing:.0f} degrees."
        elif direction not in ("up", "down"):
            text += " This scan has no compass fix, so the direction is approximate."
        content, rel = self._image_result(text, Image.open(path))
        self.focus = {"lon": sweep["lon"], "lat": sweep["lat"], "scan_id": scan_id, "sweep_id": sweep_id, "direction": direction}
        return content, f"Looking {direction} in {sc['name']}", rel

    def t_open_lead(self, title: str, hazard: str, why: str) -> tuple[Any, str, str | None]:
        lead = {"id": f"L{len(self.leads) + 1}", "title": title, "hazard": hazard, "why": why, "status": "open", "action_ids": []}
        self.leads.append(lead)
        self.emit("lead", lead=lead)
        return f"Lead {lead['id']} opened.", f"New lead: {title}", None

    def t_add_action(self, **a: Any) -> tuple[Any, str, str | None]:
        s = self.site
        lead = self._lead(a["lead_id"])
        if a["cost_low"] > a["cost_high"]:
            raise ToolError("cost_low is greater than cost_high")
        if a["hours_of_work"] <= 0:
            raise ToolError("hours_of_work must be positive")
        if a["timing"] == "before_arrival" and self.hours_left is not None:
            usable = self.hours_left - CREW_STANDDOWN_HOURS
            if a["hours_of_work"] > usable:
                raise ToolError(f"this needs {a['hours_of_work']} hours of work but only about {max(0, usable):.0f} usable crew hours remain "
                                "before conditions arrive. Split out the part that fits, or file it under after_event or capital.")
        has_place = bool(a.get("site_cell") or a.get("structure") or (a.get("scan_id") and a.get("sweep_id")))
        if a["basis"] == "seen" and not has_place:
            raise ToolError("basis 'seen' needs a place you looked at: a structure, a site_cell, or a scan position. Otherwise use basis 'record'.")
        aid = f"A{len(self.actions) + 1}"
        action: dict[str, Any] = {"id": aid, **{k: a[k] for k in ("lead_id", "title", "hazard", "timing", "hours_of_work", "crew",
                                                                 "cost_low", "cost_high", "why", "basis")},
                                  "structure": None, "site": None, "interior": None}
        lon = lat = None
        if a.get("structure"):
            sid, _ = self._structure_wkt(a["structure"])
            action["structure"] = sid
            lon, lat = s.structures[sid]["centroid"]
        if a.get("site_cell"):
            lon, lat = s.cell_center(a["site_cell"])
        if lon is not None:
            crop = s.render_aerial(grid=False, markers=[{"lon": lon, "lat": lat}], crop_cell=s.cell_of(lon, lat))
            action["site"] = {"lon": lon, "lat": lat, "cell": s.cell_of(lon, lat), "image": self._save(crop, f"{aid}_site.jpg")}
        if a.get("aerial_view") and a["aerial_view"] != "overhead" and VIEW_TO_OBLIQUE[a["aerial_view"]] in s.d["aerial"]["obliques"]:
            sid, wkt = self._structure_wkt(action["structure"])
            path, _ = vexcel.oblique(wkt, VIEW_TO_OBLIQUE[a["aerial_view"]], buffer_m=10)
            with Image.open(path) as im:
                action["site"] = (action["site"] or {}) | {"oblique_view": a["aerial_view"], "oblique_image": self._save(im, f"{aid}_oblique.jpg")}
        if a.get("scan_id") and a.get("sweep_id"):
            sc = self._scan(a["scan_id"])
            sweep = next((x for x in sc["sweeps"] if x["id"] == a["sweep_id"]), None)
            if sweep is None:
                raise ToolError(f"unknown sweep_id {a['sweep_id']} for scan {a['scan_id']}")
            direction = a.get("direction") or "north"
            face, bearing = s.face_for(a["scan_id"], a["sweep_id"], direction)
            with Image.open(matterport.face_image(a["scan_id"], a["sweep_id"], face)) as im:
                rel = self._save(im, f"{aid}_interior.jpg")
            action["interior"] = {"scan_id": a["scan_id"], "scan_name": sc["name"], "sweep_id": a["sweep_id"], "direction": direction,
                                  "bearing": bearing, "image": rel, "lon": sweep["lon"], "lat": sweep["lat"]}
        self.actions.append(action)
        lead["status"] = "actions"
        lead["action_ids"].append(aid)
        self.emit("action", action=action)
        self.emit("lead_closed", lead=lead)
        return f"Action {aid} added under {lead['id']}.", f"Action: {a['title']}", None

    def t_close_lead(self, lead_id: str, outcome: str, note: str) -> tuple[Any, str, str | None]:
        lead = self._lead(lead_id)
        if lead["action_ids"]:
            raise ToolError(f"{lead_id} already has actions {lead['action_ids']}; it is resolved.")
        lead["status"] = outcome
        lead["note"] = note
        self.emit("lead_closed", lead=lead)
        return f"Lead {lead_id} closed as {outcome}.", f"{'Not a concern' if outcome == 'not_a_concern' else 'Could not check'}: {lead['title']}", None

    def t_draft_message(self, kind: str, to: str, subject: str, body: str, action_ids: list[str] | None = None) -> tuple[Any, str, str | None]:
        known = {a["id"] for a in self.actions}
        bad = [x for x in action_ids or [] if x not in known]
        if bad:
            raise ToolError(f"unknown action ids {bad}; actions so far: {sorted(known)}")
        msg = {"id": f"M{len(self.messages) + 1}", "kind": kind, "to": to, "subject": subject, "body": body, "action_ids": action_ids or []}
        msg = correct_notice(msg, self.threat)
        self.messages.append(msg)
        self.emit("message", message=msg)
        return f"Message {msg['id']} drafted.", f"Drafted {'a notice' if kind == 'notice' else 'a work order'} for {to}", None

    def t_finish(self, headline: str, summary: str) -> tuple[Any, str, str | None]:
        still_open = [l["id"] for l in self.leads if l["status"] == "open"]
        if still_open:
            raise ToolError(f"leads still open: {still_open}. Resolve each with add_action or close_lead first.")
        if self.actions and not any(m["kind"] == "notice" for m in self.messages):
            raise ToolError("draft the notice to the people in the building before finishing.")
        self.result = {"headline": headline, "summary": summary}
        return "Plan complete.", "Writing the plan", None

    # --- loop ------------------------------------------------------------------
    def _call_tool(self, name: str, args: dict) -> dict:
        fn = getattr(self, f"t_{name}", None)
        if fn is None:
            return {"content": f"Unknown tool {name}", "is_error": True}
        try:
            self.focus = None
            content, label, image = fn(**args)
            if name not in ("open_lead", "add_action", "close_lead", "draft_message"):
                self.emit("step", tool=name, label=label, image=image, focus=self.focus)
            return {"content": content}
        except (ToolError, ValueError, KeyError, TypeError) as e:
            return {"content": f"Error: {e}", "is_error": True}
        except (vexcel.VexcelError, matterport.MatterportError) as e:
            return {"content": f"Error: the imagery service failed ({e}). Try again or use another view.", "is_error": True}

    def run(self) -> dict:
        rec = self.site.d["record"]
        left = f" About {self.hours_left:.0f} hours remain before damaging conditions reach the site." if self.hours_left is not None else ""
        messages: list[dict] = [{"role": "user", "content": (
            f"Prepare {rec['name']} ({rec['type_label'].lower()}, {rec['address']}, {rec['city']}, {rec['state']}) for: "
            f"{self.threat.get('name')}, {self.threat.get('label') or 'current forecast'}.{left}")}]
        self.emit("status", label=f"Preparing {rec['name']} for {self.threat.get('name')}")
        stop = "max_turns"
        try:
            for _ in range(MAX_AGENT_TURNS):
                resp = self.client.beta.messages.create(
                    model=AGENT_MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=messages,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": AGENT_EFFORT},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
                for k in self.usage:
                    self.usage[k] += getattr(resp.usage, k, 0) or 0
                for block in resp.content:
                    if block.type == "thinking" and block.thinking:
                        self.emit("thinking", text=block.thinking)
                    elif block.type == "text" and block.text.strip():
                        self.emit("note", text=block.text.strip())
                if resp.stop_reason == "refusal":
                    stop = "refusal"
                    self.emit("error", message="The model declined to continue this plan.")
                    break
                # Thinking blocks must go back unchanged, so append the content as returned.
                messages.append({"role": "assistant", "content": resp.content})
                if resp.stop_reason == "pause_turn":
                    continue
                calls = [b for b in resp.content if b.type == "tool_use"]
                if not calls:
                    if self.result is None and resp.stop_reason == "end_turn":
                        messages.append({"role": "user", "content": "Resolve any open leads, draft the messages, then call finish."})
                        continue
                    stop = resp.stop_reason or "end_turn"
                    break
                results = [{"type": "tool_result", "tool_use_id": c.id, **self._call_tool(c.name, dict(c.input))} for c in calls]
                messages.append({"role": "user", "content": results})
                if self.result is not None:
                    stop = "finished"
                    break
        except anthropic.AuthenticationError:
            stop = "error"
            self.emit("error", message="No valid Anthropic credentials. Set ANTHROPIC_API_KEY in .env.")
        except anthropic.RateLimitError:
            stop = "error"
            self.emit("error", message="Rate limited by the Anthropic API. Wait a minute and run again.")
        except anthropic.APIStatusError as e:
            stop = "error"
            self.emit("error", message=f"Anthropic API error {e.status_code}: {e.message}")
        except anthropic.APIConnectionError:
            stop = "error"
            self.emit("error", message="Could not reach the Anthropic API.")
        except Exception as e:  # last resort: surface it in the UI rather than hang the stream
            stop = "error"
            traceback.print_exc()
            self.emit("error", message=f"Unexpected error: {e}")
        plan = self.plan(stop)
        if stop != "error":
            (self.site.dir / "plans" / f"{self.key}.json").write_text(json.dumps(plan))
        self.emit("done", stop=stop, plan={k: v for k, v in plan.items() if k != "events"})
        return plan

    def plan(self, stop: str) -> dict:
        order = {t: i for i, t in enumerate(TIMINGS)}
        actions = sorted(self.actions, key=lambda a: (order[a["timing"]], -a["cost_high"]))
        totals = {t: {"count": sum(1 for a in actions if a["timing"] == t),
                      "cost_low": sum(a["cost_low"] for a in actions if a["timing"] == t),
                      "cost_high": sum(a["cost_high"] for a in actions if a["timing"] == t),
                      "hours": round(sum(a["hours_of_work"] for a in actions if a["timing"] == t), 1)} for t in TIMINGS}
        return {
            "building_id": self.site.id, "threat": self.threat, "stop": stop, "complete": self.result is not None,
            "model": AGENT_MODEL, "seconds": round(time.time() - self.t0),
            "headline": (self.result or {}).get("headline"), "summary": (self.result or {}).get("summary"),
            "actions": actions, "totals": totals, "messages": self.messages, "leads": self.leads,
            "usage": self.usage, "events": self.events,
        }
