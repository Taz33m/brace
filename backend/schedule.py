"""The schedule: what an owner would have to replace if fire reached a property, as a tree.

    property total
      building            its share of the homes, and how exposed it is from outside
        home              the scanned home, standing for the homes like it
          room
            item          a quantity from the scan times a price a page states

Three sources meet here. The inventory agent (`inventory_agent.py`) read the scan and named the fit-out in each room.
Matterport's own measurements (`insurer_file.py`) give the floor, wall and door quantities; the model never
measures. The price research (`flood_agent.price`) found a price range for each kind of line, kept only when its
page confirmed it. This module multiplies and adds, and nothing else: a line with no confirmed price has null
money and is left out of every total, and each total says how many of its lines were priced.

One scanned home stands for every home at the property. That is an extrapolation and is marked as one.
"""
from __future__ import annotations

import json
import math
import re

from . import flood, insurer_file, inventory_agent, matterport, openings, portfolio, product_match, tighten
from .config import CACHE_DIR

PRICES = CACHE_DIR / "inventory" / "prices.json"
M_TO_FT = 1 / 0.3048

# The building work every room needs after a fire, measured from the scan. The ids are the price list's.
WORK = {"flooring": ("Flooring", "sq ft"), "drywall": ("Drywall", "sq ft"), "paint": ("Painting", "sq ft"), "baseboard": ("Baseboard", "ft")}


class ScheduleError(Exception):
    pass


def price_list(scan_id: str) -> list[dict]:
    """Everything this home's schedule needs a price for: the measured building work, and each kind of fit-out the agent named."""
    inv = inventory_agent.saved(scan_id)
    if not inv:
        raise ScheduleError("this scan has not been read yet")
    kinds = sorted({i["kind"] for i in inv["items"]})
    return ([w for w in insurer_file.WORK if w["id"] in (*WORK, "door")]
            + [{"id": f"fit:{k}", "what": f"{inventory_agent.KINDS[k]}, apartment grade, supplied and installed", "unit": "each"} for k in kinds])


def _prices() -> dict[str, dict]:
    """The first confirmed price for each line, from the building-work run and the fit-out run."""
    by: dict[str, dict] = {}
    for path in (PRICES, insurer_file.PRICES):
        try:
            rows = json.loads(path.read_text()).get("prices") or []
        except (OSError, ValueError):
            continue
        for row in rows:
            if row.get("checked"):
                by.setdefault(row["item"], row)
    return by


def _line(price_id: str, what: str, quantity: float, unit: str, how: str, prices: dict, key: str | None = None, match: dict | None = None,
          fitting: dict | None = None, specific: dict | None = None, **more) -> dict:
    """One line: a quantity times a price for one. Which price, and what it rests on (`price_basis`), is `tighten.price_of`'s rule: a product matched to
    the item in the scan, with the labour to fit it when a page gave one; else a page's price for what was seen; else the cost guide for the kind.
    The guide's price is carried whichever is used."""
    quantity, each = round(quantity), tighten.price_of(prices.get(price_id), match, fitting, specific)
    return {"what": what, "quantity": quantity, "unit": unit, "from": how,
            "low": round(quantity * each["price_low"]) if each["price_low"] is not None else None, "high": round(quantity * each["price_high"]) if each["price_high"] is not None else None,
            "key": key, "match": match, "finish": None, **each, **more}


def _sum(lines: list[dict]) -> dict:
    priced = [l for l in lines if l["low"] is not None]
    return {"low": sum(l["low"] for l in priced) if priced else None, "high": sum(l["high"] for l in priced) if priced else None, "lines": len(lines), "lines_priced": len(priced)}


def _times(total: dict, n: int) -> dict:
    return {"low": total["low"] * n if total["low"] is not None else None, "high": total["high"] * n if total["high"] is not None else None}


def _share(weights: list[float], whole: int) -> list[int]:
    """A whole number of homes for each building in proportion to its size, adding up to the property's count."""
    if not whole or not sum(weights):
        return [0] * len(weights)
    exact = [w / sum(weights) * whole for w in weights]
    out = [math.floor(x) for x in exact]
    for i in sorted(range(len(exact)), key=lambda i: exact[i] - out[i], reverse=True)[:whole - sum(out)]:
        out[i] += 1
    return out


def _beds_baths(name: str | None) -> tuple[float | None, float | None]:
    """'2BR, 1BA - 775SF' says two bedrooms and one bathroom."""
    beds, baths = re.search(r"(\d+(?:\.\d+)?)\s*BR", name or "", re.I), re.search(r"(\d+(?:\s*1/2|\.\d+)?)\s*BA", name or "", re.I)
    return (float(beds.group(1)) if beds else None, float(baths.group(1).replace(" 1/2", ".5")) if baths else None)


def kinds_of_home(property_id: int, unit: dict, record_homes: int) -> list[dict]:
    """How one scanned home becomes a figure for the property, one row for each kind of home.

    The community's Apartments.com listing says what kinds of home there are and how many of each. The kind that matches
    the scanned home takes its figure as it stands. A kind that was not scanned takes that figure scaled by floor area,
    and says so. With no listing, every home on the property record is taken to be like the scanned one.
    """
    plans = portfolio.floor_plans(property_id)
    total = unit["total"]
    if not plans:
        return [{"name": "Every home on the record", "homes": record_homes, "per_home": {"low": total["low"], "high": total["high"]}, **_times(total, record_homes),
                 "basis": "the scanned home; the record does not say what kinds of home there are", "scanned": False, "rent_low": None, "rent_high": None}]
    beds, baths = _beds_baths(unit["name"])
    same = [p for p in plans if p["beds"] == beds and (baths is None or p["baths"] == baths)]
    like = min(same, key=lambda p: abs(((p["sqft_low"] or 0) + (p["sqft_high"] or 0)) / 2 - unit["floor_sqft"])) if same else None
    size = lambda p: ((p["sqft_low"] or 0) + (p["sqft_high"] or 0)) / 2
    base = size(like) if like and size(like) else unit["floor_sqft"]
    rows = []
    for p in plans:
        k = 1.0 if p is like else (size(p) / base if size(p) and base else 1.0)
        per = {"low": round(total["low"] * k) if total["low"] is not None else None, "high": round(total["high"] * k) if total["high"] is not None else None}
        rows.append({"name": p["name"], "homes": p["homes"], "per_home": per, **_times(per, p["homes"]), "scanned": p is like,
                     "basis": "the scanned home" if p is like else f"the scanned home's figure scaled by floor area ({size(p):,.0f} sq ft against {base:,.0f}); no home of this kind was scanned",
                     "rent_low": p["rent_low"], "rent_high": p["rent_high"]})
    return rows


def home(property_id: int, scan_id: str) -> dict:
    """One scanned home as rooms and lines: the fit-out the agent read, and the building work its measurements call for."""
    inv = inventory_agent.saved(scan_id)
    if not inv:
        raise ScheduleError("this scan has not been read yet")
    try:
        measured = insurer_file.inside(property_id, scan_id)
        bundle = json.loads((flood.BUILDINGS / str(property_id) / "building.json").read_text())
        scan = next(s for s in bundle["scans"] if s["id"] == scan_id)
        plan = openings.layout(scan, json.loads((matterport.MP_CACHE / "openings" / f"{scan_id}.json").read_text()))
    except (insurer_file.FileError, OSError, StopIteration):
        raise ScheduleError("this scan's rooms have not been measured")
    prices = _prices()
    matches = product_match.saved(scan_id)      # a product matched to one item in the scan, under '<room_id>:<kind>'
    tight = tighten.Tight(scan_id)              # confirmed prices for fitting a product, for built work as it was seen, and for the finishes read from the scan
    walls = {r["id"]: sum(math.dist(a, b) for a, b in r["walls"]) * M_TO_FT for r in plan["rooms"]}
    net = measured["wall_less_doorways_ft"] / measured["wall_ft"] if measured["wall_ft"] else 1.0      # doorways come out of every room alike
    names = inventory_agent.InventoryRun(property_id, scan_id).rooms       # the agent's room ids against Matterport's
    read_as = {r["matterport_id"]: rid for rid, r in names.items()}
    headings = {sw["id"]: sw.get("heading") for sw in scan.get("sweeps") or []}      # which way the camera faced at each standpoint, to turn a picture the right way
    by_room: dict[str, list[dict]] = {}
    for i in inv["items"]:
        by_room.setdefault(i["room"], []).append({**i, "at": {**i["at"], "heading_deg": headings.get(i["at"]["sweep_id"])}})

    # What the agent decided beyond its list: what it would not record, what it left out and why, and what it is still unsure of.
    doubts: dict[str, list[dict]] = {}
    for d in inv.get("doubts") or []:
        doubts.setdefault(d["room"], []).append({"id": d["id"], "about": inventory_agent.KINDS.get(d.get("kind") or "", None), "doubt": d["doubt"]})
    left: dict[str, list[dict]] = {}
    for k in inv.get("skipped") or []:
        left.setdefault(k["room"], []).append({"saw": k["saw"], "why": k["why"]})
    # Refusals are not shown as things left out: most are a reader trying a name the list does not use and then finding the right one.

    rooms, count = [], {}
    for r in scan.get("rooms") or []:
        kind = r.get("type") or ""
        if kind in ("", "Void", "Patio") or not r.get("height_m") or not r.get("area_sqft"):
            continue
        count[kind] = count.get(kind, 0) + 1
        ceiling, wall = r["height_m"] * M_TO_FT, walls.get(r["id"], 0.0) * net
        lines = [_line(f"fit:{i['kind']}", inventory_agent.KINDS.get(i["kind"], i["what"]), i["quantity"], "each", "read from the scan", prices, seen=i["seen"], at=i["at"],
                       key=product_match.key_of(i["room"], i["kind"]), match=product_match.for_schedule(matches.get(product_match.key_of(i["room"], i["kind"]))), **tight.fit(i))
                 for i in by_room.get(read_as.get(r["id"], ""), [])]
        lines += [_line("flooring", "Flooring", r["area_sqft"], "sq ft", "measured from the scan", prices, seen=None, at=None, **tight.built("flooring", read_as.get(r["id"]))),
                  _line("drywall", "Drywall", wall * ceiling, "sq ft", "measured from the scan", prices, seen=None, at=None, **tight.built("drywall")),
                  _line("paint", "Painting", wall * ceiling, "sq ft", "measured from the scan", prices, seen=None, at=None, **tight.built("paint")),
                  _line("baseboard", "Baseboard", wall, "ft", "measured from the scan", prices, seen=None, at=None, **tight.built("baseboard"))]
        rooms.append({"name": kind if sum(1 for x in scan["rooms"] if x.get("type") == kind and x.get("area_sqft") and x.get("height_m")) == 1 else f"{kind} {count[kind]}",
                      "area_sqft": r["area_sqft"], "read": r["id"] in read_as, "room_id": read_as.get(r["id"]), "items": lines, "total": _sum(lines),
                      "doubts": doubts.get(read_as.get(r["id"], ""), []), "left_out": left.get(read_as.get(r["id"], ""), [])})
    doors = [_line("door", "Interior doors", measured["inner_doors"], "each", "measured from the scan", prices, seen=None, at=None, **tight.built("door"))]
    rooms.append({"name": "Throughout the home", "area_sqft": None, "read": True, "room_id": None, "items": doors, "total": _sum(doors), "doubts": [], "left_out": []})
    every = [l for room in rooms for l in room["items"]]
    return {"scan_id": scan_id, "name": measured["name"], "under_roof": measured["under_roof"], "scan_date": measured["model_made"], "floor_sqft": measured["floor_sqft"],
            "rooms": rooms, "total": _sum(every), "numbers": inv["numbers"], "statement": inv.get("statement"), "seconds": inv.get("seconds"),
            "decisions": {"left_out": sum(len(v) for v in left.values()), "merged": len(inv.get("merged_away") or []), "doubts": sum(len(v) for v in doubts.values())},
            "rechecks": [{k: c.get(k) for k in ("room", "room_name", "at", "seconds", "changed", "statement")} for c in inv.get("rechecks") or []]}


def schedule(property_id: int, scan_id: str | None = None) -> dict:
    """The whole property: one scanned home, the homes like it, each building's share, and the rent lost while they are empty."""
    try:
        s = flood.site(property_id)
        bundle = json.loads((flood.BUILDINGS / str(property_id) / "building.json").read_text())
    except (flood.FloodError, OSError):
        raise ScheduleError("this property has not been gathered")
    scan_id = scan_id or next((sc["id"] for sc in bundle.get("scans") or [] if inventory_agent.saved(sc["id"])), None)
    if not scan_id:
        raise ScheduleError("no scan at this property has been read yet")
    unit = home(property_id, scan_id)
    record_homes = s["homes"] or 0
    kinds = kinds_of_home(property_id, unit, record_homes)
    homes = sum(k["homes"] for k in kinds)
    priced = [k for k in kinds if k["low"] is not None]
    total = {"low": sum(k["low"] for k in priced) if priced else None, "high": sum(k["high"] for k in priced) if priced else None}
    each = {"low": total["low"] / homes if total["low"] is not None and homes else None, "high": total["high"] / homes if total["high"] is not None and homes else None}
    sizes = {st["id"]: st.get("footprint_sqft") or 0 for st in bundle["structures"]}
    rows = sorted(s["buildings"], key=lambda b: -(b.get("trees_within_5ft_percent") or 0))
    shares = dict(zip([b["id"] for b in rows], _share([sizes.get(b["id"], 0) for b in rows], homes)))
    buildings = []
    for rank, b in enumerate(rows, 1):
        n = shares[b["id"]]
        buildings.append({"id": b["id"], "exposure_rank": rank, "brush_within_5ft_percent": b.get("trees_within_5ft_percent"), "in_fire_zone": None, "homes_assumed": n,
                          "polygon": b["polygon"], "total": {"low": round(each["low"] * n) if each["low"] is not None else None, "high": round(each["high"] * n) if each["high"] is not None else None},
                          "units": [{**unit, "multiplied_by": next((k["homes"] for k in kinds if k["scanned"]), n), "extrapolated": True}] if b["id"] == unit["under_roof"] else []})
    rented = [k for k in kinds if k["rent_low"] and k["rent_high"]]
    try:
        price_run = json.loads(PRICES.read_text())
    except (OSError, ValueError):
        price_run = {}
    used = {l["what"] for room in unit["rooms"] for l in room["items"] if l["low"] is not None}
    confirmed = len(used)      # the kinds of line on this schedule that carry a confirmed price
    seconds = (unit.get("seconds") or 0) + (price_run.get("seconds") or 0)
    listed = bool(portfolio.floor_plans(property_id))
    return {
        "property": {"id": property_id, "name": s["name"], "address": s["address"], "homes": homes, "homes_on_record": record_homes, "scenario": "fire reaches the community",
                     "scan_date": unit["scan_date"], "bounds": s["bounds"], "aerial": s["aerial"]},
        "total": {**total, "lines": unit["total"]["lines"], "lines_priced": unit["total"]["lines_priced"]},
        "home": {"name": unit["name"], "total": unit["total"], "multiplied_by": homes},
        "kinds_of_home": kinds,
        "lost_rent_per_month": ({"low": round(sum(k["rent_low"] * k["homes"] for k in rented)), "high": round(sum(k["rent_high"] * k["homes"] for k in rented)),
                                 "how": "; ".join(f"{k['homes']} x ${k['rent_low']:,.0f}" + (f" to ${k['rent_high']:,.0f}" if k["rent_high"] != k["rent_low"] else "") for k in rented) + " a month, asking rents"}
                                if rented else None),
        "numbers": {"scans_read": 1, "rooms_read": unit["numbers"]["rooms_read"], "views_looked_at": unit["numbers"]["views_looked_at"], "items_named": unit["numbers"]["items_named"],
                    "prices_confirmed": confirmed, "minutes": round(seconds / 60, 1) if seconds else None, "model_cost_usd": None},
        "buildings": buildings,
        "assumptions": [
            "The scenario is stated, not forecast: fire reaches the community and the fit-out of its homes is a total loss.",
            (f"The kinds of home and how many of each are from the community's Apartments.com listing: {homes:,} homes. The kind that was scanned takes the scanned home's figure; a kind that was not is scaled by floor area. Both are extrapolations."
             + (f" CoStar's property record gives {record_homes:,}; the schedule counts only the homes the listing describes." if record_homes and record_homes != homes else "")
             if listed else f"The record does not say what kinds of home there are, so all {homes:,} are taken to be like the scanned one. That is an extrapolation."),
            "Homes are shared among the buildings by roof area, because no source gives a count for each building.",
            "Rent is the listing's asking rent for each kind of home, not a lease.",
            "Fit-out was named and counted by an agent looking at the scan's own pictures. Each line says where it was seen.",
            "Floor, wall and door quantities are Matterport's measurements of the scan. Doorways are taken out of the walls. Ceilings are not counted.",
            "A line is priced only when a fetch of the page confirmed the price. Where a page gives a range, both ends are carried through.",
            "Where a product was matched to an item in the scan by its appearance, the line is that product's listed price plus a page's labour-only price to fit one of that kind, low with low and high with high. A matched line with no confirmed fitting price says so and leaves out delivery and fitting.",
            "Where a line says it is priced for what was seen, the price is a page's for that thing as the scan showed it (the tub as the reader described it, the floor finish read from the pictures), not for the kind in general. It can be wider than the general price. Each line says which it rests on.",
            "Buildings are ranked by the share of their walls with vegetation within 5 ft, from Vexcel. It is a ranking, not a chance of fire.",
        ],
        "not_counted": ["Furniture and anything a tenant owns", "The structure itself: frame, roof, wiring, plumbing", "Ceilings", "Common areas and anything outside the homes"],
    }
