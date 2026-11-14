"""Checking what a resident reports against the scan made before the storm.

`site_model` files a report against the room its words name and judges nothing. This is the judging,
kept as a separate step. The scan is the record of the home before the damage, so it can answer one
question only: does the place the report describes exist in this home the way the report says?

  fits         the thing the report names was seen in the room it was filed against
  wrong_place  the report names a room and a thing; the room is in this home's scan, the thing was not
               seen there (and where in the home it was seen is said, if anywhere)
  cannot_tell  the scan holds nothing that answers it

There is no verdict about how bad the damage is. The scan was made before it and cannot measure it.

The verdict is worked out by code from the scan's search index, never by a model, and costs nothing.
Separately, the scan's own photograph in the report's direction is shown once to the vision model, which
records what was there before the storm: the thing, the floor, and any damage already visible. That look
is paid, is kept on disk, and is never made twice for one report.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from . import matterport, site_model, vision
from .config import VISION_MODEL
from .openproblems import search

MAX_LOOKS = 12                     # paid looks this module may make for one building
PITCH_DEG, HFOV_DEG = -15.0, 100.0  # tilted down a little, so the floor in front of the thing is in the picture
WIDTH, HEIGHT = 1200, 900
BASIS = "read from the scan's photograph by a vision model; the scan was made before the storm"
INDEXED = "read from this scan position's all-round view by a vision model when the scan was indexed"
MISSES = "a description can miss or misname a thing"

PROMPT = (
    "This photograph was cut from a 3D scan of an apartment home. The scan was made before a storm. After the storm a "
    "resident reported: “{text}”. The photograph looks from the scan towards the place that report describes, "
    "as it was before the storm, so the reported damage is not in it. Say only what is visible in this photograph. "
    "Name the thing the report is about as it appears here (for a door: what kind, its frame and threshold), and say "
    "whether it is in view at all. Name the floor covering in front of it. Then say whether any damage, staining, water "
    "marks or heavy wear is already visible on or around it, and describe it in one sentence, or say that none is "
    "visible. Do not guess at anything you cannot see.")
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["thing_in_view", "thing", "floor_covering", "damage_already_visible", "damage_or_staining"], "properties": {
              "thing_in_view": {"type": "boolean"}, "thing": {"type": "string"}, "floor_covering": {"type": "string"},
              "damage_already_visible": {"type": "boolean"}, "damage_or_staining": {"type": "string"}}}

_NEAREST_FIRST = {"in this room": 0, "outside": 1, "through a doorway": 2}
_LOOKING = threading.Lock()        # two requests for the same report must not both pay for the look


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _positions(property_id: int) -> list[dict]:
    """Every described scan position at a building, or none when its scans have not been indexed."""
    return (_read(site_model.OPEN / "search" / f"{property_id}.json") or {}).get("positions") or []


def _said(text: str | None) -> set[str]:
    return search.tokens(re.sub(r"^Support request \([^)]*\):\s*", "", text or ""))


def _as_written(text: str | None, matched: set[str]) -> list[str]:
    """The report's own words behind the matched ones, so a reader sees "living room" and not the folded form it was matched as."""
    raw = re.findall(r"[a-z0-9']+", re.sub(r"^Support request \([^)]*\):\s*", "", text or "").lower())
    kept = [w for w in dict.fromkeys(raw) if search.tokens(w) and search.tokens(w) <= matched]
    for pair in (f"{a} {b}" for a, b in zip(raw, raw[1:]) if a not in kept and b not in kept):
        if search.tokens(pair) and search.tokens(pair) <= matched and pair not in kept:
            kept.append(pair)
    return kept


def _a(name: str) -> str:
    return f"{'an' if name[:1].lower() in 'aeiou' else 'a'} {name}"


def _room_of(position: dict) -> str:
    return str(position.get("room_label") or position.get("room_type") or "room").lower()


def _placed(property_id: int, report: dict) -> dict | None:
    """Where the report sits in the scan. One tied to a home but not to a room is matched on its words inside that home."""
    where = report.get("where")
    if where and (where.get("room_id") or where.get("position_id")):
        return where
    home = (where or {}).get("scan_id") or report.get("scan_id")
    return site_model.locate(property_id, report.get("text") or "", home) if home else where


def _matches(positions: list[dict], words: set[str]) -> list[dict]:
    """The things seen from these positions that the report's words name, nearest and best named first.

    A thing counts when the report uses at least half the words of its name, the same bar `locate` files by."""
    found = []
    for position in positions:
        for thing in position.get("things") or []:
            name = search.tokens(thing.get("name"))
            hit = len(words & name) / len(name) if name else 0.0
            if hit >= 0.5:
                found.append({"thing": thing, "position": position, "hit": hit})
    return sorted(found, key=lambda m: (_NEAREST_FIRST.get(m["thing"].get("where"), 1), -m["hit"]))


def _view(match: dict) -> dict:
    position = match["position"]
    return {"scan_id": position["scan_id"], "position_id": position["sweep_id"],
            "bearing_deg": search.bearing(position.get("heading"), match["thing"].get("quarter"))}


def _seen_fact(match: dict) -> dict:
    """One thing the index holds, as a sentence: what, from which room, whether in it or beyond it, and the index's own words."""
    thing, room = match["thing"], _room_of(match["position"])
    spot = {"outside": "outside it", "through a doorway": "through a doorway"}.get(thing.get("where"), "in that room")
    detail = (thing.get("detail") or "").strip().rstrip(".")
    return site_model.fact(f"A scan position in the {room} recorded {_a(thing['name'])} {spot}" + (f": {detail}." if detail else "."),
                           [f"matterport:{match['position']['scan_id']}"], how=INDEXED, limits=MISSES)


def _answer(verdict: str, says: str, because: list[dict], view: dict | None = None) -> dict:
    return {"verdict": verdict, "says": says, "because": because, "view": view, "before": None}


def check(property_id: int, report: dict) -> dict:
    """Whether a resident's report fits the scan made before the storm. Decided by code from the scan's index; no model is asked."""
    positions = _positions(property_id)
    if not positions:
        return _answer("cannot_tell", "The scan cannot tell: this building's scans have not been described yet, so there is nothing to check the report against.", [])
    where = _placed(property_id, report)
    home = (where or {}).get("scan_id") or report.get("scan_id")
    in_home = [p for p in positions if p["scan_id"] == home]
    if home and not in_home:
        return _answer("cannot_tell", "The scan cannot tell: there is no scan of this home to check the report against.", [])
    if not where:
        return _answer("cannot_tell", "The scan cannot tell: the report names no room or fixture that the scans recorded.", [])

    src = [f"matterport:{home}"]
    own = next((p for p in in_home if p["sweep_id"] == where.get("position_id")), None)
    room_id = where.get("room_id") or (own or {}).get("room_id")
    in_room = [p for p in in_home if p.get("room_id") == room_id] if room_id else ([own] if own else [])
    if not in_room:
        return _answer("cannot_tell", "The scan cannot tell: it has no position inside the room the report was filed against.", [])
    in_room.sort(key=lambda p: p is not own)                      # the report's own position is read first
    room = _room_of(in_room[0])                                   # the scan's own name for it, not the report's
    words = _said(report.get("text"))
    room_words = set().union(*(search.tokens(f"{p.get('room_type') or ''} {p.get('room_label') or ''}") for p in in_room))
    # A report bound to a room by the resident's verified home carries no matched words: its room is given, not guessed.
    names_room = bool(words & room_words) or "matched_on" not in where
    naming = words - room_words                                   # "balcony" names the room, not the balcony railing
    because = [site_model.fact(f"This home's scan ({in_room[0].get('scan_name') or home}) has a {room} with {len(in_room)} scan position{'' if len(in_room) == 1 else 's'} in it.",
                               src, how="Matterport's room label" if in_room[0].get("room_label") else "the room type seen from a scan position")]
    matched = _as_written(report.get("text"), words & (room_words | set().union(set(), *(search.tokens(m["thing"]["name"]) for m in _matches(in_home, naming)))))
    if matched:
        because.append(site_model.fact(f"The report's words that the scan could be matched on: {', '.join(matched)}.", ["resident:report"] + src))
    placed = {"scan_id": home, "position_id": own["sweep_id"], "bearing_deg": where.get("bearing_deg")} if own else None

    # A report that names no room is checked against the whole home; one that names a room, against that room.
    seen = _matches(in_room if names_room else in_room + [p for p in in_home if p not in in_room], naming)
    near = [m for m in seen if m["thing"].get("where") != "through a doorway"]
    if near:
        top, name = near[0], near[0]["thing"]["name"]
        facts, told = [], set()
        for m in near:                                            # each thing once, as its nearest sighting
            if m["thing"]["name"] not in told and len(facts) < 3:
                told.add(m["thing"]["name"])
                facts.append(_seen_fact(m))
        if not names_room:
            says = f"Fits the scan: this home has {_a(name)}, seen in the {_room_of(top['position'])}; the report does not say which room."
        elif top["thing"].get("where") == "outside":
            says = f"Fits the scan: {_a(name)} was seen from this home's {room}, just outside it, from a scan position there."
        else:
            says = f"Fits the scan: this home's {room} has {_a(name)}, seen from a scan position there."
        return _answer("fits", says, because + facts, placed if placed and placed["bearing_deg"] is not None else _view(top))
    if seen:
        name = seen[0]["thing"]["name"]
        return _answer("cannot_tell", f"The scan cannot tell: {_a(name)} is seen from this home's {room} only through a doorway, so the scan does not settle which room it is in.",
                       because + [_seen_fact(seen[0])], placed)
    if not names_room:
        return _answer("cannot_tell", "The scan cannot tell: the report names no room or fixture that this home's scan recorded.", because, placed)

    # Saying a report is in the wrong place rests on a firmer match than agreeing with it: most of the thing's name, and seen inside a room.
    def firmly(found: list[dict]) -> list[dict]:
        return [m for m in found if m["hit"] > 0.5 and m["thing"].get("where") == "in this room"]

    nothing = f"The scan position in the {room} did not record" if len(in_room) == 1 else f"None of the {len(in_room)} scan positions in the {room} recorded"
    elsewhere = firmly(_matches([p for p in in_home if p not in in_room], naming))
    if elsewhere:
        name = elsewhere[0]["thing"]["name"]
        rooms = list(dict.fromkeys(_room_of(m["position"]) for m in elsewhere if m["thing"]["name"] == name))
        return _answer("wrong_place", f"Does not fit the scan as described: no {name} was seen in this home's {room}; the scan shows one in the {' and the '.join(rooms[:2])}.",
                       because + [site_model.fact(f"{nothing} {_a(name)}.", src, how=INDEXED, limits=MISSES), _seen_fact(elsewhere[0])], _view(elsewhere[0]))
    known = firmly(_matches([p for p in positions if p["scan_id"] != home], naming))
    if known:
        name = known[0]["thing"]["name"]
        return _answer("wrong_place", f"Does not fit the scan as described: no {name} was seen in this home's {room} or anywhere else in its scan.",
                       because + [site_model.fact(f"{nothing} {_a(name)}, and neither did any other position in this home.", src, how=INDEXED, limits=MISSES)], placed)
    return _answer("cannot_tell", f"The scan cannot tell: the report names the {room}, which this home has, but no fixture the scan recorded there.", because, placed)


# --- the look at how it was before ------------------------------------------------------------------------
def _path(property_id: int) -> Path:
    return site_model.OPEN / "report_checks" / f"{property_id}.json"


def looks(property_id: int) -> dict[str, dict]:
    """The looks already made at a building, by report id: the view each was made from and what was read."""
    return _read(_path(property_id)) or {}


def photograph(property_id: int, view: dict | None) -> Image.Image | None:
    """The scan's own photograph from a position, facing a bearing: an ordinary picture cut from its panorama.

    The bearing is a compass direction and the panorama is stored by its own first side view, so the position's
    heading is needed to turn one into the other. None when there is no bearing, no heading or no imagery."""
    if not view or view.get("bearing_deg") is None:
        return None
    position = next((p for p in _positions(property_id) if p["scan_id"] == view["scan_id"] and p["sweep_id"] == view["position_id"]), None)
    if position is None or position.get("heading") is None:
        return None
    from .openproblems import reimagine_view as rv
    try:
        cube = rv.load_cube(view["scan_id"], view["position_id"])
    except (matterport.MatterportError, OSError):
        return None
    turn = (view["bearing_deg"] - position["heading"]) % 360
    return Image.fromarray(rv.wide_view(cube, turn, PITCH_DEG, HFOV_DEG, WIDTH, HEIGHT).clip(0, 255).astype("uint8"))


def _client():
    import anthropic
    return anthropic.Anthropic()


def _look(image: Image.Image, text: str, client) -> tuple[bool, dict | None]:
    """One paid look. Says whether the model answered at all, and what it read (None when it declined or its reply could not be read)."""
    try:
        resp = (client or _client()).messages.create(
            model=VISION_MODEL, max_tokens=600, output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [vision.image_block(image, max_side=1280), {"type": "text", "text": PROMPT.replace("{text}", text)}]}])
    except Exception:
        return False, None
    if resp.stop_reason == "refusal":
        return True, None
    try:
        read = json.loads(next(b.text for b in resp.content if b.type == "text"))
    except (ValueError, StopIteration, AttributeError):
        return True, None
    return True, read if isinstance(read, dict) else None


def checked(property_id: int, report: dict, client=None, look: bool = True) -> dict:
    """The check, with what the scan's photograph showed before the storm.

    The verdict is worked out fresh each time; it costs nothing. The look is the paid part: it is made once per
    report, kept, and reused for as long as the report still points the same way. With `look=False` nothing is
    paid for: a look already kept is returned, a missing one is left out. Without a key, an image or an answer
    the check comes back with `before` empty and the verdict stands on its own.
    """
    found = check(property_id, report)
    view, rid = found["view"], str(report.get("id") or "")
    # Only a report the scan agrees with, or cannot settle, is looked at: its view is the place it was filed against.
    if not rid or found["verdict"] == "wrong_place" or not view or view.get("bearing_deg") is None:
        return found
    def kept_look(kept: dict) -> dict:                             # a look made in another direction is not this report's "before"
        return {**found, "before": kept[rid].get("before") if kept[rid].get("view") == view else None}

    kept = looks(property_id)
    if rid in kept:                                               # looked at once already: never again
        return kept_look(kept)
    if not look:
        return found
    with _LOOKING:
        kept = looks(property_id)                                 # another request may have looked while this one waited
        if rid in kept:
            return kept_look(kept)
        if len(kept) >= MAX_LOOKS:
            return found
        image = photograph(property_id, view)                     # before spending: a missing image costs nothing
        if image is None:
            return found
        answered, read = _look(image, " ".join(str(report.get("text") or "").split())[:300], client)
        if not answered:
            return found                                          # no key or no connection: nothing was read, so it may be tried again
        before = {**read, "basis": BASIS} if read else None
        kept[rid] = {"view": view, "before": before, "looked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _path(property_id).parent.mkdir(parents=True, exist_ok=True)
        _path(property_id).write_text(json.dumps(kept, indent=1))
        return {**found, "before": before}
