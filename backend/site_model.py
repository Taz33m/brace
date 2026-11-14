"""The Site Model: everything Brace knows about one address, in one object, with where each fact came from.

Six stages write into it, in the order a storm runs:

  join       which scan is which building: the CoStar record, the Vexcel roof and the Matterport scan made one place
  classify   what each room is
  inventory  what is on the site that the weather can reach: rooftop units, pools, carports, loose items
  expose     what is fixed and what is loose inside: the furnished scan against its defurnished copy
  surface    how high things stand: roofs, and whatever rises beside them
  search     what is visible from every scan position, so a thing can be found by describing it

The planner and the voice read this object, never the raw scans. After the event the same object takes
what residents report, so the after side adds to the before side instead of starting again.

Every fact carries `src`: the ids of the sources it rests on. `sources` says, for each id, which sponsor's
data it is, which capture or model, and when. That is what lets "15.5 metres" be traced to a flight.

Nothing here calls a model or a sponsor API. It assembles what the stages have already saved; a stage
that has not run for a site is reported as not run, never filled in.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import openings
from .building import building_dir
from .config import CACHE_DIR
from .matterport import MP_CACHE

OPEN = CACHE_DIR / "open"
VERSION = 1

# The six stages, in pipeline order: key, the open problem it answers, and its job in one line.
STAGES: list[tuple[str, str, str]] = [
    ("join", "Better geolocation", "Fits each scan's floor plan to the Vexcel roof outline, so the record, the roof and the scan are one place"),
    ("classify", "Understand commercial spaces", "Names what each scanned room is"),
    ("inventory", "Find and count amenities", "Counts and places what the weather can reach, and checks it against CoStar's listing"),
    ("expose", "Furnish an empty room", "Finds which scans have a defurnished copy, the basis for telling fixed from loose"),
    ("surface", "Splats from sparse imagery", "Measures roof heights and what stands beside each roof from Vexcel's surface model"),
    ("search", "Search inside panoramas", "Describes every scan position so a thing can be found by what it is"),
]


def _read(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _day(text: str | None) -> str | None:
    """Vexcel writes dates as 'Thu Feb 12 16:44:18 UTC 2026' inside its images; keep the day."""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%a %b %d %H:%M:%S %Z %Y").date().isoformat()
    except ValueError:
        return text[:10]


def fact(value: Any, src: list[str], *, how: str | None = None, limits: str | None = None, confidence: float | None = None) -> dict:
    """One thing the model holds: the value, the sources it rests on, how it was got, and what it cannot tell you."""
    out: dict[str, Any] = {"value": value, "src": src}
    if how:
        out["how"] = how
    if limits:
        out["limits"] = limits
    if confidence is not None:
        out["confidence"] = confidence
    return out


class _Sources:
    """The sources a site model rests on, each recorded once under a short id."""

    def __init__(self) -> None:
        self.by_id: dict[str, dict] = {}

    def add(self, sid: str, **about: Any) -> str:
        self.by_id.setdefault(sid, {k: v for k, v in about.items() if v is not None})
        return sid


def cached_property_ids() -> list[int]:
    """Buildings whose three-layer bundle has been gathered, which is what a site model is assembled from."""
    root = CACHE_DIR / "buildings"
    return sorted(int(p.name) for p in root.iterdir() if p.name.isdigit() and (p / "building.json").exists()) if root.exists() else []


def build(property_id: int, reports: list[dict] | None = None) -> dict:
    """Assemble the site model for one address from what each stage has saved."""
    bundle = _read(building_dir(property_id) / "building.json")
    if bundle is None:
        raise KeyError(f"no gathered bundle for property {property_id}")
    if reports is None:
        reports = load_reports(property_id)
    record, site, aerial = bundle["record"], bundle.get("site") or {}, bundle.get("aerial") or {}
    S = _Sources()
    costar = S.add(f"costar:property:{property_id}", provider="CoStar", what="commercial property record", id=property_id)
    photo = S.add("vexcel:aerial", provider="Vexcel", what="aerial photo of the site", captured=_day(aerial.get("captured")))
    attrs = S.add("vexcel:roof-analysis", provider="Vexcel", what="roof and grounds analysis per structure", captured=site.get("roof_analysis_date"),
                  note="the analysis can be older than the photo")
    stages: dict[str, dict] = {}

    # ---- surface: heights ----------------------------------------------------------------------------
    heights = _read(OPEN / "reconstruct" / str(property_id) / "heights.json")
    height_of: dict[str, dict] = {}
    if heights:
        surf, terr = heights["source"]["surface"], heights["source"]["terrain"]
        dsm = S.add(f"vexcel:surface:{surf['collection']}", provider="Vexcel", what="surface model (heights of roofs and trees)",
                    collection=surf["collection"], captured=f"{surf['first_capture']} to {surf['last_capture']}", ground_sample_m=surf.get("native_gsd_m"))
        dtm = S.add(f"vexcel:terrain:{terr['collection']}", provider="Vexcel", what="terrain model (bare ground)",
                    collection=terr["collection"], captured=f"{terr['first_capture']} to {terr['last_capture']}")
        how = "surface model minus terrain model, less the measured step between the two flights"
        # A height says how tall, not what. Where someone has looked at the spot on the photo, that is recorded beside it.
        looked = _read(OPEN / "reconstruct" / str(property_id) / "checked.json") or {}
        for st in heights.get("structures") or []:
            tall = st.get("tallest_nearby") or {}
            seen = (looked.get("structures") or {}).get(st["id"])
            height_of[st["id"]] = {
                "roof_height_m": fact(st.get("roof_height_m"), [dsm, dtm], how=how, limits="good to about half a metre"),
                "tallest_beside_it": fact(
                    None if not tall else {"height_m": tall.get("height_m"), "from_wall_m": tall.get("distance_to_wall_m"),
                                           "above_roof_m": tall.get("above_roof_m"), "lon": tall.get("lon"), "lat": tall.get("lat"),
                                           "what": (seen or {}).get("what")},
                    [dsm, dtm] + ([photo] if seen else []), how=how + "; the highest cell within 10 m of the footprint",
                    limits=(f"what it is: {seen['what']}, {looked.get('basis')}. {seen.get('note') or ''}".strip() if seen else
                            "not proven to be a tree" + ("; Vexcel reports trees within 30 ft of this roof" if tall.get("vexcel_reports_trees_within_30ft") else ""))),
            }
        stages["surface"] = {"state": "ready", "number": len(height_of), "unit": "roofs measured",
                             "headline": f"{len(height_of)} roofs measured at {heights['cell_m'][0]:.1f} m cells"}
    else:
        stages["surface"] = {"state": "not_run", "number": 0, "unit": "roofs measured", "headline": "No height model for this site yet"}

    # ---- join: where each scan sits ------------------------------------------------------------------
    joined = _read(OPEN / "geolocation" / f"{property_id}.json")
    placed_by: dict[str, dict] = {s["id"]: s for s in (joined or {}).get("scans") or []}

    # ---- classify and search: what each room is, and what is visible from each position --------------
    index = _read(OPEN / "search" / f"{property_id}.json")
    seen: dict[str, list[dict]] = {}
    for position in (index or {}).get("positions") or []:
        seen.setdefault(position["scan_id"], []).append(position)

    scans_out, typed_rooms, rooms_total, aligned, shifts = [], 0, 0, 0, []
    defurnished_found = 0
    for scan in bundle.get("scans") or []:
        sid = scan["id"]
        mp = S.add(f"matterport:{sid}", provider="Matterport", what="3D scan", model=sid, name=scan.get("name"),
                   created=(scan.get("model_created_at") or "")[:10] or None)

        j = placed_by.get(sid)
        if j is None:
            placement = fact({"status": "not checked", "structure": scan.get("structure")}, [mp], limits="the fit has not been run for this scan")
        elif j["status"] == "aligned":
            aligned += 1
            shifts.append(j["correction"]["shift_m"])
            placement = fact({"status": "aligned", "structure": j.get("structure"), "moved_m": j["correction"]["shift_m"],
                              "turned_deg": j["correction"]["rotation_deg"], "under_roof_before": j["raw"]["inside"], "under_roof_after": j["fitted"]["inside"],
                              "position": j["fitted"].get("position")},
                             [mp, attrs], how="the scan's floor plan fitted to the Vexcel roof outline, starting from Matterport's GPS",
                             limits="shows which roof the unit is under, not where along it" if not j.get("position_pinned") else None)
        else:
            placement = fact({"status": j.get("status_label") or j["status"], "structure": j.get("structure")}, [mp], limits=j.get("why"))

        # Rooms: Matterport's own label first; where it gave none, the type seen from a scan position in that room.
        commercial = _read(OPEN / "commercial" / f"{sid}.json")
        ours_by_room: dict[str, dict] = {}
        for room in (commercial or {}).get("rooms") or []:
            if room.get("ours"):
                ours_by_room[room["room_id"]] = {"type": room["ours"].get("type"), "confidence": room["ours"].get("confidence"), "by": "commercial room labelling"}
        for position in seen.get(sid, []):
            if position.get("room_id") and position.get("room_type") and position["room_id"] not in ours_by_room:
                ours_by_room[position["room_id"]] = {"type": position["room_type"], "confidence": None, "by": "seen from a scan position"}
        rooms = []
        for room in scan.get("rooms") or []:
            named = (room.get("type") or "").strip().lower() not in ("", "void", "other", "unlabelled", "unlabeled", "unknown")
            ours = ours_by_room.get(room["id"])
            rooms_total += 1
            if named or ours:
                typed_rooms += 1
            rooms.append({"id": room["id"], "matterport_type": room.get("type") or None,
                          "type": fact(room["type"] if named else (ours or {}).get("type"), [mp],
                                       how="Matterport's own room label" if named else ((ours or {}).get("by") if ours else None),
                                       confidence=None if named else (ours or {}).get("confidence"),
                                       limits=None if named or ours else "not typed: no label and no scan position inside it"),
                          "area_sqft": room.get("area_sqft")})

        # Openings come from the scan's wall measurements. Only what is already fetched is used here.
        walls = _read(MP_CACHE / "openings" / f"{sid}.json")
        plan = openings.layout(scan, walls) if walls else None
        outside = [o for o in (plan or {}).get("openings") or [] if o["outside"]]
        measured = None if plan is None else {
            "windows": sum(1 for o in outside if o["kind"] == "window"), "outside_doors": sum(1 for o in outside if o["kind"] == "door"),
            "largest": max(({"kind": o["kind"], "room": o["room"], "width_m": o["width_m"], "height_m": o["height_m"], "faces_deg": o["faces_deg"]}
                            for o in outside), key=lambda o: o["width_m"] * (o["height_m"] or 1), default=None)}

        has_defurnished = (OPEN / "reimagine" / "defurnished" / sid).is_dir()
        defurnished_found += has_defurnished
        scans_out.append({
            "id": sid, "name": scan.get("name"), "kind": scan.get("kind"),
            "placement": placement,
            "rooms": rooms,
            "outside_openings": fact(measured, [mp], how="Matterport's wall measurements; an opening in only one room's walls is on the outside",
                                     limits=None if plan else "wall measurements not fetched for this scan"),
            "defurnished_copy": fact(True if has_defurnished else None, [mp], how="Matterport's defurnished view of the same scan positions",
                                     limits=None if has_defurnished else "not checked for this scan"),
            "positions": len(scan.get("sweeps") or []), "positions_described": len(seen.get(sid, [])),
        })

    total_scans = len(scans_out)
    if joined:
        median = sorted(shifts)[len(shifts) // 2] if shifts else None
        stages["join"] = {"state": "ready" if aligned == total_scans and total_scans else "partial", "number": aligned, "unit": f"of {total_scans} scans fitted to a roof",
                          "headline": (f"{aligned} of {total_scans} scans fitted to a roof" + (f", moved a median {median:.1f} m" if median is not None else ""))}
    else:
        stages["join"] = {"state": "not_run", "number": 0, "unit": f"of {total_scans} scans fitted to a roof", "headline": "The fit has not been run for this site"}
    stages["classify"] = {"state": "not_run" if not typed_rooms else "ready" if typed_rooms == rooms_total else "partial", "number": typed_rooms, "unit": f"of {rooms_total} rooms typed",
                          "headline": f"{typed_rooms} of {rooms_total} scanned rooms have a type" if rooms_total else "No scanned rooms"}
    described = sum(s["positions_described"] for s in scans_out)
    every = sum(s["positions"] for s in scans_out)
    stages["search"] = {"state": "not_run" if not index else "ready" if described == every else "partial", "number": described, "unit": f"of {every} scan positions described",
                        "headline": f"{described} of {every} scan positions described" if index else "No search index for this site yet"}
    stages["expose"] = {"state": "partial" if defurnished_found else "not_run", "number": defurnished_found, "unit": f"of {total_scans} scans with a defurnished copy found",
                        "headline": (f"{defurnished_found} of {total_scans} scans have a defurnished copy on file" if defurnished_found
                                     else "Not checked for this site"),
                        "limits": "Only the scans checked so far are counted. Telling fixed from loose by comparing the two copies is not built."}

    # ---- structures ----------------------------------------------------------------------------------
    structures = []
    roof_objects: dict[str, int] = {}
    for st in bundle.get("structures") or []:
        for kind, n in (st.get("roof_objects") or {}).items():
            roof_objects[kind] = roof_objects.get(kind, 0) + int(n)
        structures.append({
            "id": st["id"], "footprint_sqft": st.get("footprint_sqft"),
            "roof": fact({"material": st.get("roof_material"), "shape": st.get("roof_shape"), "condition_1_to_5": st.get("roof_condition"),
                          "defects": st.get("roof_defects") or [], "objects": st.get("roof_objects") or {},
                          "tree_cover_percent": st.get("roof_tree_cover_percent"), "trees_within_5ft_percent": st.get("trees_within_5ft_percent")},
                         [attrs], how="Vexcel's machine reading of the aerial", limits="can be older than the photo"),
            **height_of.get(st["id"], {}),
            "scans": [s["id"] for s in scans_out if (s["placement"]["value"] or {}).get("structure") == st["id"]],
        })

    # ---- inventory -----------------------------------------------------------------------------------
    inv = _read(OPEN / "amenities" / f"{property_id}.json")
    exposure = [{"kind": kind.replace("-", " "), "count": fact(n, [attrs], how="counted on the roofs by Vexcel's analysis"), "where": "on the roofs", "listed_by_costar": None}
                for kind, n in sorted(roof_objects.items(), key=lambda kv: -kv[1])]
    if inv:
        detector = S.add("vexcel:detector", provider="Vexcel", what="open-vocabulary detection on the aerial", captured=_day(aerial.get("captured")))
        listed = {x["kind"] for x in (inv.get("comparison") or {}).get("listed_and_found") or []}
        for item in inv.get("amenities") or []:
            if not item.get("confirmed"):
                continue
            exposure.append({"kind": item["kind"], "count": fact(item["count"], [attrs, detector] + ([costar] if item["kind"] in listed else []),
                                                                 how=item.get("count_basis"), confidence=item.get("confidence")),
                             "where": "on the grounds" if any(((i.get("place") or {}).get("type") == "site point") for i in item.get("instances") or []) else "inside",
                             "listed_by_costar": item["kind"] in listed,
                             "places": [{"lon": i["place"].get("lon"), "lat": i["place"].get("lat"), "cell": i["place"].get("cell")}
                                        for i in item.get("instances") or [] if (i.get("place") or {}).get("lon") is not None]})
    counted = sum(e["count"]["value"] or 0 for e in exposure)
    stages["inventory"] = {"state": "ready" if inv else ("partial" if exposure else "not_run"), "number": counted, "unit": "things counted and placed",
                           "headline": f"{counted} things the weather can reach, in {len(exposure)} kinds"
                                       + ("" if inv else " (roofs only; the grounds have not been inventoried)")}

    return {
        "version": VERSION, "property_id": property_id, "assembled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": record.get("name"), "address": ", ".join(str(x) for x in (record.get("address"), record.get("city"), record.get("state")) if x),
        "record": fact({"type": record.get("type_label"), "homes": record.get("units"), "built": record.get("year_built"), "storeys": record.get("stories"),
                        "construction": record.get("construction"), "tenants_on_record": record.get("tenant_count")}, [costar]),
        "stages": [{"key": key, "problem": problem, "job": job, **stages[key]} for key, problem, job in STAGES],
        "structures": structures, "scans": scans_out, "exposure": exposure,
        "reports": reports or [],
        "sources": S.by_id,
    }


def measured_notes(model: dict, structure_ids: list[str] | None = None) -> list[str]:
    """The site model's measured facts as plain lines, each with where it came from. This is what the
    planner and the voice are given, so anything they say about a height or a position can be traced."""
    def cite(f: dict) -> str:
        bits = []
        for sid in f.get("src") or []:
            s = model["sources"].get(sid) or {}
            bits.append(" ".join(str(x) for x in (s.get("provider"), s.get("what"), f"({s['captured']})" if s.get("captured") else None) if x))
        return "; ".join(bits)

    lines = []
    for st in model["structures"]:
        if structure_ids and st["id"] not in structure_ids:
            continue
        roof, tall = st.get("roof_height_m"), (st.get("tallest_beside_it") or {})
        if roof and roof["value"] is not None and tall.get("value"):
            t = tall["value"]
            lines.append(f"{st['id']}: roof {_m(roof['value'])} m high; the tallest thing beside it ({t.get('what') or 'not identified'}) is {_m(t['height_m'])} m, {_m(t['from_wall_m'])} m from the wall and "
                         f"{_m(t['above_roof_m'])} m above the roof ({tall.get('limits')}). Source: {cite(tall)}; {tall.get('how')}.")
    for scan in model["scans"]:
        p = scan["placement"]["value"] or {}
        if structure_ids and p.get("structure") not in structure_ids:
            continue
        if p.get("status") == "aligned":
            lines.append(f"Scan {scan['name']}: under roof {p['structure']}, placed by moving it {p['moved_m']:.1f} m from Matterport's GPS "
                         f"({round(p['under_roof_before'] * 100)}% then {round(p['under_roof_after'] * 100)}% of its floor plan under the roof). "
                         f"{scan['placement'].get('limits') or ''}".strip())
        o = scan["outside_openings"]["value"]
        if o and o.get("largest"):
            big = o["largest"]
            lines.append(f"Scan {scan['name']}: {_count(o['windows'], 'window')} and {_count(o['outside_doors'], 'outside door')} measured; the largest is the "
                         f"{(big['room'] or '').lower()} {big['kind']}, {big['width_m']:.1f} m wide. Source: Matterport wall measurements.")
    for item in model["exposure"]:
        if item["where"] == "on the grounds":
            lines.append(f"On the grounds: {item['kind']}, {item['count']['value']} counted"
                         f"{', and CoStar lists it too' if item['listed_by_costar'] else ''}.")
    return lines


def board(property_ids: list[int] | None = None) -> dict:
    """Each stage across every gathered building: how many sites it has run for and its one number."""
    ids = property_ids if property_ids is not None else cached_property_ids()
    totals: dict[str, dict] = {key: {"key": key, "problem": problem, "job": job, "sites_ready": 0, "number": 0, "of": 0}
                               for key, problem, job in STAGES}
    shifts: list[float] = []
    rows: list[dict] = []
    for pid in ids:
        model = build(pid)
        rows.append({"property_id": pid, "name": model["name"], "address": model["address"], "scans": len(model["scans"]),
                     "structures": len(model["structures"]),
                     "stages": {st["key"]: {"state": st["state"], "number": st["number"], "headline": st["headline"]} for st in model["stages"]}})
        for stage in model["stages"]:
            t = totals[stage["key"]]
            t["sites_ready"] += stage["state"] != "not_run"
            t["number"] += stage["number"]
        totals["join"]["of"] += len(model["scans"])
        totals["classify"]["of"] += sum(len(s["rooms"]) for s in model["scans"])
        totals["search"]["of"] += sum(s["positions"] for s in model["scans"])
        totals["expose"]["of"] += len(model["scans"])
        shifts += [s["placement"]["value"]["moved_m"] for s in model["scans"] if (s["placement"]["value"] or {}).get("status") == "aligned"]
    shifts.sort()
    if shifts:
        totals["join"]["median_move_m"] = round(shifts[len(shifts) // 2] if len(shifts) % 2 else (shifts[len(shifts) // 2 - 1] + shifts[len(shifts) // 2]) / 2, 2)
        totals["join"]["largest_move_m"] = round(shifts[-1], 2)
    return {"sites": len(ids), "stages": [totals[key] for key, _, _ in STAGES], "rows": rows}


# --- where a fact came from ---------------------------------------------------------------------------
def expand(model: dict, src: list[str]) -> list[dict]:
    """The sources behind a fact, written out: whose data, which capture or scan, and when."""
    return [{"id": sid, **(model["sources"].get(sid) or {})} for sid in src]


def _measured(model: dict, label: str, text: str, f: dict) -> dict:
    out = {"label": label, "text": text, "src": f["src"], "sources": expand(model, f["src"])}
    for key in ("how", "limits"):
        if f.get(key):
            out[key] = f[key]
    return out


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _m(x: float) -> str:
    """Metres to one decimal, rounding halves up (15.45 reads 15.5, as a person would write it)."""
    return f"{x + 1e-9:.1f}"


_ROOF_WORK = re.compile(r"\b(roof|limb|tree|branch|gutter|chimney|vent|condenser)", re.I)
_TREES = re.compile(r"\b(tree|limb|branch|canopy)", re.I)
_ROOF_UNITS = re.compile(r"\b(condenser|rooftop unit|air.?condition|hvac|\bac\b)", re.I)
_POOL = re.compile(r"\b(pool|lounge chair|umbrella)", re.I)
_OPENINGS = re.compile(r"\b(balcon|patio|window|sliding door|shutter)", re.I)


def measured_for(model: dict, action: dict) -> list[dict]:
    """The measurements in the site model that bear on one action of a plan, each with its sources.

    The plan was written before these were measured; they are attached beside the action, never put in
    the planner's mouth. Which measurements bear on an action is decided by the roofs it names and by
    what it is about (trees, rooftop units, the pool, windows and doors).
    """
    said = " ".join(str(action.get(k) or "") for k in ("title", "why"))
    named = [st for st in model["structures"] if st["id"] == action.get("structure") or re.search(rf"\b{st['id']}\b", said)]
    out: list[dict] = []

    roofs = [st for st in named if (st.get("roof_height_m") or {}).get("value") is not None] if _ROOF_WORK.search(said) else []
    if len(roofs) == 1:
        out.append(_measured(model, f"Roof {roofs[0]['id']}", f"{_m(roofs[0]['roof_height_m']['value'])} m above the ground", roofs[0]["roof_height_m"]))
    elif roofs:
        heights = sorted(st["roof_height_m"]["value"] for st in roofs)
        out.append(_measured(model, f"{len(roofs)} roofs named", f"{_m(heights[0])} to {_m(heights[-1])} m above the ground", roofs[0]["roof_height_m"]))

    if _TREES.search(said):
        # One tall thing can stand beside several roofs. Report it once, against the roof it is nearest to.
        nearest: dict[tuple, dict] = {}
        for st in named:
            t = (st.get("tallest_beside_it") or {}).get("value")
            if t and t["above_roof_m"] >= 1:
                key = (round(t["lon"], 5), round(t["lat"], 5))
                if key not in nearest or t["from_wall_m"] < nearest[key]["tallest_beside_it"]["value"]["from_wall_m"]:
                    nearest[key] = st
        for st in nearest.values():
            t = st["tallest_beside_it"]["value"]
            out.append(_measured(model, f"Beside roof {st['id']}",
                                 f"{t.get('what') or 'something'} {_m(t['height_m'])} m tall stands {_m(t['from_wall_m'])} m from the wall, {_m(t['above_roof_m'])} m above the roof",
                                 st["tallest_beside_it"]))
    if _ROOF_UNITS.search(said):
        units = sum(int((st["roof"]["value"]["objects"] or {}).get("ac-unit", 0)) for st in named)
        if units:
            out.append(_measured(model, "Rooftop units", f"{units} counted on the roofs named", named[0]["roof"]))
    if _POOL.search(said):
        for item in model["exposure"]:
            if item["kind"] == "pool":
                out.append(_measured(model, "Pools", f"{item['count']['value']} on the grounds" + (", and CoStar lists a pool" if item["listed_by_costar"] else ""), item["count"]))
    if _OPENINGS.search(str(action.get("title") or "")):
        measured = [sc for sc in model["scans"] if sc["outside_openings"]["value"]]
        if measured:
            windows = sum(sc["outside_openings"]["value"]["windows"] for sc in measured)
            doors = sum(sc["outside_openings"]["value"]["outside_doors"] for sc in measured)
            src = sorted({sid for sc in measured for sid in sc["outside_openings"]["src"]})
            out.append(_measured(model, "Windows and outside doors", f"{windows} windows and {doors} outside doors measured in {len(measured)} scanned homes",
                                 {"src": src, "how": measured[0]["outside_openings"].get("how"),
                                  "limits": f"{len(measured)} homes are scanned out of {model['record']['value'].get('homes') or 'an unknown number'}"}))
    return out


# --- after the event: what residents report is filed into the same model ------------------------------
def ground(property_id: int) -> dict | None:
    """Which structures stand on the lowest ground of a site, from Vexcel's terrain model (bare ground).

    Water goes to low ground first, so this is the order a flood would reach the buildings in. It is the
    level of the ground under each roof and nothing more: not a flood depth and not a forecast. None when
    the site has no terrain model or fewer than two structures were measured.
    """
    heights = _read(OPEN / "reconstruct" / str(property_id) / "heights.json")
    rows = sorted(((s["ground_elevation_m"], s["id"]) for s in (heights or {}).get("structures") or [] if s.get("ground_elevation_m") is not None))
    if len(rows) < 2:
        return None
    terr = heights["source"]["terrain"]
    low, high = rows[0][0], rows[-1][0]
    return {"lowest": [{"id": sid, "elevation_m": m, "below_highest_m": round(high - m, 2)} for m, sid in rows[:3]],
            "highest": {"id": rows[-1][1], "elevation_m": high}, "spread_m": round(high - low, 2), "structures": len(rows),
            "source": f"Vexcel terrain model (bare ground), flown {terr['first_capture']} to {terr['last_capture']}"}


def _reports_path(property_id: int) -> Path:
    return CACHE_DIR / "site_models" / f"{property_id}_reports.json"


def load_reports(property_id: int) -> list[dict]:
    return _read(_reports_path(property_id)) or []


def locate(property_id: int, text: str, scan_id: str | None = None) -> dict | None:
    """Which scanned room, and which thing in it, a resident's words point at.

    The scan was made before the damage, so a stain or a leak is not in it. What is in it is the room and
    the fixture the report names ("under the balcony sliding door"), and that is what is matched: the
    report's words against each scan position's room and the things described there. Returns None when
    the site has no index or the words name nothing that was seen. `scan_id` keeps the answer inside
    the home the resident lives in.
    """
    index = _read(OPEN / "search" / f"{property_id}.json")
    if not index:
        return None
    from .openproblems import search
    said = search.tokens(re.sub(r"^Support request \([^)]*\):\s*", "", text or ""))
    best, best_score = None, 0.0
    for position in index.get("positions") or []:
        if scan_id and position["scan_id"] != scan_id:
            continue
        room_words = search.tokens(f"{position.get('room_type') or ''} {position.get('room_label') or ''}")
        thing, thing_score = None, 0.0
        for t in position.get("things") or []:
            if t.get("where") == "through a doorway":
                continue
            words = search.tokens(t.get("name"))
            hit = len(said & words) / len(words) if words else 0.0
            if hit > thing_score:
                thing, thing_score = t, hit
        score = 2.0 * len(said & room_words) + thing_score
        if score > best_score:
            best_score = score
            best = {"scan_id": position["scan_id"], "scan_name": position.get("scan_name"),
                    "room": position.get("room_label") or position.get("room_type"), "room_id": position.get("room_id"),
                    "position_id": position["sweep_id"], "thing": thing["name"] if thing and thing_score >= 0.5 else None,
                    "bearing_deg": search.bearing(position.get("heading"), thing.get("quarter")) if thing and thing_score >= 0.5 else None,
                    "matched_on": sorted(said & (room_words | (search.tokens(thing["name"]) if thing else set())))}
    return best


def place(property_id: int, rows: list[dict]) -> list[dict]:
    """Give each resident message that came without a place the room and fixture its own words name.

    A message already tied to a verified home keeps that. One placed here is marked as placed from its
    description, so nobody reads a guess as a confirmed location. One that names nothing stays unplaced.
    """
    out = []
    for row in rows:
        if not row.get("where"):
            found = locate(property_id, row.get("text") or "", row.get("scan_id"))
            if found:
                row = {**row, "where": {**found, "placed_by": "description"}, "scan_id": row.get("scan_id") or found["scan_id"]}
        out.append(row)
    return out


def add_report(property_id: int, text: str, scan_id: str | None = None, at: str | None = None) -> dict:
    """File what a resident reported against the room it describes. Kept as reported: never judged here."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("a report needs some words")
    report = {"id": uuid.uuid4().hex[:10], "at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"), "text": text[:600],
              "scan_id": scan_id, "where": locate(property_id, text, scan_id),
              "src": ["resident:report"], "status": "reported, not yet reviewed"}
    reports = load_reports(property_id) + [report]
    path = _reports_path(property_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reports, indent=1))
    return report


def clear_reports(property_id: int) -> None:
    _reports_path(property_id).unlink(missing_ok=True)


def facts(model: dict) -> list[dict]:
    """The site model as a flat list a person can read down: one line per fact, grouped by the stage that
    produced it, each with its sources written out."""
    out: list[dict] = []

    def add(stage: str, label: str, text: str, f: dict, **more: Any) -> None:
        out.append({"stage": stage, **_measured(model, label, text, f), **more})

    for scan in model["scans"]:
        p = scan["placement"]["value"] or {}
        if p.get("status") == "aligned":
            add("join", scan["name"], f"under roof {p['structure']}; moved {_m(p['moved_m'])} m from Matterport's GPS, "
                f"{round(p['under_roof_before'] * 100)}% then {round(p['under_roof_after'] * 100)}% of the floor plan under the roof", scan["placement"], scan_id=scan["id"])
        else:
            add("join", scan["name"], f"{p.get('status')}" + (f"; assumed under roof {p['structure']}" if p.get("structure") else ""), scan["placement"], scan_id=scan["id"])
        typed = [r for r in scan["rooms"] if r["type"]["value"]]
        if scan["rooms"]:
            ours = sum(1 for r in typed if r["type"].get("how") != "Matterport's own room label")
            kinds = sorted({str(r["type"]["value"]).lower() for r in typed})
            add("classify", scan["name"], f"{len(typed)} of {len(scan['rooms'])} rooms typed" + (f", {ours} by Brace" if ours else "")
                + (": " + ", ".join(kinds[:8]) if kinds else ""), {"src": scan["placement"]["src"][:1],
                   "how": "Matterport's own room labels" + ("; where it gave none, the type seen from a scan position in the room" if ours else "")}, scan_id=scan["id"])
        o = scan["outside_openings"]["value"]
        if o:
            big = o.get("largest")
            add("join", f"{scan['name']}: openings", f"{_count(o['windows'], 'window')} and {_count(o['outside_doors'], 'outside door')}"
                + (f"; the largest is the {(big['room'] or '').lower()} {big['kind']}, {_m(big['width_m'])} m wide" if big else ""), scan["outside_openings"], scan_id=scan["id"])
        if scan["defurnished_copy"]["value"]:
            add("expose", scan["name"], "a defurnished copy of this scan is on file", scan["defurnished_copy"], scan_id=scan["id"])
        if scan["positions_described"]:
            add("search", scan["name"], f"{scan['positions_described']} of {scan['positions']} scan positions described",
                {"src": scan["placement"]["src"][:1], "how": "each position's all-round view described once, then searched as text",
                 "limits": "a description can miss or misname a thing; spot checks found 3 of 5 right"}, scan_id=scan["id"])
    for item in model["exposure"]:
        add("inventory", item["kind"].capitalize(), f"{item['count']['value']} {item['where']}"
            + (", and CoStar lists it" if item["listed_by_costar"] else ""), item["count"])
    measured = [st for st in model["structures"] if (st.get("roof_height_m") or {}).get("value") is not None]
    for st in sorted(measured, key=lambda st: -((st["tallest_beside_it"]["value"] or {}).get("above_roof_m") or 0)):
        t = st["tallest_beside_it"]["value"]
        add("surface", f"Roof {st['id']}", f"{_m(st['roof_height_m']['value'])} m high"
            + (f"; {t.get('what') or 'something'} {_m(t['height_m'])} m tall stands {_m(t['from_wall_m'])} m from its wall, {_m(t['above_roof_m'])} m above it" if t and t["above_roof_m"] >= 1 else ""),
            st["tallest_beside_it"] if t else st["roof_height_m"], structure=st["id"])
    for r in model["reports"]:
        w = r.get("where")
        out.append({"stage": "search", "label": "Resident report", "text": f"\u201c{r['text']}\u201d"
                    + (f" filed against the {str(w['room']).lower()}" + (f", at the {w['thing']}" if w.get("thing") else "") + f" in {w['scan_name']}" if w else " not matched to a scanned room"),
                    "src": r["src"], "sources": [{"id": "resident:report", "provider": "Resident", "what": "report", "captured": r["at"][:10]}],
                    "limits": r["status"], "report": True})
    return out


# --- what measuring changed -----------------------------------------------------------------------------
_METRES = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m\b|metres?\b|meters?\b)", re.I)


def _model_metres(model: dict, first: list[str] | None = None) -> dict[str, str]:
    """Every height and distance in the model, as it would be written, with what it is.

    Two roofs can share a number. The roofs an action names are read first, so a number is credited to them."""
    out: dict[str, str] = {}
    for st in sorted(model["structures"], key=lambda st: st["id"] not in (first or [])):
        roof = (st.get("roof_height_m") or {}).get("value")
        if roof is not None:
            out.setdefault(_m(roof), f"roof {st['id']} height")
        t = (st.get("tallest_beside_it") or {}).get("value")
        if t:
            out.setdefault(_m(t["height_m"]), f"height of {t.get('what') or 'the tallest thing'} beside {st['id']}")
            out.setdefault(_m(t["from_wall_m"]), f"its distance from {st['id']}'s wall")
            out.setdefault(_m(t["above_roof_m"]), f"how far it stands above {st['id']}'s roof")
    return out


def cited(model: dict, action: dict) -> list[dict]:
    """The model's measurements that an action's own words quote, matched on the number as written."""
    said = " ".join(str(action.get(k) or "") for k in ("title", "why"))
    known = _model_metres(model, [st["id"] for st in model["structures"] if st["id"] == action.get("structure") or re.search(rf"\b{st['id']}\b", said)])
    found, seen = [], set()
    for number in _METRES.findall(said):
        key = f"{float(number):.1f}"
        if key in known and key not in seen:
            seen.add(key)
            found.append({"metres": key, "is": known[key]})
    return found


def what_measuring_changed(model: dict, without: dict, with_measurements: dict) -> dict:
    """Two plans for the same building and forecast step: one written before the site was measured, one after.

    Two runs of the planner differ for many reasons, so a difference is not proof of cause. What can be
    shown is narrower and is all this reports: which jobs appear in only one plan, and which jobs in the
    measured plan quote a measurement from the model.
    """
    from .clock import _alike, _brief
    was, now = list(without.get("actions") or []), list(with_measurements.get("actions") or [])
    scored = sorted(((_alike(a, b), i, j) for i, a in enumerate(was) for j, b in enumerate(now)), reverse=True)
    pair: dict[int, int] = {}
    taken: set[int] = set()
    for score, i, j in scored:
        if score < 0.6:
            break
        if i not in pair and j not in taken:
            pair[i] = j
            taken.add(j)
    rows = []
    for j, b in enumerate(now):
        i = next((i for i, jj in pair.items() if jj == j), None)
        rows.append({"change": "in both" if i is not None else "only in the measured plan", "before": _brief(was[i]) if i is not None else None,
                     "after": _brief(b), "structure": b.get("structure"), "quotes": cited(model, b)})
    for i, a in enumerate(was):
        if i not in pair:
            rows.append({"change": "only in the earlier plan", "before": _brief(a), "after": None, "structure": a.get("structure"), "quotes": []})

    def total(plan: dict) -> dict:
        t = ((plan.get("totals") or {}).get("before_arrival")) or {}
        return {"actions": len(plan.get("actions") or []), "before_arrival": t.get("count", 0), "cost_low": t.get("cost_low", 0), "cost_high": t.get("cost_high", 0)}

    return {"note": "Both plans were written by the planner for the same forecast step. Only the second could read the site's measurements. "
                    "Two runs differ for many reasons; a quoted measurement is the part that can be traced.",
            "without": total(without), "with": total(with_measurements),
            "actions_quoting_a_measurement": sum(1 for r in rows if r["quotes"]), "rows": rows}


# --- the site in three dimensions ---------------------------------------------------------------------
def scene(property_id: int) -> dict | None:
    """What a browser needs to stand the site up in 3D: the height grid, the photo to drape over it, each
    roof's outline and height, the tall things that were looked at, and where each scan position is.
    None when the site has no height model. Everything here is a measurement or a sponsor's record."""
    heights = _read(OPEN / "reconstruct" / str(property_id) / "heights.json")
    bundle = _read(building_dir(property_id) / "building.json")
    if not heights or not heights.get("available") or bundle is None:
        return None
    model = build(property_id)
    measured = {st["id"]: st for st in model["structures"]}
    structures = []
    for st in bundle.get("structures") or []:
        m = measured.get(st["id"]) or {}
        tall = (m.get("tallest_beside_it") or {}).get("value")
        structures.append({"id": st["id"], "polygon": st.get("polygon"), "roof_height_m": (m.get("roof_height_m") or {}).get("value"),
                           "tallest": tall if tall and tall.get("above_roof_m", 0) >= 1 else None})
    src = heights["source"]
    # Where each scan sat by its own GPS, and where its floor plan sits once fitted under a roof.
    fits = [{"scan_id": j["id"], "name": j.get("name"), "roof": j.get("structure"), "moved_m": j["correction"]["shift_m"],
             "under_roof_before": j["raw"]["inside"], "under_roof_after": j["fitted"]["inside"],
             "raw": j["raw"]["outline"], "fitted": j["fitted"]["outline"]}
            for j in (_read(OPEN / "geolocation" / f"{property_id}.json") or {}).get("scans") or []
            if j.get("status") == "aligned" and j["raw"].get("outline") and len(j["raw"]["outline"]) == len(j["fitted"].get("outline") or [])]
    return {
        "fits": fits,
        "property_id": property_id, "name": bundle["record"].get("name"), "homes": bundle["record"].get("units"),
        "bounds": heights["bounds"], "rows": heights["rows"], "cols": heights["cols"], "cell_m": heights["cell_m"],
        "heights_url": f"/api/buildings/{property_id}/heights.png", "texture_url": f"/api/buildings/{property_id}/aerial.jpg",
        "decode": {"unit_m": heights["encoding"]["unit_m"], "what": heights["encoding"]["what"]},
        "sources": {"heights": f"Vexcel surface model, flown {src['surface']['first_capture']} to {src['surface']['last_capture']}",
                    "photo": f"Vexcel aerial photo, {_day((bundle.get('aerial') or {}).get('captured'))}"},
        "structures": structures,
        "positions": {sw["id"]: {"lon": sw["lon"], "lat": sw["lat"], "scan_id": sc["id"], "scan_name": sc.get("name")}
                      for sc in bundle.get("scans") or [] for sw in sc.get("sweeps") or [] if sw.get("lon") is not None and sw.get("lat") is not None},
    }
