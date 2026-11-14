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
* the fixes and their prices come from the research agent (flood_agent.py), each with the page it was found on and only
  when a fetch of that page confirmed the price; with no research saved, from the two barriers in HAND.

The plan is chosen by a rule in code: protect the buildings that avoid the most loss per dollar, until the
budget or the crew hours run out. A barrier lower than the water does nothing and is never chosen.
"""
from __future__ import annotations

import io
import json
import math
import re
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

# What can be put round a building before the water comes, as entered by hand from a page a person read. The research agent
# (flood_agent.py) replaces this list with what it finds, when a research run is saved. A price is the published one.
_BLOOMBERG = {"title": "Bloomberg, 1 September 2017: AquaDam at $20 a foot for 30 inches and $50 a foot for 4 feet, before shipping and tax",
              "url": "https://www.climatechange.ie/?p=64031"}
HAND = [
    {"id": "tube30", "name": "Water-filled barrier, 30 in", "type": "quick", "holds_ft": 2.5, "cost_per_ft": 20.0, "crew_hours_per_100ft": None, "weeks": None, "source": _BLOOMBERG},
    {"id": "tube48", "name": "Water-filled barrier, 4 ft", "type": "quick", "holds_ft": 4.0, "cost_per_ft": 50.0, "crew_hours_per_100ft": None, "weeks": None, "source": _BLOOMBERG},
]
RESEARCH = CACHE_DIR / "flood" / "research.json"
CREW_DAY_H = 12.0          # with no stated rate, one crew sets one building's barrier in a working day
WORK_H_PER_DAY = 12.0      # crews work 07:00 to 19:00, as the storm desk assumes
CREW_SIZE = 4              # people in a crew, for turning a rate per person into crew hours
SANDBAG_WALLS_FT = (1.0, 2.0, 3.0)
PANEL_WALLS_FT = (2.0, 4.0, 6.0)
# A sentence that says its own price leaves out something the fix cannot work without. Such a price is listed, never planned.
LEAVES_OUT = re.compile(r"\b(not including|excluding|does not include|doesn't include|not included|plus (the )?(cost of )?(sand|fill|installation|labou?r))\b", re.I)


def bags_per_ft(height_ft: float) -> float:
    """Sandbags in one foot of wall of a height: North Dakota State University Extension, AE626, N = (3H + 9H^2) / 2."""
    return (3 * height_ft + 9 * height_ft * height_ft) / 2


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")[:48]


def catalogue() -> dict:
    """The fixes the plan may choose from: the two barriers entered by hand, and what the research agent found.

    An agent's find is planned only when a fetch of its page confirmed the price and the page does not say the price leaves
    something out. A find that fails either is listed and never planned.
    """
    try:
        run = json.loads(RESEARCH.read_text())
    except (OSError, ValueError):
        return {"by": "hand", "made_at": None, "measures": list(HAND), "found": [], "steps": [], "searches": 0}
    measures, found = list(HAND), []
    for f in run.get("fixes") or []:
        price = float(f.get("price_high") or f["price"])      # where a page gives a range, the plan counts the top of it
        row = {"name": f["name"], "type": f["type"], "holds_ft": f.get("holds_ft"), "price": f.get("price"), "price_high": f.get("price_high"), "price_unit": f.get("price_unit"),
               "weeks": f.get("weeks"), "time_text": f.get("time_text"), "source": f.get("source"), "checked": bool(f.get("checked")), "planned": False, "why_not": None}
        found.append(row)
        base = {"type": f["type"], "weeks": f.get("weeks"), "source": f.get("source")}
        if not row["checked"]:
            row["why_not"] = "the price could not be confirmed on the page"
        elif f["type"] != "quick":
            row["why_not"] = "long-term work"
            measures.append({**base, "id": _slug(f["name"]), "name": f["name"], "holds_ft": f.get("holds_ft"), "cost_per_ft": None, "crew_hours_per_100ft": None})
        elif LEAVES_OUT.search((f.get("source") or {}).get("quote") or ""):
            row["why_not"] = "the page says this price leaves something out"
        elif f.get("price_unit") == "per linear foot" and f.get("holds_ft"):
            row["planned"] = True
            measures.append({**base, "id": _slug(f["name"]), "name": f["name"], "holds_ft": float(f["holds_ft"]), "cost_per_ft": price,
                             "crew_hours_per_100ft": f.get("crew_hours_per_100ft")})
        elif f.get("price_unit") == "per square foot":
            row["planned"] = True
            for h in PANEL_WALLS_FT:      # a panel wall priced by its face: a foot of wall h feet high is h square feet
                measures.append({**base, "id": f"{_slug(f['name'])}-{h:g}ft", "name": f"{f['name']}, {h:g} ft", "holds_ft": h, "cost_per_ft": round(price * h, 2), "crew_hours_per_100ft": f.get("crew_hours_per_100ft")})
        elif f.get("price_unit") == "per sandbag" and f.get("bags_per_person_hour"):
            row["planned"] = True
            for h in SANDBAG_WALLS_FT:      # a wall of sandbags is priced and timed by its count of bags
                measures.append({**base, "id": f"sandbags-{h:g}ft", "name": f"Sandbag wall, {h:g} ft", "holds_ft": h, "cost_per_ft": round(bags_per_ft(h) * price, 2),
                                 "crew_hours_per_100ft": round(100 * bags_per_ft(h) / (float(f["bags_per_person_hour"]) * CREW_SIZE), 1)})
        else:
            row["why_not"] = ("no stated filling rate" if f.get("price_unit") == "per sandbag" else "no stated height" if f.get("price_unit") == "per linear foot" else "its price is not per foot of barrier")
    seen: set[str] = set()
    measures = [m for m in measures if not (m["id"] in seen or seen.add(m["id"]))]
    return {"by": "agent", "made_at": run.get("made_at"), "model": run.get("model"), "measures": measures, "found": found,
            "steps": run.get("steps") or [], "searches": sum(1 for e in run.get("steps") or [] if e.get("kind") == "search")}


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
    by_id = {s["id"]: s for s in heights.get("structures") or []}
    ground = {k: v.get("ground_elevation_m") for k, v in by_id.items()}
    rows = [s for s in bundle["structures"] if ground.get(s["id"]) is not None and s.get("polygon") and s.get("footprint_sqft")]
    if len(rows) < 2:
        raise FloodError("too few buildings here have a measured ground level")
    try:
        sale = portfolio.building(property_id).get("last_sale") or {}
    except KeyError:
        sale = {}
    rec, price, roof = bundle["record"], sale.get("price"), sum(s["footprint_sqft"] for s in rows)
    terr = heights["source"]["terrain"]
    return {
        "property_id": property_id, "name": rec.get("name"), "homes": rec.get("units"), "sqft": rec.get("gba_sqft"),
        "address": ", ".join(str(x) for x in (rec.get("address"), rec.get("city"), rec.get("state")) if x) or None, "city": rec.get("city"),
        "bounds": bundle["aerial"]["bounds"], "aerial": {"width": bundle["aerial"]["width"], "height": bundle["aerial"]["height"]},
        "sale": {"price": price, "year": (sale.get("date") or "")[:4] or None} if price else None,
        "lowest_ground_m": min(ground[s["id"]] for s in rows), "highest_ground_m": max(ground[s["id"]] for s in rows),
        "terrain": f"Vexcel terrain model, flown {terr['first_capture']} to {terr['last_capture']}",
        "buildings": [{"id": s["id"], "polygon": s["polygon"], "ground_m": ground[s["id"]], "perimeter_ft": round(_perimeter_ft(s["polygon"])),
                       "trees_within_5ft_percent": by_id[s["id"]].get("vexcel_trees_within_5ft_percent"),
                       "value": round(price * s["footprint_sqft"] / roof) if price else None} for s in rows],
    }


def sites(city: str = "Houston") -> list[dict]:
    """Every site in a city that can be tested: it has a terrain model, measured ground under its buildings, and a recorded sale."""
    out = []
    for d in sorted(HEIGHTS.iterdir()) if HEIGHTS.is_dir() else []:
        if d.name.isdigit():
            try:
                s = site(int(d.name))
            except (FloodError, KeyError, ValueError):
                continue
            if s["sale"] and (s["city"] or "").lower() == city.lower():
                out.append(s)
    return out


def why(s: dict, rows: list[dict]) -> list[dict]:
    """Why this site loses what it does, each line a fact from a named source. Nothing is said that the data does not hold."""
    low = min(rows, key=lambda r: r["ground_m"])
    out = [{"text": f"Building {low['id']} stands on the lowest ground here, {(s['highest_ground_m'] - s['lowest_ground_m']) / FT:.1f} ft below the highest", "source": "Vexcel"}]
    if s["sale"]:
        out.append({"text": f"Last sold for ${s['sale']['price']:,.0f}" + (f" in {s['sale']['year']}" if s["sale"]["year"] else ""), "source": "CoStar"})
    wet = [r for r in rows if r["depth_ft"] > 0]
    if wet:
        out.append({"text": f"{len(wet)} of {len(rows)} buildings take water", "source": "Vexcel"})
    trees = max((r for r in rows if r.get("trees_within_5ft_percent")), key=lambda r: r["trees_within_5ft_percent"], default=None)
    if trees:
        out.append({"text": f"Trees within 5 ft of {trees['trees_within_5ft_percent']:.0f}% of building {trees['id']}", "source": "Vexcel"})
    return out


def _hours(m: dict, perimeter_ft: float) -> float:
    """Crew hours to put a fix round a building: the stated rate where the source gives one, else one crew-day."""
    rate = m.get("crew_hours_per_100ft")
    return round(rate * perimeter_ft / 100, 1) if rate else CREW_DAY_H


def test(property_id: int, water_ft: float, budget: float | None = None, hours: float | None = None, crews: int = 3) -> dict:
    """What `water_ft` of water at the lowest building costs if nothing is done, and the plan a budget and the hours left buy.

    With no budget or hours, only the do-nothing loss is worked out.
    """
    s, cat = site(property_id), catalogue()
    level = s["lowest_ground_m"] + water_ft * FT
    rows = []
    for b in s["buildings"]:
        depth = max(0.0, (level - b["ground_m"]) / FT)
        loss = round(b["value"] * damage_share(depth)) if b["value"] is not None else None
        rows.append({**b, "depth_ft": round(depth, 1), "loss": loss, "fix": None, "left_out": None})
    priced = [r for r in rows if r["loss"]]
    quick = [m for m in cat["measures"] if m["type"] == "quick"]
    out = {"property_id": property_id, "name": s["name"], "address": s["address"], "homes": s["homes"], "sqft": s["sqft"], "sale": s["sale"],
           "bounds": s["bounds"], "aerial": s["aerial"], "water_ft": water_ft, "water_level_m": round(level, 2), "buildings": rows,
           "do_nothing": {"loss": sum(r["loss"] for r in priced) if priced else None, "buildings_wet": sum(1 for r in rows if r["depth_ft"] > 0)},
           "why": why(s, rows), "plan": None, "assumptions": assumptions(s, crews, cat), "measures": cat["measures"],
           "research": {"by": cat["by"], "made_at": cat["made_at"], "searches": cat["searches"], "found": cat["found"], "steps": cat["steps"]}}
    if budget is None or hours is None or not priced:
        return out

    crew_hours = crews * WORK_H_PER_DAY * (hours / 24.0)
    options = []          # for each wet building, every fix that holds its water, with its cost and its crew hours
    for r in priced:
        fit = [(m, round(r["perimeter_ft"] * m["cost_per_ft"]), _hours(m, r["perimeter_ft"])) for m in quick if m["holds_ft"] >= r["depth_ft"]]
        if fit:
            options.append((r, fit))
        else:
            r["left_out"] = f"no barrier here holds {r['depth_ft']:g} ft"

    # Two limits, so more than one way to rank: by loss avoided per dollar with the cheapest fix (when money is short), by loss
    # avoided outright with the cheapest, and by loss avoided per crew hour with the fastest (when time is). The one that saves most is kept.
    def choose(pick, rank) -> tuple[float, float, dict]:
        spent = used = 0.0
        picked: dict[str, dict] = {}
        for r, (m, cost, h) in sorted(((r, pick(fit)) for r, fit in options), key=rank):
            if spent + cost > budget:
                picked[r["id"]] = {"left_out": "the budget ran out"}
            elif used + h > crew_hours:
                picked[r["id"]] = {"left_out": "the time ran out"}
            else:
                spent += cost; used += h
                picked[r["id"]] = {"fix": {"measure": m["id"], "name": m["name"], "type": m["type"], "cost": cost, "crew_hours": h, "saves": r["loss"]}}
        return sum(v["fix"]["saves"] for v in picked.values() if "fix" in v), -spent, picked
    cheapest, fastest = (lambda fit: min(fit, key=lambda o: o[1])), (lambda fit: min(fit, key=lambda o: (o[2], o[1])))
    tries = [choose(cheapest, lambda o: -o[0]["loss"] / max(o[1][1], 1)), choose(cheapest, lambda o: -o[0]["loss"]), choose(fastest, lambda o: -o[0]["loss"] / max(o[1][2], 0.1))]
    best = max(tries, key=lambda c: (c[0], c[1]))[2]
    for r in rows:
        r.update(best.get(r["id"], {}))
    chosen = sorted((r for r in rows if r["fix"]), key=lambda r: -r["fix"]["saves"])
    spent, used, saved = sum(r["fix"]["cost"] for r in chosen), sum(r["fix"]["crew_hours"] for r in chosen), sum(r["fix"]["saves"] for r in chosen)
    out["plan"] = {"budget": budget, "hours": hours, "crews": crews, "crew_hours": crew_hours, "spent": round(spent), "crew_hours_used": round(used, 1),
                   "buildings_protected": len(chosen), "saved": saved, "loss": out["do_nothing"]["loss"] - saved,
                   "fixes": [{"building": r["id"], **r["fix"], "per_dollar": round(r["fix"]["saves"] / max(r["fix"]["cost"], 1), 1)} for r in chosen],
                   "tradeoffs": tradeoffs(cat, rows, chosen, hours, crews), "work_order": work_order(s, chosen, water_ft, hours),
                   "notice": notice(s, chosen, water_ft, hours)}
    return out


def tradeoffs(cat: dict, rows: list[dict], chosen: list[dict], hours: float, crews: int) -> list[str]:
    """Why the plan is this plan, one line each, from the figures it was made with."""
    lines = []
    used = {}
    for r in chosen:
        used.setdefault(r["fix"]["measure"], []).append(r)
    for m in cat["measures"]:
        if m["id"] in used:
            n = len(used[m["id"]])
            lines.append(f"{m['name']} at {n} building{'s' if n != 1 else ''}: the cheapest fix that holds the water there, ${m['cost_per_ft']:,.0f} a foot.")
    for m in cat["measures"]:
        if m["type"] != "quick":
            lines.append(f"{m['name']}: {m['weeks']:g} weeks. It does not fit {hours:g} hours." if m.get("weeks") else f"{m['name']}: long-term work. It does not fit {hours:g} hours.")
    waiting = sum(1 for r in rows if r["left_out"] == "the time ran out")
    if waiting:
        lines.append(f"{waiting} more building{'s' if waiting != 1 else ''} would be worth protecting: {crews} crews cannot reach them in {hours:g} hours.")
    broke = sum(1 for r in rows if r["left_out"] == "the budget ran out")
    if broke:
        lines.append(f"{broke} more building{'s' if broke != 1 else ''} would be worth protecting: the budget does not reach them.")
    deep = sum(1 for r in rows if (r["left_out"] or "").startswith("no barrier"))
    if deep:
        lines.append(f"{deep} building{'s' if deep != 1 else ''} take more water than any quick barrier found holds.")
    return lines


def assumptions(s: dict, crews: int, cat: dict | None = None) -> list[str]:
    cat = cat or catalogue()
    fixes = "Fixes and prices: two water-filled barriers entered by hand (AquaDam, as reported by Bloomberg in 2017, before shipping and tax)"
    fixes += (f", and what Brace's research agent found on the web on {cat['made_at'][:10]}. A find is planned only if a fetch of its page confirmed the price and the page does not say the price leaves something out. Where a page gives a range, the top of it is counted."
              if cat["by"] == "agent" else ".")
    return [
        "A what-if, not a forecast: the water is set by hand, in feet at the lowest building on the site.",
        f"Ground under each building: {s['terrain']}. A building on higher ground gets less water.",
        "Share of a building lost at a depth: US Army Corps of Engineers generic curve for homes of two or more storeys without a basement (EGM 04-01), applied to these apartment buildings.",
        "A building's value: the community's last recorded sale price (CoStar), split by roof area. A sale price includes the land. Contents are not counted.",
        fixes + " A barrier is counted as holding water up to its stated height: lower than the water it does nothing, and one that holds it saves the building.",
        f"Time: {crews} crews, 12 working hours a day. Where a source states how fast a fix goes in, that rate is used; otherwise one building per crew per day."
        + (f" A sandbag wall is counted by its bags (North Dakota State University, AE626), filled and placed by a crew of {CREW_SIZE}." if any(m["id"].startswith("sandbags-") for m in cat["measures"]) else ""),
    ]


def work_order(s: dict, chosen: list[dict], water_ft: float, hours: float) -> str:
    """The order for the barrier contractor, as it would be sent: which buildings, what, how many feet, in what order."""
    if not chosen:
        return ""
    lines = [f"Work order: flood barriers at {s['name']}", f"Water expected: {water_ft:g} ft at the lowest building. Finish within {hours:g} hours.", ""]
    lines += [f"{i}. Building {r['id']}: {r['fix']['name'].lower()}, {r['perimeter_ft']:,} ft round the building. ${r['fix']['cost']:,}." for i, r in enumerate(chosen, 1)]
    lines += ["", f"Total: ${sum(r['fix']['cost'] for r in chosen):,} for {len(chosen)} buildings. Nothing is ordered until the owner approves."]
    return "\n".join(lines)


def notice(s: dict, chosen: list[dict], water_ft: float, hours: float) -> str:
    """The notice for the people who live there, as it would be sent once the owner approves the work."""
    if not chosen:
        return ""
    ids = [r["id"] for r in chosen]
    listed = ", ".join(ids[:-1]) + (" and " if len(ids) > 1 else "") + ids[-1]
    return "\n".join([
        f"To the residents of {s['name']}",
        f"Flood water of up to {water_ft:g} ft is possible here within {hours:g} hours.",
        f"Crews will put flood barriers round building{'s' if len(ids) != 1 else ''} {listed}. Please keep the paths round these buildings clear and move cars away from the walls.",
        "If you live on a ground floor, move what you can off the floor.",
        "This notice is a draft. It is sent only when the owner approves it.",
    ])


def scenario(property_id: int, water_ft: float = 4.0, budget: float = 500_000, hours: float = 48, crews: int = 3) -> dict:
    """One run in the shape the team's screens read: the property, the flood, the budget, the loss before and after, and each fix with where it goes.

    A fix's position is the middle of its building as a fraction of the aerial photo, from the top left. Long-term fixes carry no position: they are not placed.
    """
    r = test(property_id, water_ft, budget, hours, crews)
    w, s_, e, n = r["bounds"]
    def at(poly):
        return {"x": round((sum(p[0] for p in poly) / len(poly) - w) / (e - w), 4), "y": round((n - sum(p[1] for p in poly) / len(poly)) / (n - s_), 4)}
    quick = {m["id"]: m for m in r["measures"] if m["type"] == "quick"}
    fixes = []
    for b in r["buildings"]:
        if b["fix"]:
            f = b["fix"]
            fixes.append({"id": f"{f['measure']}-{b['id']}", "name": f["name"], "building": b["id"], "cost": f["cost"], "hours": f["crew_hours"], "type": "quick",
                          "lossAvoided": f["saves"], "selected": True, "position": at(b["polygon"]), "lengthFt": b["perimeter_ft"], "source": quick[f["measure"]]["source"]["url"]})
        elif b["loss"] and b["left_out"] and not b["left_out"].startswith("no barrier"):
            fit = [m for m in quick.values() if m["holds_ft"] >= b["depth_ft"]]
            m = min(fit, key=lambda m: m["cost_per_ft"])
            fixes.append({"id": f"{m['id']}-{b['id']}", "name": m["name"], "building": b["id"], "cost": round(b["perimeter_ft"] * m["cost_per_ft"]), "hours": _hours(m, b["perimeter_ft"]),
                          "type": "quick", "lossAvoided": b["loss"], "selected": False, "leftOut": b["left_out"], "position": at(b["polygon"]), "lengthFt": b["perimeter_ft"], "source": m["source"]["url"]})
    fixes.sort(key=lambda f: (not f["selected"], -f["lossAvoided"]))
    for m in r["measures"]:
        if m["type"] != "quick":
            fixes.append({"id": m["id"], "name": m["name"], "cost": None, "hours": round(m["weeks"] * 168) if m.get("weeks") else None, "type": "long-term",
                          "lossAvoided": None, "selected": False, "leftOut": f"takes {m['weeks']:g} weeks" if m.get("weeks") else "takes weeks", "position": None, "source": (m.get("source") or {}).get("url")})
    plan = r["plan"]
    return {
        "property": {"id": property_id, "name": r["name"], "address": r["address"], "value": (r["sale"] or {}).get("price"), "valueBasis": "last recorded sale, CoStar",
                     "sqft": r["sqft"], "homes": r["homes"], "aerialImage": f"/api/buildings/{property_id}/aerial.jpg", "waterImage": f"/api/flood/{property_id}/water.png?water_ft={water_ft:g}"},
        "flood": {"severityFt": water_ft, "hoursBeforeFlood": hours}, "budget": budget,
        "lossBefore": r["do_nothing"]["loss"], "lossAfter": plan["loss"] if plan else r["do_nothing"]["loss"],
        "spent": plan["spent"] if plan else 0, "saved": plan["saved"] if plan else 0, "fixes": fixes,
        "why": r["why"], "tradeoffs": plan["tradeoffs"] if plan else [], "agentSteps": r["research"]["steps"], "workOrder": plan["work_order"] if plan else "",
        "notice": plan["notice"] if plan else "", "assumptions": r["assumptions"],
        "buildings": [{"id": b["id"], "depthFt": b["depth_ft"], "loss": b["loss"], "value": b["value"], "position": at(b["polygon"]),
                       "outline": [{"x": round((p[0] - w) / (e - w), 4), "y": round((n - p[1]) / (n - s_), 4)} for p in b["polygon"]]} for b in r["buildings"]],
    }


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
