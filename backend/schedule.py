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

from . import flood, insurer_file, inventory_agent, matterport, openings, portfolio
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


def _line(price_id: str, what: str, quantity: float, unit: str, how: str, prices: dict, **more) -> dict:
    row, quantity = prices.get(price_id), round(quantity)
    low = round(quantity * row["price"]) if row else None
    high = round(quantity * (row.get("price_high") or row["price"])) if row else None
    return {"what": what, "quantity": quantity, "unit": unit, "from": how, "price_low": row["price"] if row else None, "price_high": (row.get("price_high") or row["price"]) if row else None,
            "low": low, "high": high, "source_url": row["source"]["url"] if row else None, "source_title": row["source"]["title"] if row else None, **more}


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
    walls = {r["id"]: sum(math.dist(a, b) for a, b in r["walls"]) * M_TO_FT for r in plan["rooms"]}
    net = measured["wall_less_doorways_ft"] / measured["wall_ft"] if measured["wall_ft"] else 1.0      # doorways come out of every room alike
    names = inventory_agent.InventoryRun(property_id, scan_id).rooms       # the agent's room ids against Matterport's
    read_as = {r["matterport_id"]: rid for rid, r in names.items()}
    by_room: dict[str, list[dict]] = {}
    for i in inv["items"]:
        by_room.setdefault(i["room"], []).append(i)

    rooms, count = [], {}
    for r in scan.get("rooms") or []:
        kind = r.get("type") or ""
        if kind in ("", "Void", "Patio") or not r.get("height_m") or not r.get("area_sqft"):
            continue
        count[kind] = count.get(kind, 0) + 1
        ceiling, wall = r["height_m"] * M_TO_FT, walls.get(r["id"], 0.0) * net
        lines = [_line(f"fit:{i['kind']}", inventory_agent.KINDS.get(i["kind"], i["what"]), i["quantity"], "each", "read from the scan", prices, seen=i["seen"], at=i["at"])
                 for i in by_room.get(read_as.get(r["id"], ""), [])]
        lines += [_line("flooring", "Flooring", r["area_sqft"], "sq ft", "measured from the scan", prices, seen=None, at=None),
                  _line("drywall", "Drywall", wall * ceiling, "sq ft", "measured from the scan", prices, seen=None, at=None),
                  _line("paint", "Painting", wall * ceiling, "sq ft", "measured from the scan", prices, seen=None, at=None),
                  _line("baseboard", "Baseboard", wall, "ft", "measured from the scan", prices, seen=None, at=None)]
        rooms.append({"name": kind if sum(1 for x in scan["rooms"] if x.get("type") == kind and x.get("area_sqft") and x.get("height_m")) == 1 else f"{kind} {count[kind]}",
                      "area_sqft": r["area_sqft"], "read": r["id"] in read_as, "items": lines, "total": _sum(lines)})
    doors = [_line("door", "Interior doors", measured["inner_doors"], "each", "measured from the scan", prices, seen=None, at=None)]
    rooms.append({"name": "Throughout the home", "area_sqft": None, "read": True, "items": doors, "total": _sum(doors)})
    every = [l for room in rooms for l in room["items"]]
    return {"scan_id": scan_id, "name": measured["name"], "under_roof": measured["under_roof"], "scan_date": measured["model_made"], "floor_sqft": measured["floor_sqft"],
            "rooms": rooms, "total": _sum(every), "numbers": inv["numbers"], "statement": inv.get("statement"), "seconds": inv.get("seconds")}


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
    homes = s["homes"] or 0
    sizes = {st["id"]: st.get("footprint_sqft") or 0 for st in bundle["structures"]}
    rows = sorted(s["buildings"], key=lambda b: -(b.get("trees_within_5ft_percent") or 0))
    shares = dict(zip([b["id"] for b in rows], _share([sizes.get(b["id"], 0) for b in rows], homes)))
    buildings = []
    for rank, b in enumerate(rows, 1):
        n = shares[b["id"]]
        buildings.append({"id": b["id"], "exposure_rank": rank, "brush_within_5ft_percent": b.get("trees_within_5ft_percent"), "in_fire_zone": None, "homes_assumed": n,
                          "polygon": b["polygon"], "total": _times(unit["total"], n),
                          "units": [{**unit, "multiplied_by": n, "extrapolated": True}] if b["id"] == unit["under_roof"] else []})
    try:
        rent = portfolio.rent(property_id)
    except (KeyError, ValueError):
        rent = None
    try:
        price_run = json.loads(PRICES.read_text())
    except (OSError, ValueError):
        price_run = {}
    used = {l["source_url"] and (l["what"] if l["from"].startswith("read") else l["what"]) for room in unit["rooms"] for l in room["items"] if l["low"] is not None}
    confirmed = len(used)      # the kinds of line on this schedule that carry a confirmed price
    seconds = (unit.get("seconds") or 0) + (price_run.get("seconds") or 0)
    return {
        "property": {"id": property_id, "name": s["name"], "address": s["address"], "homes": homes, "scenario": "fire reaches the building", "scan_date": unit["scan_date"],
                     "bounds": s["bounds"], "aerial": s["aerial"]},
        "total": {**_times(unit["total"], homes), "lines": unit["total"]["lines"], "lines_priced": unit["total"]["lines_priced"]},
        "home": {"name": unit["name"], "total": unit["total"], "multiplied_by": homes},
        "lost_rent_per_month": ({"low": round(rent["low"] * homes), "high": round(rent["high"] * homes), "how": f"{homes:,} homes x the asking rent, ${rent['low']:,.0f} to ${rent['high']:,.0f} a month"}
                                if rent and homes else None),
        "numbers": {"scans_read": 1, "rooms_read": unit["numbers"]["rooms_read"], "views_looked_at": unit["numbers"]["views_looked_at"], "items_named": unit["numbers"]["items_named"],
                    "prices_confirmed": confirmed, "minutes": round(seconds / 60, 1) if seconds else None, "model_cost_usd": None},
        "buildings": buildings,
        "assumptions": [
            "The scenario is stated, not forecast: fire reaches the building and the fit-out of its homes is a total loss.",
            f"One scanned home stands for all {homes:,} homes at the property. That is an extrapolation: homes differ in size and finish.",
            "Homes are shared among the buildings by roof area, because the record gives a count for the property, not for each building.",
            "Fit-out was named and counted by an agent looking at the scan's own pictures. Each line says where it was seen.",
            "Floor, wall and door quantities are Matterport's measurements of the scan. Doorways are taken out of the walls. Ceilings are not counted.",
            "A line is priced only when a fetch of the page confirmed the price. Where a page gives a range, both ends are carried through.",
            "Buildings are ranked by the share of their walls with vegetation within 5 ft, from Vexcel. It is a ranking, not a chance of fire.",
        ],
        "not_counted": ["Furniture and anything a tenant owns", "The structure itself: frame, roof, wiring, plumbing", "Ceilings", "Common areas and anything outside the homes"],
    }
