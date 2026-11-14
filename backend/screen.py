"""Portfolio screening: which buildings a forecast touches, and why each one is on the list.

No model calls. For every building in the threatened metro it combines the forecast at
that point, standing flood or fire zoning, and what the aerial analysis says about the
roof and its surroundings. The ordering exists to decide where the agent looks first;
the product shows the reasons, never a score.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

from . import hazards, portfolio, vexcel
from .config import CACHE_DIR

FACTS = CACHE_DIR / "site_facts.json"
MIN_STRUCTURE_SQFT = 1200  # ignore sheds and kiosks when summarising a site
SERIOUS = ("missing-material", "tarp", "structural-damage")
STATE = {"Houston": "TX", "Los Angeles": "CA"}


def _site_facts(attrs: dict) -> dict:
    ss = [s for s in attrs.get("structures") or [] if (s.get("footprint.area") or 0) >= MIN_STRUCTURE_SQFT] or (attrs.get("structures") or [])
    cond = [s["roof-characteristics.condition"] for s in ss if s.get("roof-characteristics.condition") is not None]

    def total(key: str) -> int:
        return int(sum(s.get(key) or 0 for s in ss))

    def peak(key: str) -> float:
        # Vexcel occasionally reports cover above 100% where canopies overlap; cap it.
        return min(100.0, max([s.get(key) or 0 for s in ss], default=0))

    return {
        "structures": len(ss),
        "roof_sqft": round(sum(s.get("footprint.area") or 0 for s in ss)),
        "worst_roof": min(cond) if cond else None,
        "serious_defects": sorted({d for s in ss for d in SERIOUS if s.get(f"roof-defects.{d}.detected")}),
        "ponding": any(s.get("roof-defects.discoloration.types.water-pooling.detected") for s in ss),
        "rooftop_units": total("roof-objects.ac-unit.count"),
        "skylights": total("roof-objects.skylight.count"),
        "solar": any(s.get("roof-objects.solar.value") for s in ss),
        "materials": sorted({s.get("roof-characteristics.material.class") for s in ss if s.get("roof-characteristics.material.class")}),
        "roof_tree_cover": peak("roof-characteristics.tree-cover.percent"),
        "trees_within_5ft": peak("defensible-space.zone1-tree"),
        "trees_5_to_30ft": peak("defensible-space.zone2-tree"),
    }


@lru_cache(maxsize=1)
def site_facts() -> dict[str, dict]:
    """Aerial summary per building id, from the cached parcel records. Rebuilt when more parcels are cached."""
    have = sum(1 for _ in (vexcel.VX_CACHE / "parcel").glob("*.json")) if (vexcel.VX_CACHE / "parcel").exists() else 0
    if FACTS.exists():
        data = json.loads(FACTS.read_text())
        if data.get("parcels") == have:
            return data["facts"]
    facts: dict[str, dict] = {}
    for b in portfolio.buildings():
        path = vexcel.VX_CACHE / "parcel" / f"{b['lat']:.6f}_{b['lon']:.6f}.json"
        if not path.exists():
            continue
        par = json.loads(path.read_text())
        if par:
            facts[str(b["id"])] = _site_facts(par["attributes"])
    FACTS.write_text(json.dumps({"parcels": have, "facts": facts}))
    return facts


def signals(kind: str, b: dict, f: dict | None, static: dict | None) -> list[dict]:
    """Why this building is vulnerable to this kind of threat: [{text, weight}], heaviest first."""
    out: list[dict] = []

    def add(weight: float, text: str) -> None:
        out.append({"text": text, "weight": weight})

    f = f or {}
    fema = (static or {}).get("fema") or {}
    if kind == "hurricane":
        if fema.get("floodway"):
            add(3, "in the regulatory floodway")
        elif fema.get("high_risk"):
            add(2, f"in a high-risk flood zone ({fema.get('zone')})")
        elif "0.2" in (fema.get("subtype") or ""):
            add(1, "in the 500-year flood zone")
        if f.get("worst_roof") is not None and f["worst_roof"] <= 2:
            add(2, f"roof condition {f['worst_roof']:.0f} of 5")
        for d in f.get("serious_defects", []):
            add(2, {"missing-material": "roof covering missing in places", "tarp": "tarp on the roof",
                    "structural-damage": "roof structural damage flagged"}[d])
        if f.get("rooftop_units", 0) >= 4:
            add(1, f"{f['rooftop_units']} rooftop units")
        if f.get("roof_tree_cover", 0) >= 10:
            add(1, f"trees over {f['roof_tree_cover']:.0f}% of a roof")
        if f.get("skylights", 0) >= 2:
            add(0.5, f"{f['skylights']} skylights")
        if f.get("ponding"):
            add(0.5, "water ponding on a flat roof")
        if b.get("construction") == "WoodFrame":
            add(1, "wood-frame construction")
        if b.get("year_built") and b["year_built"] < 2000:
            add(0.5, f"built {b['year_built']}, before modern wind codes")
    else:
        zone = (static or {}).get("fire_zone")
        if zone:
            add({"Very High": 3, "High": 2, "Moderate": 1}.get(zone, 1), f"{zone.lower()} fire hazard severity zone")
        km = (static or {}).get("km_to_past_fire")
        if km is not None and km <= 2:
            add(1, f"{km:.1f} km from a past fire perimeter")
        if f.get("trees_within_5ft", 0) >= 15:
            add(2, f"vegetation within 5 ft of the walls ({f['trees_within_5ft']:.0f}% cover)")
        if f.get("roof_tree_cover", 0) >= 10:
            add(1.5, f"trees over {f['roof_tree_cover']:.0f}% of a roof")
        if f.get("trees_5_to_30ft", 0) >= 35:
            add(1, f"dense vegetation 5 to 30 ft out ({f['trees_5_to_30ft']:.0f}% cover)")
        if b.get("construction") == "WoodFrame":
            add(1.5, "wood-frame construction")
        if b.get("year_built") and b["year_built"] < 2008:
            add(0.5, f"built {b['year_built']}, before ember-resistant building rules")
        if any(m in ("shingle", "wood") for m in f.get("materials", [])):
            add(0.5, "shingle roofing")
    return sorted(out, key=lambda s: -s["weight"])


def as_of(sc: dict, static: dict | None) -> dict | None:
    """Standing risk as it was known when the scenario's forecast was issued.

    The fire-perimeter data includes the January 2025 fires. In a replay of the
    warning that preceded them, that would be hindsight, so the distance to a past
    fire falls back to fires before 2025 and the fire's name is dropped.
    """
    if not static or sc.get("live") or sc.get("kind") != "wildfire":
        return static
    out = {k: v for k, v in static.items() if k not in ("past_fire", "fire_before_2025")}
    out["km_to_past_fire"] = static.get("km_to_fire_before_2025")
    return out


def _exposure_weight(e: dict) -> float:
    if e["kind"] == "hurricane":
        return {"hurricane": 3.0, "strong tropical storm": 2.0, "tropical storm": 1.0}.get(e.get("wind_band"), 0.0)
    return 2.0 if e.get("in_warning") else 0.0


def hours_left(e: dict) -> float | None:
    """Hours until damaging conditions reach the site, from the forecast step's issue time."""
    return e.get("hours_until_tropical_storm_wind") if e["kind"] == "hurricane" else e.get("hours_until_warning")


def _people(b: dict) -> float:
    """A rough size-of-consequence factor: homes, tenants and floor area all count."""
    return 1 + math.log10(1 + (b.get("units") or 0) + 10 * (b.get("tenant_count") or 0) + (b.get("gba_sqft") or 0) / 2000)


@lru_cache(maxsize=32)
def rank(scenario_id: str, step_id: str | None = None) -> list[dict]:
    """Every building the forecast touches at this step, most pressing first."""
    sc = next(s for s in hazards.scenarios() if s["id"] == scenario_id)
    facts = site_facts()
    rows = []
    for b in portfolio.buildings():
        if b["state"] != STATE.get(sc["city"]):
            continue
        e = hazards.exposure(scenario_id, b["lat"], b["lon"], step_id)
        w = _exposure_weight(e)
        if w <= 0:
            continue
        static = as_of(sc, hazards.static_risk(b["lat"], b["lon"], cached_only=True))
        sig = signals(sc["kind"], b, facts.get(str(b["id"])), static)
        vuln = sum(s["weight"] for s in sig)
        rows.append({
            "id": b["id"], "name": b["name"], "address": b["address"], "city": b["city"], "lat": b["lat"], "lon": b["lon"],
            "type_label": b["type_label"], "units": b.get("units"), "stories": b.get("stories"), "year_built": b.get("year_built"),
            "tenant_count": b.get("tenant_count"), "manager": b["contacts"].get("manager"), "owner": b["contacts"].get("owner"),
            "photo": b.get("photo"), "scans": len(b["model_ids"]), "last_sale": b.get("last_sale"),
            "exposure": e, "hours_left": hours_left(e), "reasons": [s["text"] for s in sig],
            "_order": w * (1 + vuln) * _people(b),
        })
    rows.sort(key=lambda r: -r["_order"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        del r["_order"]
    return rows


def threat_for(scenario_id: str, step_id: str | None, b: dict) -> dict:
    """The threat as the agent sees it for one building."""
    sc = next(s for s in hazards.scenarios() if s["id"] == scenario_id)
    step = next((s for s in sc["steps"] if s["id"] == step_id), sc["steps"][-1] if sc["steps"] else {})
    e = hazards.exposure(scenario_id, b["lat"], b["lon"], step.get("id"))
    notes = {
        "hurricane": "Wind figures are sustained winds estimated from the forecast's wind radii; gusts run roughly 20 to 30 percent higher. "
                     "The forecast cone shows uncertainty in the centre's track only, so being outside it is not a sign of safety.",
        "wildfire": "A Red Flag Warning means wind and dryness that let any fire spread fast. It does not mean a fire is burning.",
    }
    return {
        "scenario_id": scenario_id, "step_id": step.get("id"), "kind": sc["kind"], "name": sc["name"],
        "label": step.get("label"), "forecast_issued": step.get("issued"), "replay": not sc.get("live"),
        "at_this_site": e, "hours_left": hours_left(e),
        "standing_risk": as_of(sc, hazards.static_risk(b["lat"], b["lon"])),
        "note": notes[sc["kind"]],
    }
