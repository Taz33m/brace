"""Exposure: which of a property's buildings stand most open to a fire arriving from outside.

Three facts for each building, each from a named source, and one order made from them:

    fire zone                    the fire hazard severity zone at the building's centre       CAL FIRE
    vegetation at the wall       the share of its walls with vegetation within 5 ft           Vexcel
    tree cover over the roof     the share of its roof under tree canopy                      Vexcel

Buildings are ordered by zone, then vegetation at the wall, then tree cover over the roof. That is an ordering of
exposure and nothing more: it is not a chance of fire and nothing here is weighted or scored. A fact that is not
known is null and sorts after every known one. Only files already on disk are read.
"""
from __future__ import annotations

import json

from .config import BUILDINGS_DIR

BUILDINGS = BUILDINGS_DIR
ZONE_RANK = {"Very High": 3, "High": 2, "Moderate": 1}
SOURCES = {"vegetation": "Vexcel, measured from its aerial survey", "fire_zone": "CAL FIRE fire hazard severity zones, the map in force today"}
HOW = ("Buildings are ordered by fire hazard severity zone (CAL FIRE), then by the share of their walls with vegetation within 5 ft, "
       "then by tree cover over the roof (both Vexcel). It is an ordering of exposure, not a chance of fire.")


class ExposureError(Exception):
    pass


def zone_at(lat: float, lon: float) -> tuple[str | None, bool]:
    """The fire hazard severity zone at a point, and whether the map was there to be read. Never downloads."""
    try:
        from .hazards import static
        la = static._load_la(allow_download=False)
        if la is None:
            return None, False
        return static.la_fire_lookup(lat, lon, la)["fire_zone"], True
    except Exception:      # a map that cannot be read is a map we do not have
        return None, False


def exposure(property_id: int) -> dict:
    """Every building at a property with its three facts and its place in the order."""
    try:
        bundle = json.loads((BUILDINGS / str(property_id) / "building.json").read_text())
    except (OSError, ValueError):
        raise ExposureError("this property has not been gathered")
    rows = []
    for n, s in enumerate(bundle.get("structures") or []):
        centre = s.get("centroid")
        zone, mapped = zone_at(centre[1], centre[0]) if centre else (None, False)
        rows.append({"id": s["id"], "brush_within_5ft_percent": s.get("trees_within_5ft_percent"), "tree_cover_over_roof_percent": s.get("roof_tree_cover_percent"),
                     "fire_zone": zone, "in_fire_zone": (zone is not None) if mapped else None, "polygon": s.get("polygon"), "footprint_sqft": s.get("footprint_sqft"), "_n": n})
    known = lambda v: v if v is not None else -1.0
    rows.sort(key=lambda r: (-ZONE_RANK.get(r["fire_zone"] or "", 0), -known(r["brush_within_5ft_percent"]), -known(r["tree_cover_over_roof_percent"]), r.pop("_n")))
    return {"property_id": property_id, "buildings": [{"id": r["id"], "exposure_rank": i, **{k: v for k, v in r.items() if k != "id"}} for i, r in enumerate(rows, 1)],
            "how": HOW, "sources": SOURCES}
