"""Open problem: understand commercial spaces.

Matterport's room labels were built for homes; on offices, shops and warehouses most rooms come back
"Void" or "Other". This module shows the vision model one wide picture per room and asks what kind of
commercial room it is, from a fixed list, with a reason, a confidence and what in it matters before a storm.

    label_rooms(model_id, client=None, limit=None) -> dict

Works from a Matterport model id alone. Rules it keeps:
  * A label is only what the model saw in the picture. "cannot tell" is a valid answer and is never replaced.
  * An answer that cannot be read is recorded as "no answer", not turned into a label.
  * Every answer is cached on disk by scan, room and scan position, so a view is never paid for twice. The cache
    is also kept per PROMPT_VERSION: an answer to an older wording of the question is kept but not reused.
  * Every request sent is counted in a ledger, and no request is sent once the ledger reaches BUDGET.

How the position is chosen: of the scan positions Matterport places in a room, the one deepest inside the
room's outline (farthest from any wall), so the picture is of the room and not of a doorway. If the outline
is missing or the positions fall outside it, the position nearest the middle of the room's positions.

Rooms that hold several positions well apart (a whole warehouse or a long hall drawn as one "room") get up
to MAX_VIEWS - 1 further looks, spread out. Those never change the room's label; they are reported beside
it, so a room that is really several kinds of space shows as "mixed".
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from shapely.geometry import Point, Polygon

from .. import matterport, vision
from ..config import CACHE_DIR, VISION_MODEL

OUT_DIR = CACHE_DIR / "open" / "commercial"
BUDGET = 150          # hard ceiling on paid vision requests, across every run that shares this cache folder
MAX_VIEWS = 8         # looks per room, counting the first
MIN_SPACING_M = 4.0   # a further look must be at least this far from every look already chosen

CANNOT_TELL = "cannot tell"
NOT_LISTED = "not on this list"
VACANT = "vacant unit or shell"  # a true answer about the room, but it names no use; counted apart from rooms whose use we named
ROOM_TYPES = [
    "lobby or reception", "open office", "private office", "meeting room", "classroom or lecture hall",
    "corridor", "stairwell", "lift lobby", "kitchen or break room", "restroom", "lounge or common area",
    "storage", "copy or mail room", "server or IT room", "mechanical or electrical room", "laboratory or workshop",
    "warehouse floor", "loading dock", "retail floor or showroom", "gym", "atrium", VACANT, "outdoors",
    NOT_LISTED, CANNOT_TELL,
]
REAL_TYPES = [t for t in ROOM_TYPES if t not in (NOT_LISTED, CANNOT_TELL)]
CONFIDENCES = ["high", "medium", "low"]
# The model answers seen / not seen for each of these, so nothing is volunteered: field name -> what we call it.
STORM_FIELDS = {"large_outside_glass": "large glass", "equipment_or_stock_on_floor": "equipment or stock on the floor",
                "electronics_at_floor_level": "electronics at floor level", "outside_door": "outside door",
                "dock_or_rollup_door": "dock or roll-up door"}
STORM_KINDS = list(STORM_FIELDS.values())
# How much each thing seen counts when ranking rooms for a storm plan; a room's score is the sum over the kinds seen in it.
STORM_WEIGHT = {"large glass": 2, "equipment or stock on the floor": 2, "electronics at floor level": 3, "outside door": 2, "dock or roll-up door": 3}
# What Matterport returns when it has no real type for a room.
MATTERPORT_EMPTY = {"", "void", "other", "unlabelled", "unlabeled", "unknown"}
MAX_REASON_WORDS = 14
PROMPT_VERSION = 2  # v1 let the model list a storm item and then say it was not there; v2 asks seen / not seen for each

PROMPT = (
    "This wide picture is the four horizontal views from one camera position inside a commercial building (an office, "
    "shop, warehouse or campus building), left to right in clockwise order; the three seams are where views meet. "
    "Say what kind of room the camera is standing in, judging only by what is visible: furniture, fixtures, signs, "
    "equipment, the shape of the space.\n"
    "room_type: choose from the list. Some that are easily confused: 'atrium' is a tall open space several floors high; "
    "'lobby or reception' is an entrance hall or a space with a reception desk; 'classroom or lecture hall' has rows of "
    "seats or tables facing a screen, board or lectern; 'meeting room' has a table people sit around; 'corridor' is a "
    "passage whose job is to lead to other rooms. If the room is empty of furniture but its purpose is still plain from "
    "its size, doors and fixtures, name that purpose; use 'vacant unit or shell' for an empty unit with nothing that shows "
    "what it is used for. Use 'not on this list' when the room is clearly something the list lacks, and name it in the "
    "reason. Use 'cannot tell' when the view does not show enough to decide (too dark, blocked, a bare wall, or it could "
    "equally be several types); do not guess.\n"
    "confidence: how sure the picture makes you.\n"
    "reason: at most 12 words naming what you saw.\n"
    "storm: five things that matter before a severe storm. For each, seen is true only if you can point to it in this "
    "picture; if it is absent or you are unsure, seen is false. 'what' is a few words on what it is and where when seen, "
    "and an empty string when not seen.\n"
    "- large_outside_glass: windows, glass walls, glass doors or skylights facing the outdoors that take up much of a wall "
    "or roof. Glass between two indoor spaces does not count.\n"
    "- equipment_or_stock_on_floor: machines, appliances, goods, boxes or stored materials standing on the floor. Ordinary "
    "tables, chairs and bins do not count.\n"
    "- electronics_at_floor_level: computers, servers, printers, screens, network or audio-visual gear standing on the floor "
    "or within a hand's height of it. Wall sockets alone, and devices up on desks or walls, do not count.\n"
    "- outside_door: a door you can see leads outdoors (daylight or outdoor ground through or beside it). An exit sign "
    "alone does not count.\n"
    "- dock_or_rollup_door: a loading dock door or a roll-up or overhead door."
)
_SEEN = {"type": "object",
         "properties": {"seen": {"type": "boolean"}, "what": {"type": "string", "description": "A few words on what and where; empty if not seen."}},
         "required": ["seen", "what"], "additionalProperties": False}
SCHEMA = {
    "type": "object",
    "properties": {
        "room_type": {"type": "string", "enum": ROOM_TYPES},
        "confidence": {"type": "string", "enum": CONFIDENCES},
        "reason": {"type": "string", "description": "At most 12 words: what in the picture shows the room type, or why it cannot be told."},
        "storm": {"type": "object", "properties": {k: _SEEN for k in STORM_FIELDS}, "required": list(STORM_FIELDS), "additionalProperties": False},
    },
    "required": ["room_type", "confidence", "reason", "storm"],
    "additionalProperties": False,
}

_lock = threading.Lock()


class BudgetSpent(RuntimeError):
    pass


# ---- the ledger of paid requests -------------------------------------------------------------------------------

def _ledger_path() -> Path:
    return OUT_DIR / "calls.json"


def calls_made() -> dict:
    """Paid vision requests sent so far from this cache folder: {"total": n, "by_model": {scan id: n}}."""
    p = _ledger_path()
    return json.loads(p.read_text()) if p.exists() else {"total": 0, "by_model": {}}


def _reserve(model_id: str) -> bool:
    """Count one request before it is sent. False, and nothing counted, once the budget is spent."""
    with _lock:
        led = calls_made()
        if led["total"] >= BUDGET:
            return False
        led["total"] += 1
        led["by_model"][model_id] = led["by_model"].get(model_id, 0) + 1
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        _ledger_path().write_text(json.dumps(led))
        return True


# ---- the per-view cache ----------------------------------------------------------------------------------------

def _answer_path(model_id: str, room_id: str, sweep_id: str) -> Path:
    return OUT_DIR / "answers" / f"v{PROMPT_VERSION}" / model_id / f"{room_id}__{sweep_id}.json"


def image_path(model_id: str, room_id: str, sweep_id: str) -> Path:
    """Where the picture shown to the model for this view is kept (outside git, under data/)."""
    return OUT_DIR / "images" / model_id / f"{room_id}__{sweep_id}.jpg"


def _picture(model_id: str, room_id: str, sweep_id: str) -> Path:
    p = image_path(model_id, room_id, sweep_id)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        vision.strip(model_id, sweep_id).save(p, "JPEG", quality=88)
    return p


def parse_answer(text: str) -> dict | None:
    """The model's reply as a checked label, or None if it is not one. Nothing is filled in."""
    try:
        a = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(a, dict) or a.get("room_type") not in ROOM_TYPES or a.get("confidence") not in CONFIDENCES:
        return None
    reason = a.get("reason")
    storm = a.get("storm")
    if not isinstance(reason, str) or not reason.strip() or not isinstance(storm, dict) or set(storm) != set(STORM_FIELDS):
        return None
    seen = []
    for field, kind in STORM_FIELDS.items():
        it = storm[field]
        if not isinstance(it, dict) or not isinstance(it.get("seen"), bool) or not isinstance(it.get("what"), str):
            return None
        if it["seen"]:
            if not it["what"].strip():
                return None  # "seen" with nothing named is not evidence
            seen.append({"kind": kind, "seen": it["what"].strip()})
    words = reason.split()
    out = {"type": a["room_type"], "confidence": a["confidence"], "reason": " ".join(words[:MAX_REASON_WORDS]), "storm_items": seen}
    if len(words) > MAX_REASON_WORDS:
        out["reason_cut"] = True  # the model ran over the word limit; the tail was dropped, nothing was reworded
    return out


def _ask(client, model_id: str, room_id: str, sweep_id: str) -> dict:
    """One paid look at one view. Returns the record that is cached; raises BudgetSpent before sending if out of budget."""
    picture = _picture(model_id, room_id, sweep_id)
    if not _reserve(model_id):
        raise BudgetSpent()
    rec = {"model_id": model_id, "room_id": room_id, "sweep_id": sweep_id, "vision_model": VISION_MODEL, "prompt_version": PROMPT_VERSION,
           "asked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "status": "no answer", "answer": None}
    resp = client.messages.create(
        model=VISION_MODEL, max_tokens=1024,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [vision.image_block(picture, max_side=2048), {"type": "text", "text": PROMPT}]}],
    )
    if resp.stop_reason == "refusal":
        rec["why"] = "the model declined"
        return rec
    text = next((b.text for b in resp.content if b.type == "text"), "")
    answer = parse_answer(text)
    if answer is None:
        rec["why"] = "the reply could not be read as a label"
        rec["raw"] = text[:400]
        return rec
    rec["status"], rec["answer"] = "ok", answer
    return rec


# ---- choosing where to look ------------------------------------------------------------------------------------

def _dist(a: dict, b: dict) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def choose_views(room: dict, sweeps: list[dict], max_views: int = MAX_VIEWS) -> tuple[list[dict], str]:
    """The scan positions to look from, best first, and how the first was chosen."""
    if not sweeps:
        return [], "no scan position inside this room"
    best, how = None, ""
    poly = Polygon(room["polygon"]) if room.get("polygon") and len(room["polygon"]) >= 4 else None
    if poly is not None and poly.is_valid:
        mid = poly.centroid  # ties (a long room, several positions equally far from the walls) go to the one nearest the middle
        inside = [(round(poly.exterior.distance(Point(s["x"], s["y"])), 1), -mid.distance(Point(s["x"], s["y"])), s["id"], s)
                  for s in sweeps if poly.contains(Point(s["x"], s["y"]))]
        if inside:
            d, _, _, best = max(inside, key=lambda t: t[:3])
            how = f"deepest inside the room outline: {d:.1f} m from the nearest wall, of {len(sweeps)} position{'s' if len(sweeps) != 1 else ''}"
    if best is None:
        cx, cy = sum(s["x"] for s in sweeps) / len(sweeps), sum(s["y"] for s in sweeps) / len(sweeps)
        best = min(sweeps, key=lambda s: (math.hypot(s["x"] - cx, s["y"] - cy), s["id"]))
        how = f"nearest the middle of the room's {len(sweeps)} position{'s' if len(sweeps) != 1 else ''} (no usable outline around them)"
    picked = [best]
    rest = [s for s in sweeps if s["id"] != best["id"]]
    while rest and len(picked) < max_views:  # spread further looks out: always the position farthest from those chosen
        gap, _, nxt = max(((min(_dist(s, p) for p in picked), s["id"], s) for s in rest), key=lambda t: (t[0], t[1]))
        if gap < MIN_SPACING_M:
            break
        picked.append(nxt)
        rest = [s for s in rest if s["id"] != nxt["id"]]
    return picked, how


def matterport_label(room: dict) -> dict:
    """Matterport's own answer for a room: its classification, any name typed in, and whether either is a real type."""
    t, name = (room.get("type") or "").strip(), (room.get("label") or "").strip()
    return {"type": t or "Unlabelled", "label": name, "real_type": t.lower() not in MATTERPORT_EMPTY, "named": bool(name)}


# ---- the main function -----------------------------------------------------------------------------------------

def label_rooms(model_id: str, client=None, limit: int | None = None, *, max_views: int = MAX_VIEWS, retry_failed: bool = False) -> dict:
    """Label every room of one Matterport scan that has a scan position inside it.

    client: an Anthropic client (one is made only if a paid look is actually needed).
    limit: the most paid looks this run may make; None means only the overall BUDGET applies. Cached looks are free.
    max_views: looks per room, counting the first; 1 gives exactly one look per room.
    retry_failed: pay again for views whose earlier reply could not be read (off by default: nothing is paid for twice).
    Writes and returns data/cache/open/commercial/<model_id>.json.
    """
    model = matterport.fetch_model(model_id)
    floors = {f["id"]: f.get("label") for f in model.get("floors", [])}
    by_room: dict[str, list[dict]] = {}
    for s in model["sweeps"]:
        if s.get("room_id") and s.get("has_pano", True):
            by_room.setdefault(s["room_id"], []).append(s)

    rooms, jobs = [], []  # jobs: (order, room index, sweep id); every room's first look comes before any second look
    for r in model["rooms"]:
        views, how = choose_views(r, by_room.get(r["id"], []), max_views)
        rooms.append({"room_id": r["id"], "floor": floors.get(r.get("floor_id")), "area_sqft": r.get("area_sqft"),
                      "matterport": matterport_label(r), "positions": len(by_room.get(r["id"], [])),
                      "sweep_id": views[0]["id"] if views else None, "chosen_by": how, "_views": [v["id"] for v in views]})
        jobs += [(k, len(rooms) - 1, v["id"]) for k, v in enumerate(views)]
    jobs.sort(key=lambda j: (j[0], j[1]))

    records: dict[tuple[int, str], dict] = {}
    todo = []
    for _, i, sid in jobs:
        p = _answer_path(model_id, rooms[i]["room_id"], sid)
        rec = json.loads(p.read_text()) if p.exists() else None
        if rec and (rec["status"] == "ok" or not retry_failed):
            records[(i, sid)] = {**rec, "cached": True}
        else:
            todo.append((i, sid))
    room_left = BUDGET - calls_made()["total"]
    wanted = len(todo) if limit is None else max(0, min(limit, len(todo)))
    allowed = max(0, min(room_left, wanted))
    run, held = todo[:allowed], todo[allowed:]
    for i, sid in held:
        records[(i, sid)] = {"status": "not looked at", "answer": None,
                             "why": "the overall call budget is spent" if room_left < wanted else "this run's call limit was reached"}

    made = 0
    if run:
        client = client or anthropic.Anthropic()
        try:
            matterport.download_faces(model_id, sorted({sid for _, sid in run}), list(matterport.SIDE_FACES))
        except matterport.MatterportError:
            pass  # each view reports its own missing picture below

        def one(job: tuple[int, str]) -> dict:
            i, sid = job
            try:
                rec = _ask(client, model_id, rooms[i]["room_id"], sid)
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                raise
            except BudgetSpent:
                return {"status": "not looked at", "answer": None, "why": "the overall call budget is spent"}
            except (matterport.MatterportError, OSError):
                return {"status": "not looked at", "answer": None, "why": "the picture could not be downloaded"}
            except anthropic.APIError as e:
                return {"status": "no answer", "answer": None, "why": f"the request failed ({type(e).__name__})", "paid": True}
            p = _answer_path(model_id, rooms[i]["room_id"], sid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rec))  # read or not, the reply is kept, so the same view is not paid for again
            return {**rec, "paid": True}

        with ThreadPoolExecutor(max_workers=6) as pool:
            for job, rec in zip(run, pool.map(one, run)):
                records[job] = rec
                made += 1 if rec.get("paid") else 0

    for i, room in enumerate(rooms):
        ids = room.pop("_views")
        looks = []
        for sid in ids:
            rec = records[(i, sid)]
            a = rec.get("answer")
            looks.append({"sweep_id": sid, "image": str(image_path(model_id, room["room_id"], sid)) if rec["status"] in ("ok", "no answer") else None,
                          "status": rec["status"], **({"why": rec["why"]} if rec.get("why") else {}), **(a or {})})
        first = looks[0] if looks else None
        room["image"] = first["image"] if first else None
        if first is None:
            room["status"], room["ours"] = "no scan position", None
        elif first["status"] != "ok":
            room["status"], room["ours"], room["why"] = first["status"], None, first.get("why")
        else:
            room["ours"] = {k: first[k] for k in ("type", "confidence", "reason", "storm_items", "reason_cut") if k in first}
            room["status"] = "labelled" if first["type"] in REAL_TYPES else first["type"]
        room["other_views"] = looks[1:]
        seen = Counter(v["type"] for v in looks if v["status"] == "ok" and v["type"] in REAL_TYPES)
        room["types_seen"] = dict(seen.most_common())
        room["mixed"] = len(seen) > 1
        storm: dict[str, dict] = {}
        for v in looks:
            for it in v.get("storm_items") or []:
                storm.setdefault(it["kind"], {"kind": it["kind"], "seen": it["seen"], "sweep_id": v["sweep_id"], "views": 0})["views"] += 1
        room["storm"] = sorted(storm.values(), key=lambda s: -STORM_WEIGHT[s["kind"]])
        room["storm_score"] = sum(STORM_WEIGHT[k] for k in storm)

    out = {
        "model_id": model_id, "name": model.get("name"), "vision_model": VISION_MODEL, "prompt_version": PROMPT_VERSION,
        "method": "One wide picture (four side views) per look. First look: the scan position deepest inside the room outline. "
                  f"Up to {max_views - 1} further looks at least {MIN_SPACING_M:g} m apart in rooms that hold more positions; they never change the room's label.",
        "room_types": ROOM_TYPES, "rooms": rooms, "summary": summarise(rooms),
        "calls": {"made_this_run": made, "answers_from_cache": sum(1 for r in records.values() if r.get("cached")),
                  "made_ever_all_scans": calls_made()["total"], "budget": BUDGET},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{model_id}.json").write_text(json.dumps(out, indent=1))
    return out


def summarise(rooms: list[dict]) -> dict:
    """Counts for one scan, or for several scans' rooms put together."""
    seen = [r for r in rooms if r["positions"]]
    ours = [r for r in seen if r["status"] == "labelled"]
    looks = [v for r in seen for v in ([{"status": "ok", **r["ours"]}] if r["ours"] else []) + r["other_views"]]
    ok = [v for v in looks if v["status"] == "ok"]
    storm = sorted((r for r in seen if r["storm"]), key=lambda r: (-r["storm_score"], -(r.get("area_sqft") or 0)))
    return {
        "rooms": len(rooms),
        "rooms_with_a_scan_position": len(seen),
        "rooms_without_a_scan_position": len(rooms) - len(seen),
        "matterport_real_type": sum(1 for r in seen if r["matterport"]["real_type"]),
        "matterport_real_type_or_name": sum(1 for r in seen if r["matterport"]["real_type"] or r["matterport"]["named"]),
        "matterport_real_type_all_rooms": sum(1 for r in rooms if r["matterport"]["real_type"]),
        "matterport_labels": dict(Counter(r["matterport"]["type"] for r in seen).most_common()),
        "ours_real_type": len(ours),
        "ours_use_named": sum(1 for r in ours if r["ours"]["type"] != VACANT),
        "ours_vacant": sum(1 for r in ours if r["ours"]["type"] == VACANT),
        "ours_cannot_tell": sum(1 for r in seen if r["status"] == CANNOT_TELL),
        "ours_not_on_list": sum(1 for r in seen if r["status"] == NOT_LISTED),
        "ours_no_answer": sum(1 for r in seen if r["status"] == "no answer"),
        "ours_not_looked_at": sum(1 for r in seen if r["status"] == "not looked at"),
        "type_counts": dict(Counter(r["ours"]["type"] for r in ours).most_common()),
        "confidence_counts": dict(Counter(r["ours"]["confidence"] for r in ours).most_common()),
        "mixed_rooms": sum(1 for r in seen if r["mixed"]),
        "looks": len(ok),
        "looks_cannot_tell": sum(1 for v in ok if v["type"] == CANNOT_TELL),
        "look_type_counts": dict(Counter(v["type"] for v in ok if v["type"] in REAL_TYPES).most_common()),
        "storm_rooms": [{"model_id": r.get("model_id"), "room_id": r["room_id"], "floor": r["floor"], "type": r["ours"]["type"] if r["ours"] else None,
                         "types_seen": r["types_seen"], "area_sqft": r.get("area_sqft"), "score": r["storm_score"],
                         "seen": [f"{s['kind']}: {s['seen']}" for s in r["storm"]]} for r in storm],
        "unlabelled": [{"room_id": r["room_id"], "status": r["status"], "why": r.get("why") or (r["ours"] or {}).get("reason")}
                       for r in seen if r["status"] != "labelled"],
    }


def label_building(property_id: int, client=None, limit: int | None = None, **kw) -> dict:
    """Every scan attached to one cached building, sharing `limit` between them. Writes building_<id>.json."""
    from ..building import Site

    site = Site.load(property_id)
    left, scans, rooms = limit, [], []
    for scan_id, scan in site.scans.items():
        res = label_rooms(scan_id, client=client, limit=left, **kw)
        if left is not None:
            left = max(0, left - res["calls"]["made_this_run"])
        scans.append({"model_id": scan_id, "name": scan.get("name"), "kind": scan.get("kind"), "level": scan.get("level"), "summary": res["summary"]})
        rooms += [{**r, "model_id": scan_id} for r in res["rooms"]]
    out = {"property_id": property_id, "name": site.d["record"].get("name"), "address": site.d["record"].get("address"),
           "scans": scans, "summary": summarise(rooms), "calls": {"made_ever_all_scans": calls_made()["total"], "budget": BUDGET}}
    (OUT_DIR / f"building_{property_id}.json").write_text(json.dumps(out, indent=1))
    return out
