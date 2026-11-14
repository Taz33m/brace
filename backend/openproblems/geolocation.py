"""Open problem: better geolocation.

Matterport: "Our scans carry GPS, but it's weak indoors. Aligning to Vexcel's aerial imagery could
pin them down."

What this module measures, for every scan of a cached building:

  before  where Matterport's own geo registration puts the scan's floor plan (its room outlines,
          pushed through `geo.initial_transform`). This is what the app draws today: the cached
          bundle never applies a fit, so "before" is recomputed here from the cached model.
  after   the same floor plan after `geo.register` nudges it (at most 8 m and 8 degrees) so it sits
          under the Vexcel roof outline it belongs to.

The difference between the two is the correction, in metres and degrees.

Two honest limits are carried in the output rather than hidden:

  * An apartment is much smaller than the roof it sits under. The fit can then only say "the unit
    must be under this roof" and push it inside; it cannot say where along the building it is.
    `geo.register` calls that quality "loose". Only "good" and "fair" fits pin the position, and
    the summary counts them separately.
  * A scan with no GPS from Matterport has no starting point. We try to place it by shape alone
    (`match_by_shape`), and only accept an answer that is clearly better than the next best one.
    Many units in a complex share one floor plan, so most of these stay "not placed".

Nothing here touches the network, and nothing is written outside data/cache/open/geolocation/.
"""
from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from .. import geo
from ..config import BUILDINGS_DIR, CACHE_DIR

OUT_DIR = CACHE_DIR / "open" / "geolocation"
MP_CACHE = CACHE_DIR / "matterport"  # same folder backend.matterport caches models in
RESULT_VERSION = 1

# building.py attaches a scan to a structure when its GPS fix is within 15 m of the roof outline.
# The same distance is used here, measured from the floor plan instead of from one point.
MAX_ATTACH_M = 15.0
# geo.refine searches up to this far; a fit that ends on the edge of the search may want to go further.
MAX_SHIFT_M = 8.0
MAX_ROT_DEG = 8.0

# --- heading from wall directions ----------------------------------------------------------------
# geo.register rarely turns a unit: under a roof much bigger than itself, every heading fits. But
# the walls of a unit run parallel to the outer walls of its building, and that can be measured.
# The turn is only trusted when both outlines are clearly built on one square grid, and only
# applied within the same 8 degree limit the existing fit allows itself.
MIN_SQUARENESS = 0.8   # 1.0 = every wall lies on one square grid; an L-shaped wing at 45 degrees scores near 0
MIN_WALL_M = 0.3       # shorter edges are tracing noise, not walls

# A roof outline says nothing about where a pool deck or a car park is, so these are never fitted.
_OUTDOOR = re.compile(r"pool|courtyard|parking|garage|entrance|patio|rooftop|sky ?deck|playground|dog park", re.I)

# --- outline from camera positions ---------------------------------------------------------------
# Some scans come back from Matterport with no room outlines at all. The only shape left is where
# the camera stood. Each camera position is given 1 m of floor around it and the gaps are closed.
# Checked on the 18 cached scans that have both shapes: between 91% and 100% of this shape lay
# inside the real floor plan, and it covered 9% to 92% of the plan's area. So it is a cautious
# under-estimate of the floor plan, never the plan itself, and is always labelled as such.
CAMERA_REACH_M = 1.0
MIN_CAMERAS = 5  # fewer than this and the "shape" is just a few dots

# --- placing a scan by shape alone ---------------------------------------------------------------
# Score = overlap ratio (intersection over union) between the floor plan and a roof outline after
# the best shift and rotation. 1.0 means the two outlines are the same shape in the same place.
MIN_MATCH_SCORE = 0.6     # below this the plan does not resemble the roof; it merely fits inside it
MIN_MATCH_MARGIN = 0.15   # the best match must beat the runner-up by this much, or it is a coin toss
MIN_MATCH_INSIDE = 0.8    # same bar geo.register uses before it calls a fit "poor"
ROTATION_STEP_DEG = 10    # a scan without GPS has no known heading, so every direction is tried
DISTINCT_POSE_DEG = 45    # two poses in one building count as different answers beyond this turn

STATUS_LABEL = {"aligned": "aligned", "raw_gps_only": "raw GPS only", "not_placed": "not placed",
                # Only reachable when a no-GPS scan wins the strict shape match. None of the cached scans does.
                "placed_by_shape": "placed by shape (no GPS)"}


# =================================================================================================
# Pure parts (tested with synthetic shapes)
# =================================================================================================

def measure_correction(raw: geo.Transform, fitted: geo.Transform, at_model_xy: tuple[float, float],
                       corners: list[tuple[float, float]] | None = None) -> dict:
    """How far the fit moved the scan, measured rather than read off the optimiser.

    `raw` and `fitted` both map scan coordinates to local east/north metres. The shift is how far the
    point `at_model_xy` (the middle of the floor plan) travels. The rotation is the turn between the
    two maps, counter-clockwise seen from above. `corners` (scan coordinates) gives the largest move
    of any outline corner, which is what a viewer actually sees when the turn is not zero.
    """
    x0, y0 = raw.apply(*at_model_xy)
    x1, y1 = fitted.apply(*at_model_xy)
    turn = np.array(fitted.a) @ np.linalg.inv(np.array(raw.a))
    deg = math.degrees(math.atan2(turn[1][0], turn[0][0]))
    out = {
        "shift_m": round(math.hypot(x1 - x0, y1 - y0), 2),
        "east_m": round(x1 - x0, 2),
        "north_m": round(y1 - y0, 2),
        "rotation_deg": round(deg, 2) + 0.0,  # "+ 0.0" turns -0.0 into 0.0
    }
    if corners:
        out["max_corner_move_m"] = round(max(
            math.dist(raw.apply(x, y), fitted.apply(x, y)) for x, y in corners), 2)
    return out


def wall_direction(rings: list[list[tuple[float, float]]]) -> tuple[float | None, float]:
    """The direction the walls run, as an angle between -45 and 45 degrees, and how square the shape is.

    Walls at right angles to each other count as the same direction (angles are folded every 90
    degrees), and longer walls count for more. Squareness is 1.0 when every wall lies on one square
    grid and falls toward 0 as directions mix.
    """
    total, sx, sy = 0.0, 0.0, 0.0
    for ring in rings:
        for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
            length = math.hypot(x1 - x0, y1 - y0)
            if length < MIN_WALL_M:
                continue
            a = 4 * math.atan2(y1 - y0, x1 - x0)
            sx, sy, total = sx + length * math.cos(a), sy + length * math.sin(a), total + length
    if not total:
        return None, 0.0
    return math.degrees(math.atan2(sy, sx)) / 4, math.hypot(sx, sy) / total


def heading_correction(plan_rings: list[list[tuple[float, float]]], roof_ring: list[tuple[float, float]]) -> dict:
    """The turn (counter-clockwise, degrees) that makes the floor plan's walls parallel to the roof's edges.

    Always reports what was measured. `applied` is True only when both shapes are clearly square
    and the turn is within the 8 degree limit; a larger disagreement is reported and left alone,
    because past that the walls could just as well belong to a differently oriented building.
    """
    pd, ps = wall_direction(plan_rings)
    rd, rs = wall_direction([roof_ring])
    out = {"plan_wall_deg": None if pd is None else round(pd, 2), "plan_squareness": round(ps, 2),
           "roof_wall_deg": None if rd is None else round(rd, 2), "roof_squareness": round(rs, 2),
           "turn_deg": None, "applied": False, "why": ""}
    if pd is None or rd is None:
        out["why"] = "no walls long enough to measure a direction"
        return out
    turn = (rd - pd + 45) % 90 - 45
    out["turn_deg"] = round(turn, 2) + 0.0
    if ps < MIN_SQUARENESS or rs < MIN_SQUARENESS:
        out["why"] = (f"walls are {abs(turn):.1f} degrees off the roof edges, but one of the two outlines is not square "
                      f"enough to trust that (plan {ps:.2f}, roof {rs:.2f}, need {MIN_SQUARENESS})")
    elif abs(turn) > MAX_ROT_DEG:
        out["why"] = (f"walls are {abs(turn):.1f} degrees off the roof edges, more than the {MAX_ROT_DEG:g} degree turn "
                      "the fit allows, so the heading was left as Matterport gave it")
    else:
        out["applied"] = True
        out["why"] = f"walls were {abs(turn):.1f} degrees off the roof edges and are now parallel to them"
    return out


def camera_outline(points: list[tuple[float, float]]) -> Polygon | None:
    """A cautious floor-plan stand-in drawn from camera positions (see CAMERA_REACH_M)."""
    if len(points) < MIN_CAMERAS:
        return None
    blob = unary_union([Point(x, y).buffer(CAMERA_REACH_M, 4) for x, y in points])
    blob = blob.buffer(1.0, 4).buffer(-1.0, 4)  # close the gaps between neighbouring positions
    poly = geo.largest_polygon(blob).simplify(0.1)
    return poly if poly.is_valid and poly.area > 1.0 else None


def _iou(a, b) -> tuple[float, float]:
    """(share of `a` inside `b`, overlap ratio of the two)."""
    inter = a.intersection(b).area
    union = a.area + b.area - inter
    return (inter / a.area if a.area else 0.0), (inter / union if union else 0.0)


def _turn_between(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def match_by_shape(plan: Polygon | MultiPolygon, footprints: dict[str, Polygon]) -> list[dict]:
    """Score the floor plan against every roof outline, in every direction.

    `plan` is in metres with any position and heading; `footprints` are roof outlines in local
    metres. For each roof the plan is laid over the middle of the outline, turned in 10 degree
    steps, and the two most promising and clearly different headings are polished with the same
    small-shift fit used everywhere else. Returns every candidate, best first. A roof can appear
    twice: a rectangle matches a rectangle just as well turned half way round, and that second
    reading is a real competitor for the first.
    """
    c = plan.centroid
    out: list[dict] = []
    for sid, fp in footprints.items():
        # Shapes can only overlap as much as their areas allow; this is the score's ceiling.
        ceiling = min(plan.area, fp.area) / max(plan.area, fp.area) if plan.area and fp.area else 0.0
        target = fp.centroid if fp.contains(fp.centroid) else fp.representative_point()
        coarse = []
        for deg in range(0, 360, ROTATION_STEP_DEG):
            p = affinity.translate(affinity.rotate(plan, deg, origin=(c.x, c.y)), target.x - c.x, target.y - c.y)
            coarse.append((_iou(p, fp)[1], deg, p))
        coarse.sort(key=lambda r: -r[0])
        picks = [coarse[0]]
        other = next((r for r in coarse[1:] if _turn_between(r[1], coarse[0][1]) >= DISTINCT_POSE_DEG), None)
        if other:
            picks.append(other)
        for _, deg, p in picks:
            fit = geo.refine(p, fp, max_shift=MAX_SHIFT_M, max_rot=ROTATION_STEP_DEG / 2)
            out.append({
                "structure": sid,
                "rotation_deg": round((deg + fit["deg"]) % 360, 2),
                # where the middle of the plan ends up, local metres
                "x": round(target.x + fit["dx"], 2), "y": round(target.y + fit["dy"], 2),
                "score": fit["iou_after"], "inside": fit["inside_after"],
                "score_ceiling": round(ceiling, 3),
            })
    out.sort(key=lambda r: (-r["score"], -r["inside"]))
    return out


def decide_placement(candidates: list[dict], outline_is_floor_plan: bool = True) -> dict:
    """Say whether the best shape match is good enough to call the scan placed.

    Strict on purpose. A unit's floor plan fits under almost any roof on the site, and many units
    share one plan, so "it fits" is not evidence. The scan is placed only when the best candidate
    (a) really has the shape of that roof, (b) clearly beats every other candidate, including the
    same roof read at a different heading, and (c) was scored on a real floor plan. An outline
    drawn from camera positions is smaller than the plan by an unknown amount, so a high score on
    it could be luck; it is scored and reported but never accepted.
    """
    if not candidates:
        return {"placed": False, "best": None, "runner_up": None, "margin": None,
                "why": "there are no roof outlines to match against"}
    ranked = sorted(candidates, key=lambda r: (-r["score"], -r.get("inside", 0.0)))
    best = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None
    margin = round(best["score"] - runner["score"], 3) if runner else None
    out = {"placed": False, "best": best, "runner_up": runner, "margin": margin}
    if best["score"] < MIN_MATCH_SCORE or best.get("inside", 1.0) < MIN_MATCH_INSIDE:
        out["why"] = (f"could not be placed: the best match ({best['structure']}) only scores {best['score']:.3f} "
                      f"against a bar of {MIN_MATCH_SCORE}. The floor plan does not have the shape of any roof "
                      f"outline; at most it fits inside one, and it would fit inside others just as well")
    elif runner is not None and margin < MIN_MATCH_MARGIN:
        out["why"] = (f"could not be placed: too close to call. Best {best['structure']} scores {best['score']:.2f}, "
                      f"runner-up {runner['structure']} scores {runner['score']:.2f}; the gap of {margin:.2f} is under "
                      f"the {MIN_MATCH_MARGIN} needed to tell them apart")
    elif not outline_is_floor_plan:
        out["why"] = (f"could not be placed: {best['structure']} scores {best['score']:.2f} and leads the runner-up, but "
                      "the shape matched was only camera positions, not a floor plan, and that is not enough to accept it")
    else:
        out["placed"] = True
        gap = f"beats the runner-up ({runner['structure']}, {runner['score']:.2f}) by {margin:.2f}" if runner \
            else "is the only roof outline on the site"
        out["why"] = f"placed by shape: {best['structure']} scores {best['score']:.2f} and {gap}"
    return out


def summarise(scans: list[dict]) -> dict:
    """Counts and correction statistics for a list of per-scan results. No rounding beyond 2 places."""
    aligned = [s for s in scans if s["status"] == "aligned"]
    pinned = [s for s in aligned if s["fit_quality"] in ("good", "fair")]
    moved = [s for s in aligned if s["correction"]["shift_m"] > 0 or s["correction"]["rotation_deg"] != 0]
    turned = [abs(s["heading"]["turn_deg"]) for s in aligned if (s.get("heading") or {}).get("applied")]

    def stats(rows: list[dict]) -> dict:
        shifts = [s["correction"]["shift_m"] for s in rows]
        turns = [abs(s["correction"]["rotation_deg"]) for s in rows]
        if not shifts:
            return {"count": 0, "median_shift_m": None, "min_shift_m": None, "max_shift_m": None,
                    "median_abs_rotation_deg": None, "max_abs_rotation_deg": None,
                    "median_inside_before": None, "median_inside_after": None}
        return {
            "count": len(rows),
            "median_shift_m": round(statistics.median(shifts), 2),
            "min_shift_m": min(shifts), "max_shift_m": max(shifts),
            "median_abs_rotation_deg": round(statistics.median(turns), 2),
            "max_abs_rotation_deg": max(turns),
            "median_inside_before": round(statistics.median(s["raw"]["inside"] for s in rows), 3),
            "median_inside_after": round(statistics.median(s["fitted"]["inside"] for s in rows), 3),
        }

    return {
        "scans": len(scans),
        "with_matterport_gps": sum(1 for s in scans if s["has_gps"]),
        "aligned": len(aligned),
        "aligned_position_pinned": len(pinned),          # quality good or fair
        "aligned_under_roof_only": len(aligned) - len(pinned),  # quality loose
        "raw_gps_only": sum(1 for s in scans if s["status"] == "raw_gps_only"),
        "not_placed": sum(1 for s in scans if s["status"] == "not_placed"),
        "placed_by_shape": sum(1 for s in scans if s["status"] == "placed_by_shape"),
        "aligned_building_not_settled": sum(1 for s in aligned if s.get("other_roofs_possible")),
        "heading_corrected": sum(1 for s in aligned if (s.get("heading") or {}).get("applied")),
        "heading_measured_not_applied": sum(1 for s in aligned if (s.get("heading") or {}).get("turn_deg") is not None
                                            and not s["heading"]["applied"]),
        "heading_turn_applied_deg": ({"median": round(statistics.median(turned), 2), "min": min(turned), "max": max(turned)}
                                     if turned else None),
        "moved_by_fit": len(moved),
        "correction_all_aligned": stats(aligned),
        "correction_moved_only": stats(moved),
        "correction_position_pinned": stats(pinned),
        "hit_search_limit": sum(1 for s in aligned if s["correction"].get("at_search_limit")),
    }


# =================================================================================================
# Reading the cache
# =================================================================================================

def _bundle(property_id: int) -> dict:
    """The cached bundle, read as it is. `building.build` is avoided: it rewrites older bundles."""
    path = BUILDINGS_DIR / str(property_id) / "building.json"
    if not path.exists():
        raise FileNotFoundError(f"building {property_id} is not cached")
    return json.loads(path.read_text())


def _model(scan_id: str) -> dict | None:
    path = MP_CACHE / scan_id / "model.json"
    return json.loads(path.read_text()) if path.exists() else None


def cached_property_ids() -> list[int]:
    return sorted(int(p.name) for p in BUILDINGS_DIR.iterdir() if p.name.isdigit() and (p / "building.json").exists())


def _parts(geom) -> list[Polygon]:
    return sorted(geom.geoms, key=lambda g: -g.area) if hasattr(geom, "geoms") else [geom]


def _rings(frame: geo.LocalFrame, geom) -> list[list[list[float]]]:
    return [frame.polygon_to_lonlat(p) for p in _parts(geom)]


def _placed(frame: geo.LocalFrame, plan, footprint: Polygon | None) -> dict:
    """One placement of a floor plan, ready to draw: where its middle is and its outline in lon/lat."""
    rings = _rings(frame, plan)
    lon, lat = frame.to_lonlat(plan.centroid.x, plan.centroid.y)
    out: dict[str, Any] = {"position": [round(lon, 7), round(lat, 7)], "outline": rings[0], "outline_parts": rings,
                           "inside": None, "overlap": None}
    if footprint is not None:
        part = geo.house_part(plan, footprint)  # same pieces geo.register scores
        inside, iou = _iou(part, footprint)
        out["inside"], out["overlap"] = round(inside, 3), round(iou, 3)
    return out


def _pick_structure(plan, footprints: dict[str, Polygon]) -> tuple[str | None, float | None]:
    """The roof outline this floor plan belongs to: the one it overlaps most, else the nearest within 15 m."""
    if not footprints:
        return None, None
    sid, area = max(((k, plan.intersection(fp).area) for k, fp in footprints.items()), key=lambda kv: kv[1])
    if area > 0:
        return sid, 0.0
    sid, dist = min(((k, fp.distance(plan)) for k, fp in footprints.items()), key=lambda kv: kv[1])
    return (sid, round(dist, 1)) if dist <= MAX_ATTACH_M else (None, round(dist, 1))


# =================================================================================================
# One scan
# =================================================================================================

def _scan_result(sc: dict, frame: geo.LocalFrame, footprints: dict[str, Polygon]) -> dict:
    res: dict[str, Any] = {
        "id": sc["id"], "name": sc.get("name") or "Untitled scan",
        "status": "not_placed", "status_label": STATUS_LABEL["not_placed"], "reason": None, "why": "",
        "has_gps": False, "gps_source": None, "outline_source": None,
        "structure": None, "bundle_structure": sc.get("structure"),
        "raw": None, "fitted": None, "correction": None, "fit_quality": None, "position_pinned": False,
        "heading": None, "other_roofs_possible": [], "camera_check": None, "shape_match": None,
    }

    def done(status: str, reason: str, why: str) -> dict:
        res.update(status=status, status_label=STATUS_LABEL[status], reason=reason, why=why)
        return res

    m = _model(sc["id"])
    if m is None:
        return done("not_placed", "not_cached", "the scan's model data is not in the local cache, so nothing could be measured")
    g = m.get("geo") or {}
    has_gps = bool(g.get("origin") and g.get("ex10") and g.get("ey10"))
    res.update(has_gps=has_gps, gps_source=g.get("source"))
    outdoor = bool(_OUTDOOR.search(res["name"]))

    rooms = [r["polygon"] for r in m.get("rooms") or [] if r.get("polygon")]
    cams = [(s["x"], s["y"]) for s in m.get("sweeps") or [] if s.get("has_pano")]
    cam_poly = camera_outline(cams)
    n_rooms = len(m.get("rooms") or [])

    # ---- no GPS: the only hope is shape ----------------------------------------------------------
    if not has_gps:
        base = "Matterport returns no geocoordinates for this scan (no GPS fix was recorded with it)"
        if outdoor:
            return done("not_placed", "no_gps", base + "; it is an outdoor space, which a roof outline cannot locate")
        if rooms:
            plan = geo.plan_union([Polygon(p) for p in rooms])
            res["outline_source"] = "room outlines"
        elif cam_poly is not None:
            plan = cam_poly
            res["outline_source"] = "camera positions"
            base += (f", and no room outlines either ({n_rooms} rooms listed, none with a boundary), so the only "
                     f"shape available is the {len(cams)} camera positions with {CAMERA_REACH_M:g} m of floor around each")
        else:
            return done("not_placed", "no_gps", base + f", no room outlines, and only {len(cams)} camera positions: "
                                             "there is no shape to match")
        cands = match_by_shape(plan, footprints)
        verdict = decide_placement(cands, outline_is_floor_plan=res["outline_source"] == "room outlines")
        best_per = {}
        for cnd in cands:  # candidates are best-first, so the first seen per structure is its best
            best_per.setdefault(cnd["structure"], cnd["score"])
        res["shape_match"] = {
            "placed": verdict["placed"], "best": verdict["best"], "runner_up": verdict["runner_up"],
            "margin": verdict["margin"],
            # the runner-up is often the same roof read half a turn round; this is the next *building*
            "next_structure": next((c for c in cands if verdict["best"] and c["structure"] != verdict["best"]["structure"]), None),
            "plan_area_sqm": round(plan.area, 1),
            "structures_tried": len(footprints), "candidates_scored": len(cands),
            "structures_it_fits_inside": sum(1 for sid in footprints
                                             if any(c["structure"] == sid and c["inside"] >= 0.99 for c in cands)),
            "score_by_structure": best_per,
            "rule": f"placed only if score >= {MIN_MATCH_SCORE}, inside >= {MIN_MATCH_INSIDE}, lead over runner-up "
                    f">= {MIN_MATCH_MARGIN}, and the shape is a real floor plan rather than camera positions",
        }
        if verdict["placed"]:
            b = verdict["best"]
            c = plan.centroid
            moved = affinity.translate(affinity.rotate(plan, b["rotation_deg"], origin=(c.x, c.y)), b["x"] - c.x, b["y"] - c.y)
            res["structure"] = b["structure"]
            res["fitted"] = _placed(frame, moved, footprints[b["structure"]])
        # A shape match is never called "aligned": there was no GPS placement to align.
        return done("placed_by_shape" if verdict["placed"] else "not_placed", "no_gps",
                    base + ". " + verdict["why"][0].upper() + verdict["why"][1:])

    # ---- GPS: Matterport's own placement first ---------------------------------------------------
    t0 = geo.initial_transform(frame, g["origin"], g["ex10"], g["ey10"])
    if rooms:
        plan0 = geo.plan_union([t0.polygon(p) for p in rooms])
        res["outline_source"] = "room outlines"
    elif cam_poly is not None:
        plan0 = t0.polygon([list(p) for p in cam_poly.exterior.coords])
        res["outline_source"] = "camera positions"
    else:
        plan0 = None

    if plan0 is None or plan0.is_empty:
        lon, lat = g["origin"]
        res["raw"] = {"position": [round(lon, 7), round(lat, 7)], "outline": None, "outline_parts": [],
                      "inside": None, "overlap": None}
        return done("raw_gps_only", "no_room_outlines",
                    f"Matterport gives a GPS position but no room outlines ({n_rooms} rooms listed, none "
                                    f"with a boundary) and only {len(cams)} camera positions, so there is no shape to fit")

    sid, gap = _pick_structure(plan0, footprints)
    fp = footprints.get(sid) if sid else None
    res["structure"] = sid
    res["raw"] = _placed(frame, plan0, fp)

    if outdoor:
        return done("raw_gps_only", "outdoor", "outdoor space: a roof outline says nothing about where it is, so no fit was attempted")
    if fp is None:
        where = (f"{gap:g} m from the nearest roof outline cached for this site ({len(footprints)} cached)"
                 if gap is not None else "on a site with no roof outlines")
        return done("raw_gps_only", "too_far_from_any_roof",
                    f"Matterport's GPS puts the floor plan {where}, further than the {MAX_ATTACH_M:g} m allowed to attach "
                    "a scan to a building, so no fit was attempted. Either the GPS is that far off or the building it "
                    "is in is not among the cached outlines; the data cannot tell which")

    # Heading first (walls parallel to the roof edges), then the existing shift fit.
    t_head, plan_head = t0, plan0
    if rooms:
        res["heading"] = heading_correction([[t0.apply(x, y) for x, y in p] for p in rooms], list(fp.exterior.coords))
        if res["heading"]["applied"]:
            c0 = geo.house_part(plan0, fp).centroid
            t_head = t0.then_rigid(0.0, 0.0, res["heading"]["turn_deg"], c0.x, c0.y)
            plan_head = geo.plan_union([t_head.polygon(p) for p in rooms])
    fit = geo.register(plan_head, fp)
    t1 = t_head.then_rigid(fit["dx"], fit["dy"], fit["deg"], fit["cx"], fit["cy"])
    centre = geo.house_part(plan0, fp).centroid  # the shift is measured at the middle of the raw floor plan
    pivot = t0.invert(centre.x, centre.y)
    ring = rooms and [tuple(p) for poly in rooms for p in poly] or list(cam_poly.exterior.coords)
    corr = measure_correction(t0, t1, pivot, corners=ring)
    corr["at_search_limit"] = bool(abs(fit["dx"]) >= MAX_SHIFT_M or abs(fit["dy"]) >= MAX_SHIFT_M
                                   or abs(fit["deg"]) >= MAX_ROT_DEG)

    if res["outline_source"] == "camera positions":
        # Not the floor plan, so it never counts as aligned. It still says something true: how far
        # the camera positions are from being under a roof.
        plan1 = t1.polygon([list(p) for p in cam_poly.exterior.coords])
        res["camera_check"] = {
            "cameras": len(cams),
            "cameras_under_roof_raw": sum(1 for x, y in cams if fp.contains(Point(t0.apply(x, y)))),
            "cameras_under_roof_after": sum(1 for x, y in cams if fp.contains(Point(t1.apply(x, y)))),
            "fit_quality": fit["quality"], "shift_m": corr["shift_m"], "rotation_deg": corr["rotation_deg"],
            "outline_after": _placed(frame, plan1, fp),
        }
        return done("raw_gps_only", "no_room_outlines",
                    f"Matterport gives a GPS position but no room outlines ({n_rooms} rooms listed, none "
                                    "with a boundary), so there is no floor plan to fit to the roof. "
                                    f"{res['camera_check']['cameras_under_roof_raw']} of {len(cams)} camera positions "
                                    f"fall under roof {sid} at the raw GPS placement")

    res["fit_quality"] = fit["quality"]
    if fit["quality"] in ("poor", "approximate"):
        why = ("the floor plan and the roof outline disagree even after the best small correction "
               f"({fit['inside_after']:.0%} of the plan under roof {sid}); the raw GPS placement is kept"
               if fit["quality"] == "poor" else
               f"roof outline {sid} is smaller than the scanned floor plan, so it cannot be used to correct it; "
               "the raw GPS placement is kept")
        return done("raw_gps_only", "fit_rejected", why)

    plan1 = geo.plan_union([t1.polygon(p) for p in rooms])
    res["fitted"] = _placed(frame, plan1, fp)
    res["correction"] = corr
    res["position_pinned"] = fit["quality"] in ("good", "fair")
    # GPS that leaves a unit half outside one roof may leave it within reach of the next roof too.
    # Every other roof the same fit could seat it under is listed, so nobody reads more into the
    # chosen one than the data supports.
    for other, ofp in footprints.items():
        if other == sid or ofp.distance(plan0) > MAX_ATTACH_M:
            continue
        alt = geo.register(plan0, ofp)
        if alt["quality"] not in ("poor", "approximate"):
            res["other_roofs_possible"].append({
                "structure": other, "shift_m": round(math.hypot(alt["dx"], alt["dy"]), 2),
                "inside_after": alt["inside_after"], "fit_quality": alt["quality"]})
    moved = corr["shift_m"] > 0 or corr["rotation_deg"] != 0
    change = (f"moved {corr['shift_m']:g} m and turned {corr['rotation_deg']:g} degrees" if moved
              else "no move needed: the raw GPS placement already sits under the roof")
    if res["heading"] and res["heading"]["turn_deg"] is not None:
        change += f" ({res['heading']['why']})"
    if fit["quality"] == "loose":
        why = (f"{change}; {res['fitted']['inside']:.0%} of the floor plan is now under roof {sid} "
               f"(was {res['raw']['inside']:.0%}). The roof is much larger than this unit, so the fit only proves the "
               "unit is under it; where along the building it sits still rests on Matterport's GPS")
    else:
        why = (f"{change}; the floor plan outline matches roof {sid} ({res['fitted']['inside']:.0%} under the roof, "
               f"was {res['raw']['inside']:.0%}; fit quality {fit['quality']})")
    if corr["at_search_limit"]:
        why += ". The fit stopped at the edge of its search, so the true correction may be larger"
    if res["other_roofs_possible"]:
        alts = ", ".join(f"{o['structure']} with a {o['shift_m']:g} m move" for o in res["other_roofs_possible"])
        why += (f". {sid} was chosen because the raw placement overlaps it most, but the unit could also be seated "
                f"under {alts}, so which building it is in is not settled by the fit")
    return done("aligned", "fitted", why)


# =================================================================================================
# Public
# =================================================================================================

def alignment(property_id: int, refresh: bool = False) -> dict:
    """Per-scan GPS-versus-roof alignment for one cached building.

    Returns {"property_id", "name", "scans": [...], "summary": {...}, ...}. Each scan carries its
    status, the raw and fitted placement (position, lon/lat outline, share of the plan under the
    roof), the correction in metres and degrees, and, for scans without GPS, the shape-match scores.
    The result is saved to data/cache/open/geolocation/<property_id>.json and reused next time.
    """
    out_path = OUT_DIR / f"{int(property_id)}.json"
    if out_path.exists() and not refresh:
        cached = json.loads(out_path.read_text())
        if cached.get("version") == RESULT_VERSION:
            return cached
    b = _bundle(int(property_id))
    frame = geo.LocalFrame(**b["frame"])
    footprints = {s["id"]: frame.polygon_to_xy(Polygon(s["polygon"])) for s in b["structures"]}
    scans = [_scan_result(sc, frame, footprints) for sc in b["scans"]]
    out = {
        "version": RESULT_VERSION,
        "property_id": int(property_id),
        "name": (b.get("record") or {}).get("name"),
        "frame": b["frame"],
        "structures": len(footprints),
        "method": {
            "before": "Matterport's own geo registration of the scan (geocoordinates.geoLocationOf), applied to its room outlines",
            "after": f"the same outline after a shift of at most {MAX_SHIFT_M:g} m and a turn of at most {MAX_ROT_DEG:g} "
                     "degrees that best seats it under the Vexcel roof outline (backend.geo.register)",
            "inside": "share of the floor plan's area that lies under the roof outline",
            "overlap": "intersection over union of floor plan and roof outline",
            "rotation": "degrees, counter-clockwise seen from above; it comes from making the unit's walls parallel "
                        "to the roof's edges, applied only when both are square and the turn is within the limit",
            "limit": "under a roof much larger than the unit (fit quality 'loose') the fit proves the unit is under "
                     "that roof and fixes its heading; it does not fix where along the building the unit sits",
        },
        "scans": scans,
        "summary": summarise(scans),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1))
    return out


def summary(property_ids: list[int] | None = None, refresh: bool = False) -> dict:
    """The same counts across every cached building, saved to data/cache/open/geolocation/summary.json."""
    ids = property_ids or cached_property_ids()
    results = [alignment(pid, refresh=refresh) for pid in ids]
    every = [s for r in results for s in r["scans"]]
    out = {
        "version": RESULT_VERSION,
        "buildings": len(results),
        "property_ids": [r["property_id"] for r in results],
        **summarise(every),
        "not_placed_reasons": {
            "no_gps_from_matterport": sum(1 for s in every if s["reason"] == "no_gps"),
            "shape_match_attempted": sum(1 for s in every if s.get("shape_match")),
            "shape_match_accepted": sum(1 for s in every if s["status"] == "placed_by_shape"),
        },
        "raw_gps_only_reasons": {r: sum(1 for s in every if s["status"] == "raw_gps_only" and s["reason"] == r)
                                 for r in ("no_room_outlines", "outdoor", "too_far_from_any_roof", "fit_rejected")},
        "by_building": [{"property_id": r["property_id"], "name": r["name"], **{
            k: r["summary"][k] for k in ("scans", "with_matterport_gps", "aligned", "aligned_position_pinned",
                                         "raw_gps_only", "not_placed", "placed_by_shape")}}
            for r in results],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(out, indent=1))
    return out


def render_proof(property_id: int, refresh: bool = False) -> Path:
    """The aerial photo with each scan's floor plan where raw GPS put it and where the fit put it.

    Writes <property_id>_proof.png (the whole site) and, when any scan has an outline, a second
    picture <property_id>_proof_zoom.png with a close-up of each one. Returns the first path.
    """
    from PIL import Image, ImageDraw

    from ..building import Site, _font, _text  # imported here so the pure parts need no imaging stack

    res = alignment(property_id, refresh=refresh)
    site = Site(_bundle(int(property_id)))  # not Site.load: that can rewrite an older bundle
    base = site.render_aerial(grid=False, labels=True)
    z = 3  # draw on an enlarged copy so thin outlines stay crisp in the close-ups
    im = base.resize((base.width * z, base.height * z), Image.LANCZOS)
    k = im.width / site.size[0]
    d = ImageDraw.Draw(im, "RGBA")
    font = _font(max(26, round(im.width / 90)))
    RAW, FIT, NOFIT, ROOF = (255, 45, 85, 255), (0, 229, 255, 255), (255, 149, 0, 255), (255, 204, 0, 255)
    w = max(4, round(im.width / 500))

    def px(lon, lat):
        x, y = site.to_px(lon, lat)
        return x * k, y * k

    def ring(points, colour, fill=None):
        pts = [px(lon, lat) for lon, lat in points]
        if fill:
            d.polygon(pts, fill=fill)
        d.line(pts + pts[:1], fill=colour, width=w, joint="curve")

    boxes = []  # one close-up per scan that has an outline
    for s in res["scans"]:
        raw, fit = s.get("raw") or {}, s.get("fitted") or {}
        aligned = s["status"] == "aligned"
        for r in fit.get("outline_parts") or []:
            ring(r, FIT, fill=(0, 229, 255, 60))
        for r in raw.get("outline_parts") or []:  # drawn last so the raw placement is never hidden
            ring(r, RAW if aligned else NOFIT)
        at = (fit or raw).get("position")
        if not at:
            continue
        x, y = px(*at)
        if not raw.get("outline_parts"):  # a GPS fix with no shape: mark the spot
            d.ellipse([x - 2 * w, y - 2 * w, x + 2 * w, y + 2 * w], fill=NOFIT, outline=(0, 0, 0, 255))
        label = s["id"][:4]
        tw = d.textlength(label, font=font)
        d.rectangle([x + 3 * w, y + 3 * w, x + 3 * w + tw + 8, y + 3 * w + font.size + 6], fill=(0, 0, 0, 170))
        _text(d, (x + 3 * w + 4, y + 3 * w + 2), label, font, FIT if aligned else NOFIT)
        pts = [px(*p) for r in (raw.get("outline_parts") or []) + (fit.get("outline_parts") or []) for p in r]
        if pts:
            boxes.append((s, min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)))

    rows = [(RAW, "floor plan where Matterport GPS puts it"),
            (FIT, "same plan after fitting to the Vexcel roof outline"),
            (NOFIT, "GPS only, not fitted (no room outlines, outdoor, or no roof in reach)"),
            (ROOF, "Vexcel roof outlines (S1, S2, ...)")]
    n = res["summary"]
    title = (f"{res['name']}: {n['scans']} scans, {n['aligned']} fitted to a roof, "
             f"{n['raw_gps_only']} GPS only, {n['not_placed']} not placed (no GPS)")
    lh = font.size + 14
    bw = max([d.textlength(t, font=font) + 90 for _, t in rows] + [d.textlength(title, font=font) + 30])
    d.rectangle([16, 16, 16 + bw, 30 + lh * (len(rows) + 1)], fill=(0, 0, 0, 200))
    _text(d, (30, 24), title, font, (255, 255, 255, 255))
    for i, (col, label) in enumerate(rows):
        y = 26 + lh * (i + 1)
        d.line([(30, y + font.size / 2), (80, y + font.size / 2)], fill=col, width=w + 2)
        _text(d, (94, y), label, font, (255, 255, 255, 255))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{int(property_id)}_proof.png"
    full = im.resize((round(im.width * 1600 / max(im.size)), round(im.height * 1600 / max(im.size))), Image.LANCZOS) \
        if max(im.size) > 1600 else im
    full.save(path)

    if boxes:
        tile, pad = 640, 12.0 * k / _metres_per_px(site)  # 12 m of context around each outline
        cols = min(3, len(boxes))
        sheet = Image.new("RGB", (cols * tile, math.ceil(len(boxes) / cols) * tile), (20, 20, 20))
        sd = ImageDraw.Draw(sheet, "RGBA")
        small = _font(20)
        for i, (s, x0, y0, x1, y1) in enumerate(boxes):
            half = max(x1 - x0, y1 - y0) / 2 + pad
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            crop = im.crop((round(cx - half), round(cy - half), round(cx + half), round(cy + half))).resize((tile, tile), Image.LANCZOS)
            ox, oy = (i % cols) * tile, (i // cols) * tile
            sheet.paste(crop, (ox, oy))
            c = s.get("correction")
            cap = f"{s['id']}  {s['name']}"
            sub = (f"moved {c['shift_m']:g} m: {s['raw']['inside']:.0%} -> {s['fitted']['inside']:.0%} under roof {s['structure']}"
                   if c else f"{s['status_label']}, not fitted")
            sd.rectangle([ox, oy + tile - 58, ox + tile, oy + tile], fill=(0, 0, 0, 190))
            _text(sd, (ox + 8, oy + tile - 54), cap, small, (255, 255, 255, 255))
            _text(sd, (ox + 8, oy + tile - 28), sub, small, FIT if c else NOFIT)
            sd.rectangle([ox, oy, ox + tile - 1, oy + tile - 1], outline=(255, 255, 255, 120))
        sheet.save(OUT_DIR / f"{int(property_id)}_proof_zoom.png")
    return path


def _metres_per_px(site) -> float:
    """Ground size of one pixel of the stored aerial photo."""
    w, s_, e, n = site.bounds
    return (n - s_) * geo.M_PER_DEG_LAT / site.size[1]
