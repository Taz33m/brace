"""A flood stress test for one site: what a given depth of water would cost if nothing is done, and where a
budget and the hours left are best spent.

It is a what-if, not a forecast. The water is set by hand (feet of water at the lowest building on the site)
and everything else is read or stated:

* the ground under each building comes from Vexcel's terrain model, so a building on higher ground gets
  less water and one above the water gets none;
* the share of a building lost at a depth is the US Army Corps of Engineers' generic curve for homes of two
  or more storeys without a basement (EGM 04-01), applied to these apartment buildings as an assumption;
* a building's value is the community's last recorded sale price from CoStar, split by roof area. A sale
  price includes the land, so this is the price at stake, not a rebuilding cost;
* the fixes and their prices are in MEASURES, each with where the figure came from.

The plan is chosen by a rule in code: protect the buildings that avoid the most loss per dollar, until the
budget or the crew hours run out. A barrier lower than the water does nothing and is never chosen.
"""
from __future__ import annotations

import io
import json
import math
from functools import lru_cache

import numpy as np
from PIL import Image

from . import portfolio
from .config import CACHE_DIR

FT = 0.3048
BUILDINGS = CACHE_DIR / "buildings"
HEIGHTS = CACHE_DIR / "open" / "reconstruct"

# Percent of a structure's value lost at a depth of water above its ground floor, in feet.
# US Army Corps of Engineers, Economic Guidance Memorandum 04-01 (10 October 2003), enclosure:
# "Two or More Stories - No Basement", structure, mean of damage.
CURVE = [(-2, 0.0), (-1, 3.0), (0, 9.3), (1, 15.2), (2, 20.9), (3, 26.3), (4, 31.4), (5, 36.2), (6, 40.7), (7, 44.9), (8, 48.8),
         (9, 52.4), (10, 55.7), (11, 58.7), (12, 61.4), (13, 63.8), (14, 65.9), (15, 67.7), (16, 69.2)]
CURVE_SOURCE = {"title": "US Army Corps of Engineers, EGM 04-01: Generic Depth-Damage Relationships for Residential Structures (2003)",
                "url": "https://planning.erdc.dren.mil/toolbox/library/EGMs/egm04-01.pdf"}

# What can be put round a building before the water comes. A price is the published one and nothing is added to it.
MEASURES = [
    {"id": "tube30", "name": "Water-filled barrier, 30 in", "holds_ft": 2.5, "cost_per_ft": 20.0,
     "source": {"title": "Bloomberg, 1 September 2017: AquaDam at $20 a foot for 30 inches and $50 a foot for 4 feet, before shipping and tax",
                "url": "https://www.climatechange.ie/?p=64031"}},
    {"id": "tube48", "name": "Water-filled barrier, 4 ft", "holds_ft": 4.0, "cost_per_ft": 50.0,
     "source": {"title": "Bloomberg, 1 September 2017: AquaDam at $20 a foot for 30 inches and $50 a foot for 4 feet, before shipping and tax",
                "url": "https://www.climatechange.ie/?p=64031"}},
]
CREW_DAY_H = 12.0          # one crew sets and fills one building's barrier in a working day: the same source gives "between an hour and a full day" to fill
WORK_H_PER_DAY = 12.0      # crews work 07:00 to 19:00, as the storm desk assumes


class FloodError(Exception):
    pass


def damage_share(depth_ft: float) -> float:
    """The share of a structure lost at a depth, read off the Corps' curve between its whole feet. Nothing below the ground floor."""
    if depth_ft <= 0:
        return 0.0
    d = min(depth_ft, CURVE[-1][0])
    for (d0, p0), (d1, p1) in zip(CURVE, CURVE[1:]):
        if d0 <= d <= d1:
            return (p0 + (p1 - p0) * (d - d0) / (d1 - d0)) / 100.0
    return CURVE[-1][1] / 100.0


def _perimeter_ft(polygon: list[list[float]]) -> float:
    lat0 = math.radians(sum(p[1] for p in polygon) / len(polygon))
    pts = [(p[0] * 111_320.0 * math.cos(lat0), p[1] * 110_540.0) for p in polygon]
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:] + pts[:1])) / FT


def site(property_id: int) -> dict:
    """The buildings of a site with the ground under each, its outline, and its share of the sale price."""
    try:
        bundle = json.loads((BUILDINGS / str(property_id) / "building.json").read_text())
        heights = json.loads((HEIGHTS / str(property_id) / "heights.json").read_text())
    except OSError:
        raise FloodError("this site has no terrain model yet")
    ground = {s["id"]: s.get("ground_elevation_m") for s in heights.get("structures") or []}
    rows = [s for s in bundle["structures"] if ground.get(s["id"]) is not None and s.get("polygon") and s.get("footprint_sqft")]
    if len(rows) < 2:
        raise FloodError("too few buildings here have a measured ground level")
    try:
        sale = portfolio.building(property_id).get("last_sale") or {}
    except KeyError:
        sale = {}
    price, roof = sale.get("price"), sum(s["footprint_sqft"] for s in rows)
    terr = heights["source"]["terrain"]
    return {
        "property_id": property_id, "name": bundle["record"].get("name"), "homes": bundle["record"].get("units"),
        "bounds": bundle["aerial"]["bounds"], "aerial": {"width": bundle["aerial"]["width"], "height": bundle["aerial"]["height"]},
        "sale": {"price": price, "year": (sale.get("date") or "")[:4] or None} if price else None,
        "lowest_ground_m": min(ground[s["id"]] for s in rows),
        "terrain": f"Vexcel terrain model, flown {terr['first_capture']} to {terr['last_capture']}",
        "buildings": [{"id": s["id"], "polygon": s["polygon"], "ground_m": ground[s["id"]], "perimeter_ft": round(_perimeter_ft(s["polygon"])),
                       "value": round(price * s["footprint_sqft"] / roof) if price else None} for s in rows],
    }


def test(property_id: int, water_ft: float, budget: float | None = None, hours: float | None = None, crews: int = 3) -> dict:
    """What `water_ft` of water at the lowest building costs if nothing is done, and the plan a budget and the hours left buy.

    With no budget or hours, only the do-nothing loss is worked out.
    """
    s = site(property_id)
    level = s["lowest_ground_m"] + water_ft * FT
    rows = []
    for b in s["buildings"]:
        depth = max(0.0, (level - b["ground_m"]) / FT)
        loss = round(b["value"] * damage_share(depth)) if b["value"] is not None else None
        rows.append({**b, "depth_ft": round(depth, 1), "loss": loss, "fix": None, "left_out": None})
    priced = [r for r in rows if r["loss"]]
    out = {"property_id": property_id, "name": s["name"], "homes": s["homes"], "sale": s["sale"], "bounds": s["bounds"], "aerial": s["aerial"],
           "water_ft": water_ft, "water_level_m": round(level, 2), "buildings": rows,
           "do_nothing": {"loss": sum(r["loss"] for r in priced) if priced else None, "buildings_wet": sum(1 for r in rows if r["depth_ft"] > 0)},
           "plan": None, "assumptions": assumptions(s, crews), "measures": MEASURES}
    if budget is None or hours is None or not priced:
        return out

    crew_hours = crews * WORK_H_PER_DAY * (hours / 24.0)
    options = []
    for r in priced:
        fit = [m for m in MEASURES if m["holds_ft"] >= r["depth_ft"]]
        if not fit:
            r["left_out"] = f"no barrier here holds {r['depth_ft']:g} ft"
            continue
        m = min(fit, key=lambda m: m["cost_per_ft"])
        options.append((r, m, round(r["perimeter_ft"] * m["cost_per_ft"])))
    # Two limits, so two ways to rank: most saved per dollar (when money is short) and most saved outright (when time is).
    # Both are tried and the one that saves more is kept.
    def choose(order: list) -> tuple[float, dict]:
        spent = used = 0.0
        picked: dict[str, dict] = {}
        for r, m, cost in order:
            if spent + cost > budget:
                picked[r["id"]] = {"left_out": "the budget ran out"}
            elif used + CREW_DAY_H > crew_hours:
                picked[r["id"]] = {"left_out": "the time ran out"}
            else:
                spent += cost; used += CREW_DAY_H
                picked[r["id"]] = {"fix": {"measure": m["id"], "name": m["name"], "cost": cost, "crew_hours": CREW_DAY_H, "saves": r["loss"]}}
        return sum(v["fix"]["saves"] for v in picked.values() if "fix" in v), picked
    _, best = max((choose(sorted(options, key=lambda o: -o[0]["loss"] / o[2])), choose(sorted(options, key=lambda o: -o[0]["loss"]))), key=lambda c: c[0])
    for r in rows:
        r.update(best.get(r["id"], {}))
    spent, used = sum(r["fix"]["cost"] for r in rows if r["fix"]), sum(r["fix"]["crew_hours"] for r in rows if r["fix"])
    saved = sum(r["fix"]["saves"] for r in rows if r["fix"])
    out["plan"] = {"budget": budget, "hours": hours, "crews": crews, "crew_hours": crew_hours, "spent": round(spent), "crew_hours_used": used,
                   "buildings_protected": sum(1 for r in rows if r["fix"]), "saved": saved, "loss": out["do_nothing"]["loss"] - saved,
                   "work_order": work_order(s, rows, water_ft, hours)}
    return out


def assumptions(s: dict, crews: int) -> list[str]:
    return [
        "A what-if, not a forecast: the water is set by hand, in feet at the lowest building on the site.",
        f"Ground under each building: {s['terrain']}. A building on higher ground gets less water.",
        "Share of a building lost at a depth: US Army Corps of Engineers generic curve for homes of two or more storeys without a basement (EGM 04-01), applied to these apartment buildings.",
        "A building's value: the community's last recorded sale price (CoStar), split by roof area. A sale price includes the land. Contents are not counted.",
        "Barrier prices: AquaDam, as reported by Bloomberg in 2017, before shipping and tax. A barrier lower than the water is counted as doing nothing.",
        f"Time: {crews} crews, 12 working hours a day, one building's barrier per crew per day.",
    ]


def work_order(s: dict, rows: list[dict], water_ft: float, hours: float) -> str:
    """The order for the barrier contractor, as it would be sent: which buildings, what, how many feet, in what order."""
    chosen = sorted((r for r in rows if r["fix"]), key=lambda r: -r["fix"]["saves"])
    if not chosen:
        return ""
    lines = [f"Work order: flood barriers at {s['name']}", f"Water expected: {water_ft:g} ft at the lowest building. Finish within {hours:g} hours.", ""]
    lines += [f"{i}. Building {r['id']}: {r['fix']['name'].lower()}, {r['perimeter_ft']:,} ft round the building. ${r['fix']['cost']:,}." for i, r in enumerate(chosen, 1)]
    lines += ["", f"Total: ${sum(r['fix']['cost'] for r in chosen):,} for {len(chosen)} buildings. Nothing is ordered until the owner approves."]
    return "\n".join(lines)


@lru_cache(maxsize=24)
def water_png(property_id: int, water_ft: float) -> bytes:
    """Where the water would stand, as a see-through blue layer on the aerial photo's own bounds: every cell of the terrain model below the water level, darker where it is deeper."""
    from .openproblems import reconstruct
    files = sorted((HEIGHTS / str(property_id) / "source").glob("dtm_*.tif"))
    if not files:
        raise FloodError("this site has no terrain model yet")
    terrain, _ = reconstruct.read_height_tiff(files[0].read_bytes())
    depth = (site(property_id)["lowest_ground_m"] + water_ft * FT) - terrain
    wet = depth > 0
    rgba = np.zeros((*terrain.shape, 4), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 24, 104, 196
    rgba[..., 3] = np.where(wet, np.clip(70 + 110 * np.clip(depth, 0, 2.5) / 2.5, 0, 185), 0).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()
