"""The file on one home for a property insurer: what is there before the water, outside and inside, and what a
given depth of water would cost to put back.

Outside comes from Vexcel (the ground under the building, its roof, the trees at its walls) and CoStar (what the
community sold for). Inside comes from the Matterport scan of the home: every room with its floor area and ceiling
height, every wall with its length, every door, and the furniture the scan saw. The water is the flood test's
(`flood.py`): a depth set by hand, less the ground under this building.

The cost is a schedule. Each line is a quantity measured from the scan times a price a page states. The prices are
found by the research agent (`flood_agent.price`) and a line is priced only when a fetch of the page confirmed the
price and the sentence; a line with no confirmed price is listed with no figure and left out of the total. Unknown
money is never zero.

What the scan cannot tell is said, not guessed: which floor the home is on, what the floor is covered with, what is
inside the cabinets. Those are in `assumptions` and `not_counted`.
"""
from __future__ import annotations

import json
import math

from . import flood, matterport, openings
from .config import CACHE_DIR

M_TO_FT = 1 / 0.3048
PRICES = CACHE_DIR / "flood" / "prices.json"
CUT_ABOVE_WATER_FT = 2.0     # drywall is cut out to this far above the water line: the top of the 12 to 24 inches the Gypsum Association's guidance is reported to give
CUT_SOURCE = {"title": "Walls & Ceilings: flooded drywall, inspection and replacement (citing the Gypsum Association)",
              "url": "https://www.wconline.com/articles/98196-flooded-drywall-inspection-and-replacement-best-practices"}
LIMITS = {"building": 500_000, "contents": 100_000, "what": "National Flood Insurance Program maximum for a residential building of five or more homes, per building and per policy",
          "source": {"title": "OCC Bulletin 2014-26", "url": "https://occ.gov/news-issuances/bulletins/2014/bulletin-2014-26.html"}}

# The building work a wetted home needs, each in the unit its price must be stated in. The quantity of each is measured from the scan.
WORK = [
    {"id": "drying", "what": "Water removal and structural drying after a flood", "unit": "per square foot of floor"},
    {"id": "flooring", "what": "Vinyl plank flooring, removed and replaced, installed", "unit": "per square foot"},
    {"id": "drywall", "what": "Drywall, hung and finished", "unit": "per square foot"},
    {"id": "baseboard", "what": "Baseboard, installed", "unit": "per linear foot"},
    {"id": "paint", "what": "Interior wall painting", "unit": "per square foot of wall"},
    {"id": "door", "what": "Interior door, installed", "unit": "each"},
]


class FileError(Exception):
    pass


def _scan(property_id: int, scan_id: str) -> tuple[dict, dict]:
    try:
        bundle = json.loads((flood.BUILDINGS / str(property_id) / "building.json").read_text())
    except OSError:
        raise FileError("this building has not been gathered")
    scan = next((s for s in bundle.get("scans") or [] if s["id"] == scan_id), None)
    if scan is None:
        raise FileError("no such scan at this building")
    return bundle, scan


def inside(property_id: int, scan_id: str) -> dict:
    """What the scan measured in the home: rooms, walls, doors, and the furniture it saw."""
    _, scan = _scan(property_id, scan_id)
    try:
        plan = openings.layout(scan, json.loads((matterport.MP_CACHE / "openings" / f"{scan_id}.json").read_text()))
    except OSError:
        plan = None
    if not plan:
        raise FileError("this scan's walls have not been measured")
    lived = [r for r in scan.get("rooms") or [] if (r.get("type") or "") not in ("Void", "Patio", "") and r.get("height_m")]
    if not lived:
        raise FileError("this scan has no measured rooms")
    indoor = [r for r in plan["rooms"] if not r["outdoor"] and r["name"] != "Void"]
    wall_ft = sum(math.dist(a, b) for r in indoor for a, b in r["walls"]) * M_TO_FT
    doors = [o for o in plan["openings"] if o["kind"] == "door"]
    inner = [o for o in doors if not o["outside"]]
    # A doorway between two rooms takes a gap out of both rooms' walls; one to the outside, out of one.
    gaps_ft = (2 * sum(o["width_m"] for o in inner) + sum(o["width_m"] for o in plan["openings"] if o["outside"] and (o["sill_m"] or 0) < 0.1)) * M_TO_FT
    from .openproblems import furnish3d
    seen = furnish3d.scene(scan_id)
    pieces = [{"name": p["name"], "kind": p.get("kind"), "look": p.get("look"), "height_ft": round(p["height_m"] * M_TO_FT, 1), "stands_at_ft": round((p.get("stands_on_m") or 0) * M_TO_FT, 1)}
              for p in (seen or {}).get("pieces") or []]
    return {
        "scan_id": scan_id, "name": scan.get("name"), "kind": scan.get("kind"), "under_roof": scan.get("structure"), "floor_known": scan.get("level") is not None,
        "model_made": (scan.get("model_created_at") or "")[:10] or None,
        "rooms": [{"type": r["type"], "area_sqft": r["area_sqft"], "ceiling_ft": round(r["height_m"] * M_TO_FT, 1)} for r in sorted(lived, key=lambda r: -r["area_sqft"])],
        "floor_sqft": round(sum(r["area_sqft"] for r in lived)), "ceiling_ft": round(sum(r["height_m"] * r["area_sqft"] for r in lived) / sum(r["area_sqft"] for r in lived) * M_TO_FT, 1),
        "wall_ft": round(wall_ft), "wall_less_doorways_ft": round(wall_ft - gaps_ft), "inner_doors": len(inner), "outside_doors": len(doors) - len(inner),
        "windows": sum(1 for o in plan["openings"] if o["kind"] == "window"),
        "contents": pieces, "contents_room": (seen or {}).get("room"), "contents_note": "Furniture seen from one standpoint in one room. The rest of the home's contents were not read." if pieces else None,
        "has_photo": bool(seen) and _photo(scan_id) is not None,
    }


def _photo(scan_id: str):
    from .openproblems import furnish3d
    return next(iter(sorted((furnish3d.OUT / scan_id).glob("*/as_it_was.jpg"))), None)


def photo(property_id: int, scan_id: str):
    _scan(property_id, scan_id)
    return _photo(scan_id)


def price_list(property_id: int, scan_id: str) -> list[dict]:
    """Everything this home's file needs a price for: the building work, and one line for each kind of furniture the scan saw."""
    kinds: dict[str, dict] = {}
    for p in inside(property_id, scan_id)["contents"]:
        key = _piece_key(p["name"])
        kinds.setdefault(key, {"id": f"piece:{key}", "what": f"A new {key}, comparable to: {p['look'] or p['name']}", "unit": "each"})
    return WORK + list(kinds.values())


def _piece_key(name: str) -> str:
    """'left side table' and 'right side table' are one kind of thing to price."""
    words = [w for w in name.lower().split() if w not in ("left", "right", "front", "back", "near", "far", "small", "large")]
    return " ".join(words) or name.lower()


def saved_prices() -> dict:
    """The confirmed price for each item, and every price the agent recorded. Empty when no price research has been saved."""
    try:
        run = json.loads(PRICES.read_text())
    except (OSError, ValueError):
        return {"made_at": None, "by_item": {}, "found": 0, "confirmed": 0, "searches": 0, "steps": []}
    by_item: dict[str, dict] = {}
    for row in run.get("prices") or []:
        if row.get("checked"):
            by_item.setdefault(row["item"], row)          # the first confirmed price for an item is the one used
    rows = run.get("prices") or []
    return {"made_at": run.get("made_at"), "by_item": by_item, "found": len(rows), "confirmed": sum(1 for r in rows if r.get("checked")),
            "searches": sum(1 for s in run.get("steps") or [] if s.get("kind") == "search"), "steps": run.get("steps") or []}


def _line(item_id: str, what: str, quantity: float, unit: str, how: str, prices: dict) -> dict:
    row = prices["by_item"].get(item_id)
    low = round(quantity * row["price"]) if row else None
    high = round(quantity * (row["price_high"] or row["price"])) if row else None
    quantity = round(quantity)
    return {"id": item_id, "what": what, "quantity": quantity, "unit": unit, "how": how,
            "price": row["price"] if row else None, "price_high": row.get("price_high") if row else None, "low": low, "high": high,
            "source": row["source"] if row else None}


def file(property_id: int, scan_id: str, water_ft: float = 4.0) -> dict:
    """The insurer's file on one home: before the water, outside and inside, and the schedule of what that water would cost."""
    run = flood.test(property_id, water_ft)
    home = inside(property_id, scan_id)
    building = next((b for b in run["buildings"] if b["id"] == home["under_roof"]), None)
    if building is None:
        raise FileError("the roof this scan is under has no measured ground level")
    try:
        heights = {s["id"]: s for s in json.loads((flood.HEIGHTS / str(property_id) / "heights.json").read_text()).get("structures") or []}
    except OSError:
        heights = {}
    roof = heights.get(building["id"], {})
    depth = building["depth_ft"]
    prices = saved_prices()

    cut = min(home["ceiling_ft"], depth + CUT_ABOVE_WATER_FT) if depth > 0 else 0.0
    work, contents = [], []
    if depth > 0:
        net = home["wall_less_doorways_ft"]
        work = [
            _line("drying", "Water removal and drying", home["floor_sqft"], "sq ft", "the floor area of every room in the scan", prices),
            _line("flooring", "Flooring", home["floor_sqft"], "sq ft", "the floor area of every room in the scan", prices),
            _line("drywall", "Drywall", net * cut, "sq ft", f"{net:,} ft of wall, less doorways, cut out to {cut:g} ft", prices),
            _line("baseboard", "Baseboard", net, "ft", "the length of every wall in the scan, less doorways", prices),
            _line("paint", "Painting", net * home["ceiling_ft"], "sq ft", f"{net:,} ft of wall to the {home['ceiling_ft']:g} ft ceiling", prices),
            _line("door", "Interior doors", home["inner_doors"], "doors", "the doorways between rooms in the scan", prices),
        ]
        for p in home["contents"]:
            if p["stands_at_ft"] < depth:      # a lamp on a table above the water is not wetted
                where = "on the floor" if not p["stands_at_ft"] else f"{p['stands_at_ft']:g} ft up"
                contents.append(_line(f"piece:{_piece_key(p['name'])}", p["name"].capitalize(), 1, "piece", f"stands {where}, {p['height_ft']:g} ft tall", prices))
    spared = [p["name"] for p in home["contents"] if depth > 0 and p["stands_at_ft"] >= depth]

    def total(rows: list[dict]) -> dict:
        priced = [r for r in rows if r["low"] is not None]
        return {"low": sum(r["low"] for r in priced) if priced else None, "high": sum(r["high"] for r in priced) if priced else None,
                "lines": len(rows), "priced": len(priced)}
    t_work, t_contents = total(work), total(contents)
    both = [t for t in (t_work, t_contents) if t["low"] is not None]

    return {
        "property_id": property_id, "name": run["name"], "address": run["address"], "sale": run["sale"], "bounds": run["bounds"], "aerial": run["aerial"],
        "outside": {"building": building["id"], "polygon": building["polygon"], "ground_m": building["ground_m"],
                    "below_highest_ft": round((max(b["ground_m"] for b in run["buildings"]) - building["ground_m"]) * M_TO_FT, 1),
                    "roof_height_ft": round(roof["roof_height_m"] * M_TO_FT, 1) if roof.get("roof_height_m") else None,
                    "trees_within_5ft_percent": building.get("trees_within_5ft_percent"), "terrain": next((a for a in run["assumptions"] if a.startswith("Ground under")), None)},
        "inside": home,
        "water": {"set_ft": water_ft, "at_this_building_ft": depth, "drywall_cut_ft": round(cut, 1)},
        "schedule": {"work": work, "contents": contents, "contents_spared": spared, "work_total": t_work, "contents_total": t_contents,
                     "total": {"low": sum(t["low"] for t in both), "high": sum(t["high"] for t in both)} if both else None},
        "limits": LIMITS,
        "prices": {"made_at": prices["made_at"], "found": prices["found"], "confirmed": prices["confirmed"], "searches": prices["searches"]},
        "not_counted": ["Cabinets, counters and appliances", "Wiring, outlets and plumbing", "Insulation inside the walls", "Contents of every room but the one the furniture was read in", "Lost rent while the home is empty"],
        "assumptions": [
            "A what-if, not a forecast: the water is set by hand, in feet at the lowest building on the site." ,
            "The scan does not say which floor this home is on. The schedule is for a home on the ground floor, with its floor at ground level."
            if not home["floor_known"] else "The home is on the ground floor, with its floor at ground level.",
            "Which roof the home is under comes from the scan's position, which is good to a few metres.",
            f"Drywall is cut out to {CUT_ABOVE_WATER_FT:g} ft above the water line, or to the ceiling if that is lower.",
            "The scan does not say what the floor is covered with. It is priced as vinyl plank.",
            "Any water on the floor means new flooring, baseboard and interior doors, and repainting the walls.",
            "Quantities: Matterport's measurements of the scan. Prices: found on the web by Brace's research agent; a line is priced only when a fetch of its page confirmed the price. Where a page gives a range, both ends are carried through.",
        ],
        "cut_source": CUT_SOURCE,
    }
