"""A likely make and model for one item of the inventory, with a tighter price. A prototype.

The schedule prices a refrigerator as a kind: whatever a cost guide says refrigerators cost. This module looks at the
one in the scan. A model is shown the picture the inventory agent recorded the item in, says what is visible, and
searches for products sold today that look like it. What it reports is then checked here, and the rules are in code:

* a product is kept only if a fetch of its page holds the price it reported (`flood_agent.confirm`), and the model
  number when it gave one; a product whose page does not bear it out is dropped and listed as dropped;
* the range is the lowest to the highest price of the kept products, and nothing else;
* no kept product means no match: the line keeps its cost-guide price;
* the label is "Brand read from the scan" only when the model says it read a brand in the picture and a kept product
  is of that brand. Otherwise it is "Closest match". It is never an identification;
* unknown is null. Nothing is guessed here.

Matches are saved beside the inventory, keyed by room and kind, so they outlive a second read of the room.
Run one with `python -m scripts.match <property> <scan> <room_id> <kind>`.
"""
from __future__ import annotations

import io
import json
import math
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from . import flood_agent, inventory_agent, matterport, vision

MAX_KEPT = 3            # products kept for one item
MAX_REPORTS = 8         # products the model may report in one run, kept or not
SPAN = 0.8              # the close-up is this share of a panorama face, each way
SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
FETCH = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 14}

BRAND_READ, CLOSEST = "Brand read from the scan", "Closest match"

SYSTEM = """You look at one piece of fit-out in a scanned rental apartment and find the products it most likely is, so its owner can be told what a like replacement sells for. You are given pictures from the scan Matterport made of the home and told which thing to look at.

How to work
1. Look at the pictures. Call note_what_is_visible once with what you can actually see of the thing: any brand name or badge you can read, the door, drawer or burner layout, the finish and colour, the handle style, where the controls are, and the size class.
2. Search retailer and manufacturer pages for products sold new today that match those details. If you read a brand, look at that brand first.
3. Open a product's page with web_fetch. As soon as a fetched page shows the product's price, report it with report_product, then go on to the next. Report up to three products, the closest first if you can.

Rules
- Give brand_read only if you can read the name or make out the badge in a picture. Do not infer a brand from styling. If you cannot read one, brand_read is null.
- A product is kept only if its price, and its model number, are found on its page as fetched. If you are told a product was not kept, try another page that states the price of the same product (the maker's own page, another retailer), or report another product.
- Many large retailers draw the price with a script, so their fetched pages show none. When a fetched page shows no price for the product, do not spend more fetches on that retailer: open the maker's own page for that model, or a smaller appliance dealer's, and report from a page that does show it.
- Reporting is the only way a product counts; one you only mention in your last line is lost. If you have opened six pages and reported nothing, report the closest product you have from the page most likely to state its price, so that it can be checked.
- Report the price of one unit as the page states it now, and copy the price as the page prints it into price_text. Do not work out a price, do not average, and do not add delivery or fitting.
- Match what is visible. This is apartment-grade fit-out unless the pictures show otherwise; do not pick a dearer or a cheaper product than the pictures support.
- A picture cannot tell you the exact product. In why, say which visible details the product shares, and nothing more.
- Stop when three products are kept or you have searched eight times. Finish with one line saying how many were kept and, if none was, why."""

NOTE_TOOL = {
    "name": "note_what_is_visible",
    "description": "Say what you can see of the thing in the pictures, before you search. Call it once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "seen": {"type": "array", "items": {"type": "string"}, "description": "Up to eight short phrases, one visible detail each. For example: stainless finish, top freezer, pocket handles."},
            "brand_read": {"type": ["string", "null"], "description": "The brand name you can read in a picture, or whose badge you can make out. Null if you cannot read one."},
            "brand_where": {"type": ["string", "null"], "description": "Where on the thing the name or badge is, in a few words. Null if brand_read is null."},
        },
        "required": ["seen", "brand_read", "brand_where"],
        "additionalProperties": False,
    },
}
REPORT_TOOL = {
    "name": "report_product",
    "description": "Report one product sold new today that matches what is visible, from a page you opened with web_fetch. Call once for each product, the closest first.",
    "input_schema": {
        "type": "object",
        "properties": {
            "make": {"type": "string", "description": "The brand."},
            "model": {"type": ["string", "null"], "description": "The model number as the page gives it. Null if the page gives none."},
            "name": {"type": "string", "description": "The product's name as the page gives it, shortened to a line."},
            "price": {"type": "number", "description": "The price of one, in US dollars, as the page states it now."},
            "price_text": {"type": "string", "description": "The price exactly as the fetched page prints it, a few characters, for example $698.00."},
            "url": {"type": "string", "description": "The address of the product's page."},
            "why": {"type": "string", "description": "One line: the visible details this product shares with the thing in the pictures."},
        },
        "required": ["make", "model", "name", "price", "price_text", "url", "why"],
        "additionalProperties": False,
    },
}


# ---- where matches are kept ------------------------------------------------------------------------

def _path(scan_id: str):
    return inventory_agent.OUT / f"{scan_id}.matches.json"


def saved(scan_id: str) -> dict:
    """The matches saved for one scan, each under '<room_id>:<kind>'. Empty when there are none."""
    try:
        data = json.loads(_path(scan_id).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def key_of(room_id: str, kind: str) -> str:
    return f"{room_id}:{kind}"


def for_schedule(entry: dict | None) -> dict | None:
    """A match as a schedule line carries it: without what the run used and said."""
    return {k: v for k, v in entry.items() if k not in ("usage", "statement", "steps", "said")} if entry and entry.get("candidates") else None


# ---- the pictures of one item ------------------------------------------------------------------------

def _item(property_id: int, scan_id: str, room_id: str, kind: str) -> tuple[dict, dict]:
    """The record of one kind in one room of the saved inventory, and the room as the scan has it."""
    room_id, kind = str(room_id).strip(), str(kind).strip()
    inv = inventory_agent.saved(scan_id)
    if not inv:
        raise ValueError("this scan has not been read yet, so there is nothing to match")
    if kind not in inventory_agent.KINDS:
        raise ValueError(f"'{kind}' is not a kind of fit-out the inventory records")
    item = next((i for i in inv.get("items") or [] if i.get("room") == room_id and i.get("kind") == kind), None)
    if not item:
        raise ValueError(f"no {kind} is recorded in that room")
    room = inventory_agent.InventoryRun(property_id, scan_id, only=[room_id]).rooms.get(room_id)
    if not room:
        raise ValueError("the camera did not stand in that room, so there is no picture of it")
    return item, room


def _place(item: dict, room: dict) -> tuple[dict, float, float] | None:
    """The standpoint an item was recorded from and where it is in that picture, each from 0 to 1.

    The inventory keeps a turn and a tilt; this undoes `record_item`'s arithmetic to get back the place in the picture.
    """
    at = item.get("at") or {}
    sw = next((s for s in room["standpoints"].values() if s["id"] == at.get("sweep_id")), None)
    side = inventory_agent.SIDES.get(at.get("direction"))
    if not sw or not side or at.get("yaw_deg") is None or at.get("pitch_deg") is None:
        return None
    off = (at["yaw_deg"] - (sw.get("heading") or 0) - 90 * (side - 1) + 180) % 360 - 180      # degrees from the centre of that face
    if abs(off) > 46:
        return None
    dx = math.tan(math.radians(max(-45.0, min(45.0, off))))
    dy = math.tan(math.radians(at["pitch_deg"])) * math.hypot(1, dx)
    return sw, min(1.0, max(0.0, (dx + 1) / 2)), min(1.0, max(0.0, (1 - dy) / 2))


def _face(scan_id: str, sweep_id: str, side: int) -> Image.Image:
    with Image.open(matterport.face_image(scan_id, sweep_id, side)) as im:
        return im.convert("RGB")


def _close_up(scan_id: str, sweep_id: str, side: int, across: float, down: float) -> Image.Image:
    """The part of the picture round the item. Near the picture's edge, the next picture round is joined on, so a thing cut by the edge is whole."""
    face = _face(scan_id, sweep_id, side)
    n = face.width
    sheet, x = face, across
    try:
        if across > 0.7:
            other = _face(scan_id, sweep_id, side % 4 + 1).resize((n, n))
            sheet = Image.new("RGB", (2 * n, n)); sheet.paste(face, (0, 0)); sheet.paste(other, (n, 0))
        elif across < 0.3:
            other = _face(scan_id, sweep_id, (side - 2) % 4 + 1).resize((n, n))
            sheet = Image.new("RGB", (2 * n, n)); sheet.paste(other, (0, 0)); sheet.paste(face, (n, 0))
            x = across + 1
    except (matterport.MatterportError, OSError):
        sheet, x = face, across      # the neighbouring picture is not to hand: stay inside this one
    w = h = round(SPAN * n)
    left = round(min(max(x * n - w / 2, 0), sheet.width - w))
    top = round(min(max(down * n - h / 2, 0), sheet.height - h))
    return sheet.crop((left, top, left + w, top + h))


def _all_round(scan_id: str, sweep_id: str, side: int = 640) -> Image.Image:
    """The four views from one standpoint as a square: ahead and right above, behind and left below."""
    sheet = Image.new("RGB", (2 * side, 2 * side))
    for i, face in enumerate(matterport.SIDE_FACES):
        sheet.paste(_face(scan_id, sweep_id, face).resize((side, side), Image.LANCZOS), ((i % 2) * side, (i // 2) * side))
    return sheet


def pictures(property_id: int, scan_id: str, room_id: str, kind: str) -> dict:
    """What the model is shown of one item: the view it was recorded in, a close-up round it, and the room from one other standpoint."""
    item, room = _item(property_id, scan_id, room_id, kind)
    placed = _place(item, room)
    if not placed:
        raise ValueError("the inventory does not say where that item was seen")
    sw, across, down = placed
    side = inventory_agent.SIDES[item["at"]["direction"]]
    try:
        shots = [{"what": "the view the item was recorded in", "image": _face(scan_id, sw["id"], side)},
                 {"what": "a close-up of the same view, with the item at its centre", "image": _close_up(scan_id, sw["id"], side, across, down)}]
    except (matterport.MatterportError, OSError):
        raise ValueError("the picture of that item could not be fetched")
    others = [s for s in room["standpoints"].values() if s["id"] != sw["id"]]
    if others:      # one more look at the room, from the standpoint nearest the one the item was recorded from
        pos = lambda s: s.get("model_position") if isinstance(s.get("model_position"), (list, tuple)) else None
        near = min(others, key=lambda s: math.dist(pos(s)[:2], pos(sw)[:2]) if pos(s) and pos(sw) else 0.0)
        try:
            shots.append({"what": "the same room from another standpoint, four views: ahead and right above, behind and left below. The item may be in one of them", "image": _all_round(scan_id, near["id"])})
        except (matterport.MatterportError, OSError):
            pass
    return {"item": item, "room": room, "across": round(across, 2), "down": round(down, 2), "shots": shots}


def view_jpeg(property_id: int, scan_id: str, room_id: str, kind: str, max_side: int = 1024) -> bytes:
    """The recorded view of one item, cut round where it sits, as a JPEG."""
    item, room = _item(property_id, scan_id, room_id, kind)
    placed = _place(item, room)
    if not placed:
        raise ValueError("the inventory does not say where that item was seen")
    sw, across, down = placed
    try:
        im = _close_up(scan_id, sw["id"], inventory_agent.SIDES[item["at"]["direction"]], across, down)
    except (matterport.MatterportError, OSError):
        raise ValueError("the picture of that item could not be fetched")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


# ---- the rules ---------------------------------------------------------------------------------------

def _words(text: Any) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def same_brand(read: str | None, make: str | None) -> bool:
    """Whether a make is the brand that was read: the same words, or one name beginning with the whole of the other ('GE' and 'GE Appliances')."""
    a, b = _words(read), _words(make)
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return bool(short) and long[:len(short)] == short


def _on_page(model: str, text: str | None) -> bool:
    squash = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return bool(squash(model)) and squash(model) in squash(text)


def _store(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def check(product: dict, text: str | None) -> tuple[bool, str]:
    """Whether a page bears a reported product out: the price as reported, and the model number when one was given."""
    ok, note = flood_agent.confirm({"price": product["price"], "price_high": None, "source": {"quote": product["price_text"]}}, text)
    if not ok:
        return False, note.replace("the sentence is not", "not as it was copied")
    if product["model"] and not _on_page(product["model"], text):
        return False, "the price is on the page but the model number is not"
    return True, "the price and the model number are on the page" if product["model"] else "the price is on the page"


def _clean(args: dict) -> dict | None:
    try:
        price = float(args["price"])
    except (KeyError, TypeError, ValueError):
        return None
    text = lambda k, n: " ".join(str(args.get(k) or "").split())[:n]
    if isinstance(args.get("price"), bool) or not (price > 0) or not text("make", 60) or not text("name", 160) or not text("price_text", 80) or not str(args.get("url") or "").strip().startswith("http"):
        return None
    url = str(args["url"]).strip()
    return {"make": text("make", 60), "model": text("model", 60) or None, "name": text("name", 160), "price": price, "url": url, "store": _store(url),
            "why": text("why", 240), "price_text": text("price_text", 80)}


def _money(low: float, high: float) -> str:
    f = lambda v: f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"
    return f(low) if low == high else f"{f(low)} to {f(high)}"


def settle(key: str, room_id: str, kind: str, room_name: str, seen: list[str], brand_read: str | None, reported: list[dict], run: dict) -> dict:
    """The entry for one item from what the model noted and what the pages bore out. Every rule about a match is here."""
    kept = [c for c in reported if c["checked"]]
    if brand_read:      # products of the brand that was read come first, in the order they were reported
        kept = [c for c in kept if same_brand(brand_read, c["make"])] + [c for c in kept if not same_brand(brand_read, c["make"])]
    kept = kept[:MAX_KEPT]
    dropped = [{k: c[k] for k in ("make", "model", "name", "price", "url", "store")} | {"why_dropped": c["check_note"]} for c in reported if not c["checked"]]
    best = kept[0] if kept else None
    label = (BRAND_READ if brand_read and same_brand(brand_read, best["make"]) else CLOSEST) if best else None
    low, high = (min(c["price"] for c in kept), max(c["price"] for c in kept)) if kept else (None, None)
    what = inventory_agent.KINDS[kind].lower()
    left = f" {len(dropped)} more {'was' if len(dropped) == 1 else 'were'} left out because the page did not bear out the price." if dropped else ""
    if best:
        named = " ".join(x for x in (best["make"], best["model"]) if x)
        statement = (f"{label}: {named}. {len(kept)} product{'' if len(kept) == 1 else 's'} kept at {_money(low, high)} each, the price found on each one's page.{left} "
                     + ("The brand name was read in the scan; the model is the closest by appearance, not an identification." if label == BRAND_READ
                        else "This is the closest match by appearance, not an identification."))
    else:
        why = ("the look did not finish" if run["stop"].startswith("error") or run["stop"] == "refusal" else
               "no product's page bore out its price" if dropped else "no product was reported")
        statement = f"No product could be confirmed for the {what} in {room_name}: {why}. The line keeps its cost-guide price."
    steps = run.get("steps") or []
    return {"key": key, "room_id": room_id, "kind": kind, "label": label,
            "make": best["make"] if best else None, "model": best["model"] if best else None, "name": best["name"] if best else None,
            "low": low, "high": high,
            "candidates": [{k: c[k] for k in ("make", "model", "name", "price", "url", "store", "why")} for c in kept],
            "seen": seen, "brand_read": brand_read, "dropped": dropped, "stop": run["stop"], "steps": steps, "said": run.get("said"),
            "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": run["seconds"],
            "usage": {**run["usage"], "searches": sum(1 for s in steps if s["kind"] == "search"), "pages_read": sum(1 for s in steps if s["kind"] == "read")},
            "statement": statement}


# ---- the run -----------------------------------------------------------------------------------------

class _Listening:
    """The client the run is given, which also keeps the model's own words, so a run that kept nothing can say why."""

    def __init__(self, client: Any):
        self._client, self.said = client, []
        self.beta = self.messages = self

    def create(self, **kw):
        resp = self._client.beta.messages.create(**kw)
        self.said += [b.text.strip() for b in resp.content if getattr(b, "type", "") == "text" and (getattr(b, "text", "") or "").strip()]
        return resp


def match(property_id: int, scan_id: str, room_id: str, kind: str, save: bool = True, client: Any = None, fetch=flood_agent.page_text) -> dict:
    """Look at one item in the scan and find the products it most likely is, each with a price its page bears out.

    Returns the entry. When no product was kept its label, make, low and high are null and it is not saved: whatever
    was saved for the item before is left as it was. Raises ValueError, in a plain sentence, when there is no such item.
    """
    t0 = time.time()
    room_id, kind = str(room_id).strip(), str(kind).strip()
    shown = pictures(property_id, scan_id, room_id, kind)
    item, room = shown["item"], shown["room"]
    noted: dict = {"seen": [], "brand_read": None, "done": False}
    reported: list[dict] = []

    def handle(name: str, args: dict, read, note) -> tuple[str, bool]:
        if name == "note_what_is_visible":
            noted["seen"] = [" ".join(str(s).split())[:80] for s in (args.get("seen") or []) if str(s).strip()][:8] if isinstance(args.get("seen"), list) else []
            brand = " ".join(str(args.get("brand_read") or "").split())[:60]
            noted["brand_read"], noted["done"] = (brand or None), True
            note("seen", "; ".join(noted["seen"]), brand_read=noted["brand_read"])
            return "Noted. Now search for products that match, and report up to three.", False
        if name != "report_product":
            return "No such tool.", True
        if not noted["done"]:
            return "Not taken: call note_what_is_visible first, with what you can see in the pictures.", True
        if sum(1 for c in reported if c["checked"]) >= MAX_KEPT:
            return f"Not taken: {MAX_KEPT} products are already kept. Stop here.", True
        if len(reported) >= MAX_REPORTS:
            return f"Not taken: {MAX_REPORTS} products have been reported. Stop here.", True
        product = _clean(args)
        if product is None:
            return "Not taken: a product needs a make, a name, a price above zero, the price as the page prints it, and the page's address.", True
        if any(flood_agent._url_key(c["url"]) == flood_agent._url_key(product["url"]) and c["checked"] for c in reported):
            return "Not taken: that page is already kept. Report a different product.", True
        product["checked"], product["check_note"] = check(product, read(product["url"]))
        if not product["checked"]:      # the page as the model's fetch read it did not bear it out: one fetch from here, and the same check
            again = check(product, fetch(product["url"]))
            if again[0]:
                product["checked"], product["check_note"] = again
        reported.append(product)
        note("found", f"{product['make']} {product['model'] or product['name']}: ${product['price']:,.2f}", checked=product["checked"], source=product["url"])
        if product["checked"]:
            return f"Kept: {product['check_note']}.", False
        return f"Not kept: {product['check_note']}. Try another page that states this product's price, or another product.", False

    what = inventory_agent.KINDS[kind]
    content: list[dict] = []
    for n, shot in enumerate(shown["shots"], 1):
        content += [{"type": "text", "text": f"Picture {n}: {shot['what']}."}, vision.image_block(shot["image"], max_side=1568 if n == 2 else 1024)]
    more = f" There are {item['quantity']} of them in the room; find the product for one." if item.get("quantity", 1) > 1 else ""
    content.append({"type": "text", "text": f"The thing to look at: the {what.lower()} in the {room['name'].lower()}. Whoever recorded it wrote: \"{item.get('seen') or what}\". "
                                            f"In picture 1 it is {round(shown['across'] * 100)}% of the way across and {round(shown['down'] * 100)}% of the way down; picture 2 is cut round that place.{more} "
                                            "Say what is visible, then find up to three products it most likely is, each with its price."})
    import anthropic
    ears = _Listening(client or anthropic.Anthropic())
    run = flood_agent._loop(ears, SYSTEM, content, [SEARCH, FETCH, NOTE_TOOL, REPORT_TOOL], handle, fetch)
    run = {**run, "seconds": round(time.time() - t0, 1), "said": ears.said[-1][:800] if ears.said else None}
    entry = settle(key_of(room_id, kind), room_id, kind, room["name"], noted["seen"], noted["brand_read"], reported, run)
    if save and entry["candidates"]:
        kept = saved(scan_id)      # read again: the look took a while, and another item may have been matched meanwhile
        kept[entry["key"]] = entry
        _path(scan_id).parent.mkdir(parents=True, exist_ok=True)
        _path(scan_id).write_text(json.dumps(kept, indent=1))
    return entry
