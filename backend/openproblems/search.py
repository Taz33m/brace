"""Open problem: search inside panoramas. "Where is the water heater", "show me every sliding glass door".

Each scan position gets one short description from the vision model: the room, the light, and a list of things
seen with the quarter of the view each is in. The quarter plus the position's heading gives the direction to
turn the viewer. Search is plain text matching over those descriptions (plurals and simple synonyms folded
together); a result is only returned when the description supports every part of the query.

Descriptions are cached one file per scan position under data/cache/open/search/<property>/<scan>/, and every
paid call is counted in data/cache/open/search/calls.json against hard limits, so nothing is paid for twice.
"""
from __future__ import annotations

import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image

from .. import matterport, vision
from ..building import Site
from ..config import CACHE_DIR, VISION_MODEL

OPEN_DIR = CACHE_DIR / "open" / "search"
MAX_INDEX_CALLS = 250   # paid vision calls allowed for indexing, in total, across runs
MAX_SEARCH_CALLS = 20   # paid calls allowed for re-ranking searches, in total, across runs
RERANK_POOL = 12
_lock = threading.Lock()

ROOMS = ["kitchen", "living room", "dining area", "bedroom", "bathroom", "closet", "hallway", "entry", "laundry",
         "balcony or patio", "office", "lobby", "utility", "other"]
PROMPT = (
    "This wide image is four photos side by side, taken from one camera position inside an apartment building or its "
    "leasing office. Each photo is one quarter of the image: left to right they are quarters 1, 2, 3 and 4, each turned "
    "90 degrees clockwise from the one before, so together they cover the full circle. People will search this "
    "building by what is in it and be turned to face what they asked for. Report only what is visible in the image; "
    "do not guess at what is behind closed doors or out of view. Give the kind of room the camera is standing in; the "
    "other kinds of space visible from here; the light ('direct sun' only when patches of sunlight are visibly "
    "falling on the floor, walls or furniture; 'daylight' when the space is lit through glass with no sun patches); a "
    "plain description in one or two sentences; and a list of up to twenty things seen, each with the quarter it is in "
    "(if it spans two, the quarter holding most of it). List every window, sliding glass door, glass wall and "
    "exterior door; every appliance and fixture (refrigerator, range, dishwasher, microwave, washer, dryer, water "
    "heater, kitchen island, fireplace, bathtub, shower, toilet, sink, ceiling fan, electrical panel, thermostat); "
    "furniture and anything else standing on the floor; and anything loose on a balcony or patio (chairs, tables, "
    "plants, grills, bicycles). Name each thing with its plain common name in the singular, such as 'sliding glass "
    "door', 'window', 'water heater', 'kitchen island'. Say whether each thing is in the room the camera is in, seen "
    "through a doorway in another room, or outside."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "room_type": {"type": "string", "enum": ROOMS},
        "spaces_visible": {"type": "array", "items": {"type": "string", "enum": ROOMS}},
        "light": {"type": "string", "enum": ["direct sun", "daylight", "artificial light", "dim"]},
        "description": {"type": "string"},
        "things": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string", "enum": ["glazing", "door", "appliance", "fixture", "on the floor",
                                                         "on a balcony or patio", "other"]},
                "quarter": {"type": "integer", "enum": [1, 2, 3, 4]},
                "where": {"type": "string", "enum": ["in this room", "through a doorway", "outside"]},
                "detail": {"type": "string", "description": "At most eight words: colour, size, state, what it is next to."},
            },
            "required": ["name", "category", "quarter", "where", "detail"],
            "additionalProperties": False,
        }},
    },
    "required": ["room_type", "spaces_visible", "light", "description", "things"],
    "additionalProperties": False,
}
RERANK_SCHEMA = {
    "type": "object",
    "properties": {"order": {"type": "array", "items": {"type": "integer"},
                             "description": "Candidate numbers that truly show what was asked for, best first."}},
    "required": ["order"],
    "additionalProperties": False,
}


ISLAND_PROMPT = (
    "This wide image is four photos side by side from one camera position in an apartment, each turned 90 degrees "
    "clockwise from the one before. Look at the kitchen counter that stands out into the room. Is it a freestanding "
    "island, with open floor on every side so a person could walk all the way round it, or a peninsula, joined at one "
    "end to a wall or to the run of cabinets? Report only what is visible."
)
ISLAND_SCHEMA = {
    "type": "object",
    "properties": {"counter": {"type": "string", "enum": ["freestanding island", "peninsula", "neither visible"]}},
    "required": ["counter"],
    "additionalProperties": False,
}


class SearchError(RuntimeError):
    pass


class BudgetSpent(SearchError):
    pass


# --- call counting and the per-position cache ------------------------------------------------------------------
def calls_used() -> dict:
    path = OPEN_DIR / "calls.json"
    return {"index": 0, "search": 0, **(json.loads(path.read_text()) if path.exists() else {})}


def _spend(kind: str, cap: int) -> None:
    """Count one paid call before it is made; refuse once the cap for that kind is reached."""
    with _lock:
        used = calls_used()
        if used[kind] >= cap:
            raise BudgetSpent(f"{kind} call limit of {cap} reached")
        used[kind] += 1
        OPEN_DIR.mkdir(parents=True, exist_ok=True)
        (OPEN_DIR / "calls.json").write_text(json.dumps(used))


def _position_path(property_id: int, scan_id: str, sweep_id: str) -> Path:
    return OPEN_DIR / str(property_id) / scan_id / f"{sweep_id}.json"


def _json_reply(resp) -> dict:
    if resp.stop_reason == "refusal":
        raise ValueError("declined")
    if resp.stop_reason == "max_tokens":
        raise ValueError("reply cut off")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def _own_face(scan_id: str, sweep_id: str, face: int) -> Path:
    return OPEN_DIR / "faces" / scan_id / f"{sweep_id}_{face}.jpg"


def fetch_fallback_faces(scan_id: str, sweep_ids: list[str]) -> int:
    """Side views for scans that have no "2k" imagery (older captures only publish "high", 1024 px a face).

    backend.matterport asks for "2k" only, so these are kept here, in this module's own cache folder. The face
    order is the same as the 2k set (checked on a scan that has both).
    """
    todo = [s for s in sweep_ids if any(not _own_face(scan_id, s, f).exists() for f in matterport.SIDE_FACES)]
    done = 0
    for i in range(0, len(todo), 40):
        ids = ",".join(f'"{s}"' for s in todo[i:i + 40])
        data = matterport.gql('{ model(id:"%s"){ panoLocations(ids:[%s]){ id skybox(resolution:"high"){ status children } } } }'
                              % (scan_id, ids))
        with httpx.Client(timeout=90) as http:
            for p in data["model"]["panoLocations"]:
                children = (p.get("skybox") or {}).get("children") or []
                for f in matterport.SIDE_FACES:
                    path = _own_face(scan_id, p["id"], f)
                    if path.exists() or f >= len(children):
                        continue
                    r = http.get(children[f])
                    if r.status_code == 200:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(r.content)
                        done += 1
    return done


def wide_image(scan_id: str, sweep_id: str, side: int = 512) -> Image.Image:
    """The four side views left to right: backend.vision.strip when its imagery exists, else the fallback faces."""
    if all(matterport._face_path(scan_id, sweep_id, f).exists() for f in matterport.SIDE_FACES):
        return vision.strip(scan_id, sweep_id, side)
    if not all(_own_face(scan_id, sweep_id, f).exists() for f in matterport.SIDE_FACES):
        raise matterport.MatterportError(f"no side views cached for position {sweep_id}")
    sheet = Image.new("RGB", (4 * side, side))
    for i, face in enumerate(matterport.SIDE_FACES):
        with Image.open(_own_face(scan_id, sweep_id, face)) as im:
            sheet.paste(im.convert("RGB").resize((side, side), Image.LANCZOS), (i * side, 0))
    return sheet


def describe(client, property_id: int, scan_id: str, sweep_id: str) -> dict:
    """One paid look at one scan position, or the cached answer. Same call shape as backend.vision."""
    path = _position_path(property_id, scan_id, sweep_id)
    if path.exists():
        return json.loads(path.read_text())
    image = vision.image_block(wide_image(scan_id, sweep_id), max_side=2048)  # before spending: a missing image costs nothing
    _spend("index", MAX_INDEX_CALLS)
    resp = client.messages.create(
        model=VISION_MODEL, max_tokens=4096,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [image, {"type": "text", "text": PROMPT}]}],
    )
    out = _json_reply(resp)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


_ISLAND = re.compile(r"\bisland\b", re.I)


def _island_path(property_id: int, scan_id: str) -> Path:
    return OPEN_DIR / str(property_id) / scan_id / "_island.json"


def check_islands(property_id: int, positions: list[dict], client) -> None:
    """One paid look per scan to settle whether its "kitchen island" is an island or a peninsula. Cached per scan.

    The first pass named every counter that juts into the room an island; in these apartments most are peninsulas.
    """
    picked: dict[str, dict] = {}
    for pos in positions:
        if pos["source"] != "vision" or not any("island" in tokens(th["name"]) for th in pos["things"]):
            continue
        best = picked.get(pos["scan_id"])
        if best is None or (pos["room_type"] == "kitchen" and best["room_type"] != "kitchen"):
            picked[pos["scan_id"]] = pos
    for scan_id, pos in picked.items():
        path = _island_path(property_id, scan_id)
        if path.exists():
            continue
        try:
            image = vision.image_block(wide_image(scan_id, pos["sweep_id"]), max_side=2048)
            _spend("index", MAX_INDEX_CALLS)
            resp = client.messages.create(
                model=VISION_MODEL, max_tokens=1024,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": ISLAND_SCHEMA}},
                messages=[{"role": "user", "content": [image, {"type": "text", "text": ISLAND_PROMPT}]}],
            )
            path.write_text(json.dumps({"sweep_id": pos["sweep_id"], **_json_reply(resp)}))
        except Exception:
            continue  # unchecked scans keep the first-pass wording, minus what its own detail contradicts


def _settle_islands(property_id: int, positions: list[dict]) -> None:
    """Rename "island" to "peninsula" where the per-scan check, or the thing's own detail, says that is what it is."""
    verdicts: dict[str, str | None] = {}
    for pos in positions:
        scan_id = pos["scan_id"]
        if scan_id not in verdicts:
            path = _island_path(property_id, scan_id)
            verdicts[scan_id] = json.loads(path.read_text())["counter"] if path.exists() else None
        says = verdicts[scan_id]
        pos["island_check"] = says
        if says == "peninsula":  # the scan's own wording follows the check; the per-position cache keeps the original
            pos["description"] = _ISLAND.sub("peninsula", pos.get("description") or "")
        for th in pos["things"]:
            if says == "peninsula":
                th["detail"] = _ISLAND.sub("peninsula", th.get("detail") or "")
            if "island" not in tokens(th["name"]):
                continue
            if says == "peninsula" or (says is None and "peninsula" in tokens(th.get("detail"))):
                th["was"], th["name"] = th["name"], "kitchen peninsula"


# --- directions ------------------------------------------------------------------------------------------------
COMPASS = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")


def bearing(heading: float | None, quarter: int | None) -> float | None:
    """True bearing of the middle of a quarter: quarter 1 looks along the heading, each next one 90 degrees clockwise."""
    if heading is None or quarter is None:
        return None
    return round((heading + 90 * (quarter - 1)) % 360, 1)


def compass(deg: float | None) -> str | None:
    return None if deg is None else COMPASS[int(((deg % 360) + 22.5) // 45) % 8]


def viewer_yaw(face1_yaw: float | None, quarter: int | None) -> float | None:
    """Rotation to give the Matterport viewer to face a quarter. Needs no compass fix, so it works for every scan."""
    if face1_yaw is None or quarter is None:
        return None
    return round((face1_yaw - 90 * quarter + 180) % 360 - 180, 1)


def _face1_yaws(scan_id: str) -> dict[str, float]:
    """Yaw of each position's first side view in the scan's own frame, from the cached scan record only."""
    path = matterport.MP_CACHE / scan_id / "model.json"
    if not path.exists():
        return {}
    out = {}
    for s in json.loads(path.read_text()).get("sweeps", []):
        q = s.get("rotation")
        if q:
            out[s["id"]] = round(math.degrees(math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]),
                                                         1 - 2 * (q["y"] ** 2 + q["z"] ** 2))), 2)
    return out


# --- building the index ----------------------------------------------------------------------------------------
def _from_survey(rec: dict) -> dict:
    """What the first-pass survey already recorded, in index form. It has no quarters, so no direction."""
    things = [{"name": n, "category": "on the floor", "quarter": None, "where": "in this room", "detail": ""}
              for n in rec.get("floor_level_items") or []]
    glass = rec.get("glass")
    if glass in ("some windows", "large windows"):
        things.append({"name": "window", "category": "glazing", "quarter": None, "where": "in this room", "detail": glass})
    elif glass == "mostly glass":
        things.append({"name": "glass wall", "category": "glazing", "quarter": None, "where": "in this room", "detail": glass})
    doors = rec.get("exterior_doors")
    if doors and doors != "none seen":
        things.append({"name": doors.rstrip("s"), "category": "door", "quarter": None, "where": "in this room",
                       "detail": "exterior"})
    return {"room_type": None, "spaces_visible": [], "light": None, "description": rec.get("note") or "", "things": things}


def _order(site: Site) -> list[tuple[str, dict]]:
    """Every position, ordered so any prefix covers every scan and, within a scan, every room before repeats."""
    per_scan = []
    for scan_id, scan in site.scans.items():
        rooms: dict = {}
        for s in scan["sweeps"]:
            rooms.setdefault(s.get("room_id") or s["id"], []).append(s)
        queue = []
        for depth in range(max((len(v) for v in rooms.values()), default=0)):
            queue += [(scan_id, v[depth]) for v in rooms.values() if depth < len(v)]
        per_scan.append(queue)
    out = []
    for depth in range(max((len(q) for q in per_scan), default=0)):
        out += [q[depth] for q in per_scan if depth < len(q)]
    return out


def build_index(property_id: int, client=None, limit: int | None = None) -> dict:
    """Describe scan positions and write the index. `limit` caps new paid calls in this run; cached ones are free.

    With no client nothing is paid for: the index is assembled from cached descriptions and the saved surveys.
    """
    site = Site.load(property_id)
    order = _order(site)
    todo = [(scan_id, s["id"]) for scan_id, s in order if not _position_path(property_id, scan_id, s["id"]).exists()]
    if client is None:
        todo = []
    room_left = MAX_INDEX_CALLS - calls_used()["index"]
    todo = todo[:max(0, min(room_left, len(todo) if limit is None else limit))]
    failed: list[str] = []
    before = calls_used()["index"]
    if todo:
        by_scan: dict[str, list[str]] = {}
        for scan_id, sweep_id in todo:
            by_scan.setdefault(scan_id, []).append(sweep_id)
        for scan_id, ids in by_scan.items():
            try:
                matterport.download_faces(scan_id, ids, list(matterport.SIDE_FACES))
                missing = [s for s in ids if not all(matterport._face_path(scan_id, s, f).exists() for f in matterport.SIDE_FACES)]
                if missing:
                    fetch_fallback_faces(scan_id, missing)
            except (matterport.MatterportError, httpx.HTTPError):
                pass  # positions without images fail below, before any call is spent

        def safe(item: tuple[str, str]) -> None:
            try:
                describe(client, property_id, *item)
            except BudgetSpent:
                failed.append(f"{item[0]}/{item[1]}: call limit reached")
            except Exception as e:  # one bad position must not stop the rest; auth problems show up on every item
                failed.append(f"{item[0]}/{item[1]}: {type(e).__name__} {str(e)[:60]}")

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(safe, todo))

    positions, per_scan = [], {}
    for scan_id, scan in site.scans.items():
        survey_path = site.dir / "surveys" / f"{scan_id}.json"
        surveys = {r["sweep_id"]: r for r in json.loads(survey_path.read_text())} if survey_path.exists() else {}
        labels = {r["id"]: (r.get("label") or (r.get("type") if r.get("type") != "Unlabelled" else None))
                  for r in scan.get("rooms") or []}
        yaws = _face1_yaws(scan_id)
        seen = 0
        for s in scan["sweeps"]:
            path = _position_path(property_id, scan_id, s["id"])
            if path.exists():
                body, source = json.loads(path.read_text()), "vision"
                seen += 1
            elif s["id"] in surveys:
                body, source = _from_survey(surveys[s["id"]]), "survey"
            else:
                continue
            positions.append({
                "scan_id": scan_id, "scan_name": scan["name"], "sweep_id": s["id"],
                "room_id": s.get("room_id"), "room_label": labels.get(s.get("room_id")),
                "heading": s.get("heading"), "face1_yaw": yaws.get(s["id"]), "source": source,
                "survey_note": (surveys.get(s["id"]) or {}).get("note") if source == "vision" else None,
                **body,
            })
        per_scan[scan_id] = {"name": scan["name"], "positions": len(scan["sweeps"]), "indexed": seen}
    if client is not None:
        check_islands(property_id, positions, client)
    _settle_islands(property_id, positions)
    total = sum(v["positions"] for v in per_scan.values())
    indexed = sum(v["indexed"] for v in per_scan.values())
    index = {
        "property_id": property_id, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": VISION_MODEL, "total_positions": total, "indexed_positions": indexed,
        "indexed_share": round(indexed / total, 3) if total else 0.0,
        "survey_only_positions": sum(1 for p in positions if p["source"] == "survey"),
        "new_calls_this_run": calls_used()["index"] - before, "failed_this_run": failed, "calls_used": calls_used(),
        "scans": per_scan, "positions": positions,
    }
    OPEN_DIR.mkdir(parents=True, exist_ok=True)
    (OPEN_DIR / f"{property_id}.json").write_text(json.dumps(index))
    return index


def load_index(property_id: int) -> dict:
    path = OPEN_DIR / f"{property_id}.json"
    if not path.exists():
        raise SearchError(f"no search index for building {property_id}; build it first")
    return json.loads(path.read_text())


# --- text matching ---------------------------------------------------------------------------------------------
# Different ways of saying the same thing, folded to one spelling in both the query and the descriptions.
_SAME = [
    (r"\bsun[- ]?(?:lit|drenched|filled|ny)\b|\bsunlight\b|\bsunshine\b|\bdirect sun\b", "sunlit"),
    (r"\bnatural(?:ly)? li(?:ght|t)\b|\bday[- ]?li(?:ght|t)\b", "daylight"),
    (r"\b(?:glass )?sliders?\b|\bsliding (?:glass )?(?:patio |balcony )doors?\b", "sliding glass door"),
    (r"\b(?:hot[- ])?water[- ](?:heater|tank)s?\b", "waterheater"),
    (r"\bwashing machines?\b|\bclothes washers?\b", "washer"),
    (r"\b(?:clothes|tumble) dryers?\b", "dryer"),
    (r"\bmicrowave ovens?\b", "microwave"),
    (r"\b(?:range|exhaust|vent|stove|oven|cooker) hoods?\b", "rangehood"),
    (r"\b(?:stove|cooktop|stovetop|oven)s?\b", "range"),
    (r"\bfridges?\b", "refrigerator"),
    (r"\b(?:breakfast|kitchen) bars?(?: counters?)?\b|\bbar counters?\b|\bpeninsulas?(?: counters?)?\b", "peninsula"),
    (r"\bfire[- ]places?\b", "fireplace"),
    (r"\b(?:couch|couches|settee|loveseat)s?\b", "sofa"),
    (r"\b(?:patio|terrace|deck|lanai|porch)s?\b", "balcony"),
    (r"\bbath[- ]tubs?\b|\btubs?\b", "bathtub"),
    (r"\b(?:tv|telly)s?\b", "television"),
    (r"\b(?:breaker|fuse|electrical|electric) (?:box|panel)(?:es|s)?\b", "electricalpanel"),
    (r"\b(?:living|sitting|family) (?:room|area)s?\b|\blounges?\b", "livingroom"),
    (r"\bdining (?:room|area)s?\b", "dining"),
    (r"\b(?:bath|rest|wash)rooms?\b", "bathroom"),
    (r"\b(?:bicycle|bike)s?\b", "bicycle"),
    (r"\b(?:barbecue|bbq|grill)s?\b", "grill"),
]
_SAME = [(re.compile(p), r) for p, r in _SAME]
_STOP = set("a an the of in on at to for is are was there any me us show find where which what that this it its i we "
            "our my every all each some please take go see look do does have has can you left loose lying sitting thing "
            "item stuff object anything something everything one room space area spot place unit apartment or by near".split())
_ODD = {"shelves": "shelf", "knives": "knife", "leaves": "leaf", "glass": "glass", "blinds": "blind"}
_SPLIT = re.compile(r"\b(?:with|and|plus|having|that has|that have)\b|[,;&+]")
_ALL = re.compile(r"\b(?:every|all|each)\b")
_GENERIC = re.compile(r"\b(?:things?|items?|stuff|objects?|anything|something|everything)\b")
_FIXED = set("railing rail fence wall ceiling floor door window light lantern post column stair step vent outlet".split())
_LIGHT_WORDS = {"sunlit", "daylight", "artificial", "dim", "dark"}
_NEGATED = re.compile(r"\b(?:no|not|none|without|isn't|aren't|cannot|can't)\b")
_WHERE = {"in this room": 1.0, "outside": 0.95, "through a doorway": 0.75}


def _stem(w: str) -> str:
    if w in _ODD:
        return _ODD[w]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "shes", "ches", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def tokens(text: str | None) -> set[str]:
    """The meaningful words of a phrase: lower case, synonyms folded, plurals removed, filler dropped."""
    text = (text or "").lower()
    for pat, rep in _SAME:
        text = pat.sub(rep, text)
    return {t for t in (_stem(w) for w in re.findall(r"[a-z0-9]+", text)) if t not in _STOP}


def concepts(query: str) -> list[dict]:
    """The separate things a query asks for: 'sunlit kitchen with an island' is two, both required.

    A part that names no object ("things left on a balcony") is marked generic and matched on the kind of thing.
    """
    out = []
    for part in _SPLIT.split(query.lower()):
        want = tokens(part)
        if want:
            out.append({"want": want, "generic": bool(_GENERIC.search(part))})
    return out


def _light_tokens(light: str | None) -> set[str]:
    return {"direct sun": {"sunlit", "daylight"}, "daylight": {"daylight"}, "artificial light": {"artificial"},
            "dim": {"dim", "dark"}}.get(light or "", set())


def _match_concept(concept: dict, pos: dict) -> dict | None:
    """How one position supports one concept: by a single thing (plus the room), the room and light, or a sentence."""
    want = set(concept["want"])
    room, light = tokens(pos.get("room_type")), _light_tokens(pos.get("light"))
    said = []
    lit = want & _LIGHT_WORDS
    if lit:  # light is recorded for where the camera stands, so it can only qualify this room and what is in it
        if not lit <= light:
            return None
        want -= lit
        said.append(pos["light"])
        if not want:
            return {"quality": 1.0, "thing": None, "quarter": None, "where": None, "phrase": pos["light"]}
    nearby = set() if lit else set().union(set(), *[tokens(r) for r in pos.get("spaces_visible") or []])
    best = None
    if concept["generic"]:
        pass  # "things on a balcony" needs things; being on a balcony, or seeing one, is not enough
    elif want <= room:
        best = {"quality": 1.0, "thing": None, "quarter": None, "where": None, "phrase": ", ".join([pos["room_type"]] + said)}
    elif want <= (room | nearby):
        best = {"quality": 0.7, "thing": None, "quarter": None, "where": None,
                "phrase": "visible from here: " + ", ".join(pos.get("spaces_visible") or [])}
    kind_hits = []
    for thing in pos.get("things") or []:
        if lit and thing.get("where") != "in this room":
            continue
        name, kind = tokens(thing.get("name")), tokens(thing.get("category"))
        full = kind if concept["generic"] else name | tokens(thing.get("detail")) | kind
        got = want & full
        rest = want - got
        if not got or not rest <= (room | nearby):
            continue
        if concept["generic"] and name & _FIXED:
            continue  # a railing is part of the balcony, not something left on it
        if not concept["generic"] and not got & name:
            continue  # "trash can (near the island)" is not an island: the name must carry part of the match
        q = (1.0 if got <= name else 0.8) * _WHERE.get(thing.get("where"), 1.0)
        q *= 0.85 + 0.15 * (1.0 if concept["generic"] else len(got & name) / max(1, len(name)))  # a tighter name is a better match
        q *= 1.0 if rest <= room else 0.7
        if concept["generic"]:
            kind_hits.append(thing["name"])
        if best is None or q > best["quality"] or (q == best["quality"] and best["thing"] is None):
            detail = f" ({thing['detail']})" if thing.get("detail") else ""
            extra = ([pos["room_type"]] if rest & room else []) + said
            best = {"quality": q, "thing": thing["name"], "quarter": thing.get("quarter"), "where": thing.get("where"),
                    "phrase": thing["name"] + detail + "".join(f"; {e}" for e in extra)}
    if best:
        if kind_hits:  # a generic ask is answered with everything of that kind seen from here
            best["phrase"] = f"{pos.get('room_type') or 'position'}: " + ", ".join(dict.fromkeys(kind_hits))
        return best
    if lit or concept["generic"]:
        return None
    for text in (pos.get("description"), pos.get("survey_note")):
        for sentence in re.split(r"(?<=[.;!?])\s+", text or ""):
            if want <= tokens(sentence) and not _NEGATED.search(sentence.lower()):
                return {"quality": 0.5, "thing": None, "quarter": None, "where": None, "phrase": sentence.strip()}
    return None


def _matches(index: dict, query: str) -> list[dict]:
    """Every indexed position whose description supports every concept in the query, best first."""
    wanted = concepts(query)
    if not wanted:
        return []
    out = []
    for n, pos in enumerate(index["positions"]):
        found = [_match_concept(c, pos) for c in wanted]
        if not all(found):
            continue
        # Face the thing itself when one was matched; prefer the last concept ("... with an island" faces the island).
        lead = next((f for f in reversed(found) if f["quarter"] is not None), None) or \
            next((f for f in reversed(found) if f["thing"]), found[-1])
        deg = bearing(pos.get("heading"), lead["quarter"])
        phrases = list(dict.fromkeys(f["phrase"] for f in found if f["phrase"]))
        out.append({
            "scan_id": pos["scan_id"], "scan_name": pos["scan_name"], "sweep_id": pos["sweep_id"],
            "room_id": pos.get("room_id"), "room": pos.get("room_type") or pos.get("room_label"),
            "thing": lead["thing"], "where": lead["where"], "quarter": lead["quarter"],
            "bearing_deg": deg, "direction": compass(deg), "viewer_yaw": viewer_yaw(pos.get("face1_yaw"), lead["quarter"]),
            "phrase": "; ".join(phrases), "description": pos.get("description"), "source": pos.get("source"),
            "score": round(sum(f["quality"] for f in found) / len(found), 3), "_n": n,
        })
    out.sort(key=lambda r: (-r["score"], r["_n"]))
    return out


def _room_key(r: dict) -> tuple:
    return r["scan_id"], r.get("room_id") or r["sweep_id"]


def _rerank(client, query: str, ranked: list[dict]) -> list[dict]:
    """One model call over the top text matches: keep only those that truly fit, best first. Text order on any failure."""
    pool = ranked[:RERANK_POOL]
    listing = "\n".join(f"{i + 1}. {r['scan_name']} / {r['room'] or 'room'}: {r['description']} Matched: {r['phrase']}."
                        for i, r in enumerate(pool))
    try:
        _spend("search", MAX_SEARCH_CALLS)
        resp = client.messages.create(
            model=VISION_MODEL, max_tokens=512,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": RERANK_SCHEMA}},
            messages=[{"role": "user", "content": [{"type": "text", "text": (
                f"Someone searching a building scan asked for: \"{query}\". Below are descriptions of camera positions "
                "that matched by text. Return the numbers of the ones whose description really shows what was asked "
                "for, best first. Leave out any that do not; an empty list is a fine answer.\n\n" + listing)}]}],
        )
        order = [i for i in dict.fromkeys(_json_reply(resp)["order"]) if 1 <= i <= len(pool)]
    except Exception:
        return ranked
    return [dict(pool[i - 1], reranked=True) for i in order]


def search(property_id: int, query: str, k: int = 5, client=None) -> list[dict]:
    """The best-matching scan positions for a spoken or typed query; an empty list when nothing indexed supports it."""
    ranked = _matches(load_index(property_id), query)
    if client is not None and len(ranked) > 1:
        ranked = _rerank(client, query, ranked)
    per_room = None if _ALL.search(query.lower()) else 2
    out, used = [], {}
    for r in ranked:
        key = _room_key(r)
        if per_room is not None and used.get(key, 0) >= per_room:
            continue
        used[key] = used.get(key, 0) + 1
        out.append({a: b for a, b in r.items() if a not in ("_n", "description")})
        if len(out) >= k:
            break
    return out


def count(property_id: int, query: str) -> dict:
    """How many rooms and scans show the thing, always beside the share of positions that were looked at."""
    index = load_index(property_id)
    found = _matches(index, query)
    # A thing seen through a doorway belongs to the next room; count it only where nothing nearer shows it.
    near = [r for r in found if r["where"] != "through a doorway"] or found
    rooms = {_room_key(r) for r in near}
    by_scan: dict[str, dict] = {}
    for r in near:
        e = by_scan.setdefault(r["scan_id"], {"scan_id": r["scan_id"], "scan_name": r["scan_name"], "rooms": set()})
        e["rooms"].add(_room_key(r))
    total, indexed = index["total_positions"], index["indexed_positions"]
    share = f"{indexed} of {total} scan positions were indexed ({round(100 * indexed / total) if total else 0}%)"
    if not found:
        statement = f"Nothing indexed shows \"{query}\"; {share}."
    else:
        statement = (f"\"{query}\" is seen in {len(rooms)} room{'s' if len(rooms) != 1 else ''} across {len(by_scan)} of "
                     f"{len(index['scans'])} scans; {share}"
                     + (", so the true number may be higher." if indexed < total else "."))
    return {
        "query": query, "rooms": len(rooms), "scans": len(by_scan), "positions": len(found),
        "total_scans": len(index["scans"]), "indexed_positions": indexed, "total_positions": total,
        "indexed_share": index["indexed_share"], "complete": indexed == total, "statement": statement,
        "by_scan": [{"scan_id": e["scan_id"], "scan_name": e["scan_name"], "rooms": len(e["rooms"])} for e in by_scan.values()],
    }
