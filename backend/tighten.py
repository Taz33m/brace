"""Tighter prices for the schedule, and only where a page states one for a more specific thing.

The schedule's ranges are wide because each line is priced as a kind: any bathtub, any floor. Three things narrow a
line without making a number up, and each is a price found on a page and confirmed there by `flood_agent.confirm`:

* fitting: the labour to fit ONE of a kind the owner buys as a product (a toilet, a ceiling fan; delivery and hook-up
  for an appliance). A line with a matched product (`product_match`) is that product's listed price plus this, so it
  is supplied and installed like every cost-guide line. Saved in `fitting.json`.
* specific: built work is not a product. The inventory says what this one is ("white tub with tiled surround"), and
  the research looks for the installed price of that. Saved in `<scan>.specific.json` under '<room_id>:<kind>'.
* finishes: one look at the scan says what each room's floor is and what the doors, walls and baseboards are, and
  the research prices those finishes. Saved in `<scan>.finishes.json` and `work.json`.

The rules, all here and none in a prompt:

* a price is used only if the check found it and its sentence on the fetched page (`flood_agent.confirm`), and the
  sentence itself gives the figures; an unconfirmed row is saved, shown and never used, and the line keeps the
  price it had;
* nothing here narrows a range by arithmetic. There is no midpoint, no average, no percentage. The only sum is a
  product's price plus the labour to fit it, low with low and high with high;
* where an item has several confirmed rows, the choice is by place (Los Angeles, then California, then the rest) and
  then by which was recorded first. Never by which is narrower;
* a specific price that is wider than the generic one is still used, because it is for the thing that is there;
* a specific price belongs to the words it was priced under: what the reader wrote of the item, what the look said
  of the doors. If the scan is read again and the words change, the price is dropped;
* a reviewer can set a confirmed row aside, with a reason that stays in the file. Nothing can do the opposite;
* a finish is one from a fixed list with a phrase of what was seen, or it is not a finish. "cannot tell" prices nothing;
* unknown is null, never zero.

Run with `python -m scripts.tighten`.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from . import flood_agent, inventory_agent, matterport, vision
from .config import AGENT_MODEL

# What a line's price rests on. A line with no price has no basis.
MATCH_FITTED, MATCH_BARE = "matched product plus fitting", "matched product, fitting not priced"
SEEN, GUIDE = "cost guide for what was seen", "cost guide, supplied and installed"

# Built in place, never bought as one product: priced for what the reader described. Everything else in KINDS is a product somebody fits.
MIN_TO_PRICE = 2        # products kept for an item before its match is used as the line's price
BUILT = ("bathtub or shower", "kitchen countertop")
CABINETS = ("base cabinet", "wall cabinet", "tall cabinet")      # a product when stock, built work when the reader called it built-in
DELIVERED = ("refrigerator", "range", "dishwasher", "washer", "dryer")      # fitting one of these is delivery and hook-up

SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 24}
FETCH = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 30}
PLACES = ("Los Angeles", "California")      # a figure for one of these is preferred, and only when the page names the place

# The finishes a look at the scan may name. Anything else, and "cannot tell", is no finish. Each priced finish has the words it is researched under.
CANNOT = "cannot tell"
FLOORS = {"carpet": "Carpet with pad", "vinyl plank": "Vinyl plank flooring", "sheet vinyl": "Sheet vinyl flooring", "laminate": "Laminate flooring",
          "ceramic or porcelain tile": "Ceramic or porcelain floor tile", "hardwood": "Hardwood flooring"}
DOORS = {"flush": "Interior door, flush (a flat slab)", "panelled": "Interior door, panelled", "louvred": "Interior door, louvred"}
WALLS = {"smooth painted": ("a smooth finish", "smooth"), "textured painted": ("a sprayed texture such as orange peel", "textured")}
OTHER_WALLS = ("wallpaper", "wood panelling")      # may be named, but drywall and paint are not priced for them
BASEBOARDS = {"painted wood or MDF": "Painted wood or MDF baseboard", "stained wood": "Stained wood baseboard", "vinyl or rubber cove": "Vinyl or rubber cove base"}
OTHER_BASEBOARDS = ("tile", "none")
# Which finish prices which building-work line, and what is asked for. The line ids are the schedule's.
WORK = {
    "flooring": ("per square foot", {k: f"{v}, supplied and installed (materials and labour)" for k, v in FLOORS.items()}),
    "door": ("each", {k: f"{v}, with its frame (pre-hung), supplied and installed" for k, v in DOORS.items()}),
    "drywall": ("per square foot", {k: f"Drywall hung and finished with {v[0]}, ready for paint (materials and labour)" for k, v in WALLS.items()}),
    "paint": ("per square foot of wall", {k: f"Interior wall painting on {v[1]} walls (labour and paint)" for k, v in WALLS.items()}),
    "baseboard": ("per linear foot", {k: f"{v}, supplied and installed" for k, v in BASEBOARDS.items()}),
}
HOME_FINISH = {"drywall": "wall", "paint": "wall", "baseboard": "baseboard", "door": "door"}      # flooring is by room; these are for the whole home
MAX_PICTURES = 8

SYSTEM = """You research prices for Brace, which prepares a schedule of what the owner of an apartment community in Los Angeles would have to replace in a rental apartment home after a fire. You are given a list of things to price, each described specifically and each in a stated unit.

For each thing on the list, find a page that states its price and call record_price once.

Rules
- Record a price only when a page states it for that thing as it is described, in the unit asked for. Copy the sentence that states the price into quote, word for word, and give that page's address. The sentence you copy must itself contain the figures you record.
- When the page gives a range, record its low end as price and its high end as price_high, exactly as the page gives them. Do not narrow a range, average it, pick a point in it, or work out a price yourself, and do not convert one unit into another.
- Each thing is described more narrowly than its general kind. Record the price a page states for that narrower thing. If a page only prices the general kind, look for another page. If no page prices the narrower thing, leave it out: nothing recorded is better than a price for something else.
- Prefer a page that gives a figure for Los Angeles or for California, and say so in place. Otherwise a United States figure is wanted. Never adjust a figure for place yourself.
- Prefer a cost guide, a trade publication, or a contractor's or supplier's page that states a price. Prefer a web page to a PDF file: a PDF cannot be checked here.
- Open the page with web_fetch before you record from it, so the price can be checked against the page as it was read.
- You are told whether each record was confirmed on its page. If it was not, try once more with the sentence exactly as the page has it or with another page, then move on.
- Stop when the list is covered or after twenty-four searches. Finish with one line saying how many were confirmed."""

ABOUT = {
    "fitting": "This list is the labour to fit things the owner buys as products. For each, the price wanted is labour only, for ONE: what a plumber, an electrician or an installer charges to fit it, or for an appliance to deliver it and hook it up, without the product itself. Cost guides often state it beside the total as the cost of labor alone; record that labour figure and never a total that includes the product. An hourly rate is not a price for one.",
    "specific": "This list is built work in one home, each described in the words of whoever read the scan of it. The price of the general kind (any bathtub, any countertop) is already known and is wide because it covers every material. Find the installed price, materials and labour together, that a page states for this one: its material and its form as described.",
    "work": "This list is the finishes of one home as they were read from a scan of it. Find what each costs supplied and installed, materials and labour together, in an apartment refit.",
}

FINISH_SYSTEM = """You look at pictures from the scan Matterport made of one rental apartment home and say what its finishes are, so the building work to put the home back can be priced for what is there.

Say only what the pictures show.
- For each room pictured, the floor finish.
- For the home as a whole: what kind of interior doors it has, the wall finish, and the baseboard.
- Name a finish only when you can see what tells it apart: for a floor the pile, the plank seams and their width, grout lines, the sheen; for a door a flat face or panels; for a wall its texture. Vinyl plank, laminate and hardwood can look alike in a photograph: name one only if the pictures show what distinguishes it.
- Where the pictures do not show it, or you cannot tell two finishes apart, answer "cannot tell". That is a good answer. Do not infer from the age or the kind of building.
- With each answer give one short phrase of what you saw, for example "grey wood-look planks, tight seams, low sheen". For "cannot tell", say in the phrase what stopped you."""


# ---- where it is kept ----------------------------------------------------------------------------------

def fitting_path():
    return inventory_agent.OUT / "fitting.json"


def work_path():
    return inventory_agent.OUT / "work.json"


def specific_path(scan_id: str):
    return inventory_agent.OUT / f"{scan_id}.specific.json"


def finishes_path(scan_id: str):
    return inventory_agent.OUT / f"{scan_id}.finishes.json"


def key_of(room_id: str, kind: str) -> str:
    return f"{room_id}:{kind}"


def _read(path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _number(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def rows(path) -> list[dict]:
    """Every price row in a saved file, confirmed or not. A file is either a research run ({"prices": [...]}) or rows under their keys."""
    data = _read(path)
    found = data["prices"] if isinstance(data.get("prices"), list) else [v for v in data.values() if isinstance(v, dict) and "item" in v]
    return [r for r in found if isinstance(r, dict) and isinstance(r.get("item"), str) and _number(r.get("price")) and isinstance(r.get("source"), dict) and r["source"].get("url")]


def confirmed(path, words: dict[str, str | None] | None = None) -> dict[str, dict]:
    """The row in use for each item: confirmed on its page and not set aside, a local figure before a national one, and otherwise the first recorded.
    Width plays no part. With `words` (what was seen, by item), a row counts only for the words it was priced under."""
    by: dict[str, dict] = {}
    local = lambda r: PLACES.index(r["place"]) if r.get("place") in PLACES else len(PLACES)
    for row in sorted((r for r in rows(path) if r.get("checked") is True and not r.get("set_aside")), key=local):      # the sort is stable: within a place, the order they were recorded in
        if words is None or (row["item"] in words and row.get("seen") == words[row["item"]]):
            by.setdefault(row["item"], row)
    return by


def set_row_aside(path, item_id: str, why: str) -> int:
    """A reviewer's refusal of confirmed rows for one item: they stay in the file with the reason, are never used, and the item is not asked for again
    while its words stand. Returns how many rows were set aside. There is no way here to make an unconfirmed row count."""
    data, why = _read(path), " ".join(str(why or "").split())[:300]
    if not why:
        raise ValueError("say why the price is set aside")
    found = [r for r in (data["prices"] if isinstance(data.get("prices"), list) else data.values()) if isinstance(r, dict) and r.get("item") == item_id and r.get("checked") is True and not r.get("set_aside")]
    for r in found:
        r["set_aside"] = why
    if found:
        path.write_text(json.dumps(data, indent=1))
    return len(found)


def saved_finishes(scan_id: str) -> dict:
    return _read(finishes_path(scan_id))


# ---- what the schedule asks ----------------------------------------------------------------------------

_ASIDE = False


@contextmanager
def set_aside():
    """The schedule as it stands without anything saved here, for a before and after."""
    global _ASIDE
    was, _ASIDE = _ASIDE, True
    try:
        yield
    finally:
        _ASIDE = was


def finish_of(finishes: dict, line: str, room_id: str | None = None) -> str | None:
    """The finish that prices one building-work line, as it was read from the scan. None when it was not read, could not be told, or is not one that is priced."""
    entry = (finishes.get("rooms") or {}).get(room_id) if line == "flooring" else (finishes.get("home") or {}).get(HOME_FINISH.get(line, ""))
    finish = entry.get("finish") if isinstance(entry, dict) else None
    return finish if line in WORK and finish in WORK[line][1] and str(entry.get("seen") or "").strip() else None


class Tight:
    """What is saved for one scan, as the schedule's lines take it."""

    def __init__(self, scan_id: str):
        aside = _ASIDE
        inv = {} if aside else inventory_agent.saved(scan_id) or {}
        self.finishes = {} if aside else saved_finishes(scan_id)
        self.fitting = {} if aside else confirmed(fitting_path())
        self.specific = {} if aside else confirmed(specific_path(scan_id), {key_of(i["room"], i["kind"]): i.get("seen") for i in inv.get("items") or []})
        self.work = {} if aside else confirmed(work_path(), {i["id"]: i.get("seen") for i in _work_items(self.finishes)})

    def fit(self, item: dict) -> dict:
        """For a line of fit-out: the labour to fit one of its kind, and the price of this one as the reader described it, if those words still stand."""
        row = self.specific.get(key_of(item["room"], item["kind"]))
        return {"fitting": self.fitting.get(f"fitting:{item['kind']}"), "specific": row if row and row.get("seen") == item.get("seen") else None}

    def built(self, line: str, room_id: str | None = None) -> dict:
        """For a line of building work: the finish read from the scan, and its price if one was confirmed."""
        finish = finish_of(self.finishes, line, room_id)
        return {"specific": self.work.get(f"{line}:{finish}") if finish else None, "finish": f"{finish}, read from the scan" if finish else None}


def _range(row: dict | None) -> tuple[float | None, float | None]:
    low = _number(row.get("price")) if row else None
    return (low, _number(row.get("price_high")) or low) if low else (None, None)


def price_of(guide: dict | None, match: dict | None = None, fitting: dict | None = None, specific: dict | None = None) -> dict:
    """The price of one, and what it rests on. A matched product comes first, then a price for what was seen, then the cost guide for the kind.

    The guide's range is carried whichever is used. Nothing is worked out here but the one sum: a product's price and the labour to fit it.
    """
    guide_low, guide_high = _range(guide)
    seen_low, seen_high = _range(specific)
    fit_low, fit_high = _range(fitting)
    page = guide
    out = {"fitting_low": None, "fitting_high": None, "fitting_url": None}
    # One lookalike is not a range: a match sets the price only when at least two products were kept for it. A single one stays on the line to be seen.
    if match and match.get("low") is not None and match.get("high") is not None and len(match.get("candidates") or []) >= MIN_TO_PRICE:
        low, high, basis = match["low"], match["high"], MATCH_BARE
        if fit_low is not None:
            low, high, basis = low + fit_low, high + fit_high, MATCH_FITTED
            out = {"fitting_low": fit_low, "fitting_high": fit_high, "fitting_url": fitting["source"]["url"]}
    elif seen_low is not None:
        low, high, basis, page = seen_low, seen_high, SEEN, specific
    else:
        low, high, basis = guide_low, guide_high, GUIDE if guide_low is not None else None
    source = (page or {}).get("source") or {}
    return {"price_low": low, "price_high": high, "price_basis": basis, "source_url": source.get("url"), "source_title": source.get("title"),
            "guide_low": guide_low, "guide_high": guide_high, **out}


# ---- what is to be priced ------------------------------------------------------------------------------

def fitting_items(first: list[str] | None = None) -> list[dict]:
    """The labour to fit one of each kind that is bought as a product. The kinds in `first` head the list, so a short run reaches them."""
    kinds = [k for k in inventory_agent.KINDS if k not in BUILT]
    kinds.sort(key=lambda k: k not in (first or []))
    def what(kind: str) -> str:
        name = inventory_agent.KINDS[kind].lower()
        return (f"Delivery and hook-up of one {name} in an apartment: labour only, not the price of the appliance" if kind in DELIVERED
                else f"Labour only to fit one {name} in an apartment, not the price of the {name} itself")
    return [{"id": f"fitting:{k}", "what": what(k), "unit": "each"} for k in kinds]


def is_built(item: dict) -> bool:
    """Built work: a tub or a countertop always; a cabinet when whoever read the scan called it built-in."""
    return item.get("kind") in BUILT or (item.get("kind") in CABINETS and "built-in" in str(item.get("seen") or "").lower())


def built_items(scan_id: str) -> list[dict]:
    """Each item of built work in the saved inventory, to be priced as the reader described it."""
    inv = inventory_agent.saved(scan_id)
    if not inv:
        raise ValueError("this scan has not been read yet, so there is nothing to price")
    area = {r["id"]: r.get("area_sqft") for r in inv.get("rooms") or []}
    out = []
    for i in inv.get("items") or []:
        if not is_built(i) or not str(i.get("seen") or "").strip():
            continue
        room = str(i.get("room_name") or i["room"]).lower()
        size = f" The {room} is {area[i['room']]:g} sq ft of floor." if area.get(i["room"]) else ""
        many = f" There are {i['quantity']} in the room: the price of one." if i.get("quantity", 1) > 1 else ""
        out.append({"id": key_of(i["room"], i["kind"]), "unit": "each", "seen": i["seen"],
                    "what": f"{inventory_agent.KINDS[i['kind']]} in the {room} of an apartment, described from a scan of it as \"{i['seen']}\". Supplied and installed, the price of one.{many}{size}"})
    return out


def _work_items(finishes: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for line, (unit, texts) in WORK.items():
        rooms = list(finishes.get("rooms") or {}) if line == "flooring" else [None]
        for room_id in rooms:
            finish = finish_of(finishes, line, room_id)
            if not finish or f"{line}:{finish}" in found:
                continue
            item = {"id": f"{line}:{finish}", "what": texts[finish], "unit": unit}
            if line != "flooring":      # one answer for the whole home, so the price is for those words; a floor finish is shared by rooms that were each described differently
                seen = finishes["home"][HOME_FINISH[line]]["seen"]
                item = {**item, "what": f'{texts[finish]}. In a scan of the home: "{seen}"', "seen": seen}
            found[item["id"]] = item
    return list(found.values())


def work_items(scan_id: str) -> list[dict]:
    """Each finish that was read from the scan and prices a building-work line, once."""
    finishes = saved_finishes(scan_id)
    if not finishes:
        raise ValueError("this scan's finishes have not been read yet")
    return _work_items(finishes)


# ---- the research --------------------------------------------------------------------------------------

def _tool(ids: list[str]) -> dict:
    return {
        "name": "record_price",
        "description": "Record the stated price of one thing on the list, with the page it came from. Call once for each thing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "enum": ids, "description": "Which thing on the list this prices."},
                "price": {"type": "number", "description": "The stated price in US dollars, in the unit the list asks for. The low end if the page gives a range."},
                "price_high": {"type": ["number", "null"], "description": "The high end, if the page gives a range. Otherwise null."},
                "place": {"type": "string", "enum": [*PLACES, "United States"], "description": "Where the page says the figure is for. Los Angeles or California only if the page says so."},
                "source_title": {"type": "string"},
                "source_url": {"type": "string"},
                "quote": {"type": "string", "description": "The sentence on the page that states the price, word for word."},
            },
            "required": ["item", "price", "price_high", "place", "source_title", "source_url", "quote"],
            "additionalProperties": False,
        },
    }


def _in_sentence(row: dict) -> bool:
    """Whether the sentence that was copied gives the figures itself: both ends of the range, as numbers in it. '$2' is not in '$2.50'."""
    stated = {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", row["source"]["quote"])}
    return row["price"] in stated and (row["price_high"] is None or row["price_high"] in stated)


def check(row: dict, text: str | None) -> tuple[bool, str]:
    """The check every price here must pass: the existing one (the price and the sentence are on the page), and the sentence states the price."""
    ok, note = flood_agent.confirm(row, text)
    return (False, "the sentence is on the page but does not itself state this price") if ok and not _in_sentence(row) else (ok, note)


def _stands(row: dict, item: dict) -> bool:
    """Whether a saved row still answers an item: confirmed, and for the same words when the item is a thing somebody described."""
    return row.get("checked") is True and row.get("seen") == item.get("seen")


def research(items: list[dict], path, about: str, keyed: bool = False, client: Any = None, fetch=flood_agent.page_text, save: bool = True) -> dict:
    """Find a stated price for each item ({"id", "what", "unit"}) that has no confirmed price in `path` yet, check each against its page, and add them to the file.

    A confirmed price that is already saved is not looked up again, so a price in use does not change under the schedule.
    """
    have = {r["item"] for r in rows(path) for i in items if i["id"] == r["item"] and _stands(r, i)}
    todo = [i for i in items if i["id"] not in have]
    if not todo:
        return {"stop": "nothing to price", "seconds": 0.0, "steps": [], "usage": {"input_tokens": 0, "output_tokens": 0}, "items": [], "prices": []}
    known = {i["id"]: i for i in todo}
    prices: list[dict] = []

    def handle(name: str, args: dict, read, note) -> tuple[str, bool]:
        try:
            item, low = known[args["item"]], float(args["price"])
        except (KeyError, TypeError, ValueError):
            return "Not recorded: the item must be one on the list and the price a number.", True
        url = str(args.get("source_url") or "").strip()
        if isinstance(args.get("price"), bool) or low <= 0 or not url.startswith("http") or not str(args.get("quote") or "").strip():
            return "Not recorded: a price needs to be above zero, with a page address and the sentence that states it.", True
        high = _number(args.get("price_high"))
        row = {"item": item["id"], "price": low, "price_high": high if high and high > low else None, "unit": item["unit"], "what": item["what"],
               "source": {"title": str(args.get("source_title") or "").strip()[:160], "url": url, "quote": str(args["quote"]).strip()[:500]}}
        if "seen" in item:
            row["seen"] = item["seen"]
        text = read(url)
        row["checked"], row["check_note"] = check(row, text)
        if not row["checked"] and _in_sentence(row):      # the page as the agent's fetch read it did not bear it out: one fetch from here, and the same check
            text = fetch(url)
            again = check(row, text)
            if again[0]:
                row["checked"], row["check_note"] = again
        place = args.get("place")
        row["place"] = place if place in PLACES and row["checked"] and place.lower() in flood_agent._norm(text or "") else None      # a local figure only when the page names the place
        prices.append(row)
        note("found", f"{item['id']}: ${low:,.2f}" + (f" to ${row['price_high']:,.2f}" if row["price_high"] else "") + f" {item['unit']}", checked=row["checked"], source=url)
        return (f"Recorded. Check of the page: {row['check_note']}." if row["checked"]
                else f"Recorded, but not confirmed and so not used: {row['check_note']}. Try once more with the sentence exactly as the page has it, or another page."), False

    import anthropic
    listed = "\n".join(f"- {i['id']}: {i['what']} ({i['unit']})" for i in todo)
    run = flood_agent._loop(client or anthropic.Anthropic(), f"{SYSTEM}\n\n{about}", f"Price each of these and record it:\n{listed}", [SEARCH, FETCH, _tool(list(known))], handle, fetch)
    run = {**run, "items": todo, "prices": prices}
    if save and prices:      # a price its page confirmed is confirmed however the run ended
        _keep(path, run, keyed)
    return run


def _keep(path, run: dict, keyed: bool) -> None:
    """Add one run to what is saved. The file is read again first: the run took minutes, and another may have saved meanwhile."""
    old = _read(path)
    log = {k: run[k] for k in ("made_at", "model", "seconds", "stop", "steps", "usage") if k in run}
    if keyed:      # rows under their keys; a confirmed row is never replaced by one that is not
        out = {r["item"]: r for r in rows(path)}
        for r in run["prices"]:
            was = out.get(r["item"])
            if not was or not _stands(was, r):      # the first confirmed row for these words stays; anything else gives way to the newer record
                out[r["item"]] = r
        out["runs"] = [*(old.get("runs") or []), log]
    else:
        ids = {i["id"] for i in old.get("items") or []}
        out = {**log, "seconds": round((old.get("seconds") or 0) + run["seconds"], 1), "steps": [*(old.get("steps") or []), *run["steps"]],
               "items": [*(old.get("items") or []), *(i for i in run["items"] if i["id"] not in ids)], "prices": [*rows(path), *run["prices"]],
               "runs": (old.get("runs") or (1 if old else 0)) + 1}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))


def price_fitting(first: list[str] | None = None, **how) -> dict:
    return research(fitting_items(first), fitting_path(), ABOUT["fitting"], **how)


def price_specific(scan_id: str, **how) -> dict:
    return research(built_items(scan_id), specific_path(scan_id), ABOUT["specific"], keyed=True, **how)


def price_work(scan_id: str, **how) -> dict:
    return research(work_items(scan_id), work_path(), ABOUT["work"], **how)


# ---- the finishes, read from the scan ------------------------------------------------------------------

def _all_round(scan_id: str, sweep_id: str, side: int = 768) -> Image.Image:
    """The four views from one standpoint as a square: ahead and right above, behind and left below."""
    sheet = Image.new("RGB", (2 * side, 2 * side))
    for i, face in enumerate(matterport.SIDE_FACES):
        with Image.open(matterport.face_image(scan_id, sweep_id, face)) as im:
            sheet.paste(im.convert("RGB").resize((side, side), Image.LANCZOS), ((i % 2) * side, (i // 2) * side))
    return sheet


def pictures(property_id: int, scan_id: str) -> list[dict]:
    """One picture for each room the camera stood in: the four views from its first standpoint. A handful across the home."""
    shots = []
    for room in list(inventory_agent.InventoryRun(property_id, scan_id).rooms.values())[:MAX_PICTURES]:
        standpoint, sw = next(iter(room["standpoints"].items()))
        try:
            image = _all_round(scan_id, sw["id"])
        except (matterport.MatterportError, OSError):
            continue      # a room whose picture cannot be fetched is not read, and says nothing
        shots.append({"room": room["id"], "room_name": room["name"], "standpoint": standpoint, "sweep_id": sw["id"], "image": image})
    return shots


def _schema(room_ids: list[str]) -> dict:
    said = lambda kinds, what: {"type": "object", "properties": {"finish": {"type": "string", "enum": [*kinds, CANNOT]}, "seen": {"type": "string", "description": f"One short phrase: what you saw of the {what}."}},
                                "required": ["finish", "seen"], "additionalProperties": False}
    floor = said(FLOORS, "floor")
    return {"type": "object", "additionalProperties": False, "required": ["rooms", "door", "wall", "baseboard"],
            "properties": {"rooms": {"type": "array", "description": "One entry for each room pictured.",
                                     "items": {"type": "object", "properties": {"room": {"type": "string", "enum": room_ids}, **floor["properties"]}, "required": ["room", "finish", "seen"], "additionalProperties": False}},
                           "door": said(DOORS, "interior doors"), "wall": said([*WALLS, *OTHER_WALLS], "walls"), "baseboard": said([*BASEBOARDS, *OTHER_BASEBOARDS], "baseboard")}}


def _said(entry: Any, kinds) -> dict | None:
    """One answer as it is kept: a finish from the list with a phrase of what was seen. Anything else is no answer."""
    if not isinstance(entry, dict) or entry.get("finish") not in (*kinds, CANNOT):
        return None
    seen = " ".join(str(entry.get("seen") or "").split())[:160]
    return {"finish": entry["finish"], "seen": seen} if seen else None      # no phrase of what was seen, no finish


def settle_finishes(data: Any, shown: list[str]) -> dict:
    """What the look said, held to the lists: only rooms that were pictured, each once; only finishes on the list; a phrase with each."""
    rooms: dict[str, dict] = {}
    for entry in (data.get("rooms") if isinstance(data, dict) and isinstance(data.get("rooms"), list) else []):
        said = _said(entry, FLOORS)
        if said and entry.get("room") in shown and entry["room"] not in rooms:
            rooms[entry["room"]] = said
    get = lambda k, kinds: _said(data.get(k), kinds) if isinstance(data, dict) else None
    return {"rooms": rooms, "home": {"door": get("door", DOORS), "wall": get("wall", [*WALLS, *OTHER_WALLS]), "baseboard": get("baseboard", [*BASEBOARDS, *OTHER_BASEBOARDS])}}


def read_finishes(property_id: int, scan_id: str, client: Any = None, save: bool = True) -> dict:
    """One look at the scan: the floor of each room, and the home's doors, walls and baseboards. One model call, held to a schema and checked again here."""
    t0 = time.time()
    shots = pictures(property_id, scan_id)
    if not shots:
        raise ValueError("no picture of this scan could be fetched, so its finishes cannot be read")
    content: list[dict] = []
    for n, s in enumerate(shots, 1):
        content += [{"type": "text", "text": f"Picture {n}: the room with id {s['room']} ({s['room_name']}), four views from one standpoint: ahead and right above, behind and left below."},
                    vision.image_block(s["image"], max_side=1536)]
    content.append({"type": "text", "text": "Say what the floor of each room pictured is, and what this home's interior doors, walls and baseboards are. Use each room's id as given."})
    import anthropic
    client = client or anthropic.Anthropic()
    out = {"property_id": property_id, "scan_id": scan_id, "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": AGENT_MODEL,
           "pictures": [{k: s[k] for k in ("room", "room_name", "standpoint", "sweep_id")} for s in shots], "rooms": {}, "home": {"door": None, "wall": None, "baseboard": None}}
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        resp = client.beta.messages.create(
            model=AGENT_MODEL, max_tokens=8000, system=FINISH_SYSTEM, messages=[{"role": "user", "content": content}],
            thinking={"type": "adaptive"}, output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema([s["room"] for s in shots])}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        stop = resp.stop_reason or "end_turn"
        usage = {k: getattr(resp.usage, k, 0) or 0 for k in ("input_tokens", "output_tokens")}
        if stop != "refusal":
            out.update(settle_finishes(json.loads(next(b.text for b in resp.content if b.type == "text")), [s["room"] for s in shots]))
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        stop = f"error: {getattr(e, 'status_code', 'no connection')}"
    except (StopIteration, ValueError):
        stop = "error: the answer was not in the form asked for"
    out = {**out, "stop": stop, "seconds": round(time.time() - t0, 1), "usage": usage}
    if save and stop == "end_turn" and (out["rooms"] or any(out["home"].values())):
        finishes_path(scan_id).parent.mkdir(parents=True, exist_ok=True)
        finishes_path(scan_id).write_text(json.dumps(out, indent=1))
    return out
