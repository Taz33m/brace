"""Registration: putting the indoor scan and the aerial photo in one coordinate frame.

Everything is done in a local east/north frame in metres, centred on the home.
Matterport supplies a starting transform from scan coordinates to GPS. We refine
it with a small shift and rotation so the scanned floor plan sits inside the
building footprint seen from the air.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

M_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class LocalFrame:
    """East/north metres around a reference point. Accurate to centimetres at house scale."""
    lat0: float
    lon0: float

    @property
    def _kx(self) -> float:
        return M_PER_DEG_LAT * math.cos(math.radians(self.lat0))

    def to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lon0) * self._kx, (lat - self.lat0) * M_PER_DEG_LAT

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        return self.lon0 + x / self._kx, self.lat0 + y / M_PER_DEG_LAT

    def polygon_to_xy(self, poly: Polygon) -> Polygon:
        return Polygon([self.to_xy(x, y) for x, y in poly.exterior.coords])

    def polygon_to_lonlat(self, poly: Polygon) -> list[list[float]]:
        return [[round(v, 7) for v in self.to_lonlat(x, y)] for x, y in poly.exterior.coords]


@dataclass
class Transform:
    """2D affine map from scan coordinates to local metres: p' = A @ p + t."""
    a: list[list[float]]
    t: list[float]

    def apply(self, x: float, y: float) -> tuple[float, float]:
        (a, b), (c, d) = self.a
        return a * x + b * y + self.t[0], c * x + d * y + self.t[1]

    def invert(self, x: float, y: float) -> tuple[float, float]:
        m = np.linalg.inv(np.array(self.a))
        v = m @ (np.array([x, y]) - np.array(self.t))
        return float(v[0]), float(v[1])

    def polygon(self, coords: list[list[float]]) -> Polygon:
        return Polygon([self.apply(x, y) for x, y in coords])

    def then_rigid(self, dx: float, dy: float, deg: float, cx: float, cy: float) -> "Transform":
        """Compose with a rotation of `deg` about (cx, cy) followed by a shift (dx, dy)."""
        th = math.radians(deg)
        r = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
        a = r @ np.array(self.a)
        c = np.array([cx, cy])
        t = r @ (np.array(self.t) - c) + c + np.array([dx, dy])
        return Transform(a.tolist(), t.tolist())

    def to_json(self) -> dict:
        return {"a": self.a, "t": self.t}

    @staticmethod
    def from_json(d: dict) -> "Transform":
        return Transform(d["a"], d["t"])


def initial_transform(frame: LocalFrame, origin: list[float], ex10: list[float], ey10: list[float]) -> Transform:
    """Matterport's own registration, from where it places (0,0), (10,0) and (0,10)."""
    o = np.array(frame.to_xy(*origin))
    ex = (np.array(frame.to_xy(*ex10)) - o) / 10.0
    ey = (np.array(frame.to_xy(*ey10)) - o) / 10.0
    return Transform([[float(ex[0]), float(ey[0])], [float(ex[1]), float(ey[1])]], [float(o[0]), float(o[1])])


def _score(plan: Polygon | MultiPolygon, footprint: Polygon) -> tuple[float, float]:
    inter = plan.intersection(footprint).area
    inside = inter / plan.area if plan.area else 0.0
    union = plan.area + footprint.area - inter
    return inside, (inter / union if union else 0.0)


def refine(plan: Polygon | MultiPolygon, footprint: Polygon, max_shift: float = 8.0, max_rot: float = 8.0) -> dict:
    """Find the small shift + rotation that best seats the floor plan inside the footprint.

    `plan` and `footprint` are in local metres. Coarse-to-fine grid search; the
    objective rewards the plan lying inside the footprint, with overlap ratio as
    a tie-breaker so the plan does not float free inside a larger roof outline.
    """
    c = plan.centroid
    before = _score(plan, footprint)

    def moved(dx: float, dy: float, deg: float):
        p = affinity.rotate(plan, deg, origin=(c.x, c.y)) if deg else plan
        return affinity.translate(p, dx, dy) if (dx or dy) else p

    def objective(dx: float, dy: float, deg: float) -> float:
        inside, iou = _score(moved(dx, dy, deg), footprint)
        # A mild pull toward the starting pose keeps equal-scoring answers honest.
        return inside + 0.35 * iou - 0.002 * math.hypot(dx, dy) - 0.0015 * abs(deg)

    best = (objective(0, 0, 0), 0.0, 0.0, 0.0)
    span, rspan = max_shift, max_rot
    centre = (0.0, 0.0, 0.0)
    for step, rstep in ((2.0, 4.0), (0.5, 1.0), (0.125, 0.25)):
        n, rn = int(round(span / step)), int(round(rspan / rstep))
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                for k in range(-rn, rn + 1):
                    dx, dy, deg = centre[0] + i * step, centre[1] + j * step, centre[2] + k * rstep
                    if abs(dx) > max_shift or abs(dy) > max_shift or abs(deg) > max_rot:
                        continue
                    s = objective(dx, dy, deg)
                    if s > best[0]:
                        best = (s, dx, dy, deg)
        centre = best[1:]
        span, rspan = step, rstep
    _, dx, dy, deg = best
    after = _score(moved(dx, dy, deg), footprint)
    return {
        "dx": round(dx, 3), "dy": round(dy, 3), "deg": round(deg, 3),
        "cx": c.x, "cy": c.y,
        "inside_before": round(before[0], 3), "inside_after": round(after[0], 3),
        "iou_before": round(before[1], 3), "iou_after": round(after[1], 3),
    }


def plan_union(polys: list[Polygon]) -> Polygon | MultiPolygon:
    """One shape for the whole scanned floor plan; a small buffer closes the gaps left by walls."""
    return unary_union([p.buffer(0.25) for p in polys if p.is_valid and p.area > 0.2])


def house_part(plan: Polygon | MultiPolygon, footprint: Polygon) -> Polygon | MultiPolygon:
    """The pieces of the floor plan that belong to this building.

    A scan often includes a detached garage or shed. Those pieces sit well outside
    the roof outline even before any correction, so they are left out of the fit;
    wings of the same house (which touch the outline) are kept, because an L-shape
    is what pins down the rotation.
    """
    if not isinstance(plan, MultiPolygon):
        return plan
    near = footprint.buffer(3.0)
    keep = [g for g in plan.geoms if g.intersection(near).area >= 0.5 * g.area]
    if not keep:
        keep = [max(plan.geoms, key=lambda g: g.area)]
    return unary_union(keep)


def largest_polygon(geom) -> Polygon:
    return max(geom.geoms, key=lambda g: g.area) if hasattr(geom, "geoms") else geom


def register(plan: Polygon | MultiPolygon, footprint: Polygon) -> dict:
    """Seat the plan in the footprint and say how far the result can be trusted.

    quality:
      good / fair   the house outline fits the roof outline after a small correction
      loose         the roof outline is much larger than the scanned rooms, so the fit
                    cannot pin the position; Matterport's own GPS placement dominates
      approximate   the roof outline is smaller than the scanned rooms (trees over the
                    roof, or the outline predates the building); no correction applied
      poor          the two outlines disagree
    """
    house = house_part(plan, footprint)
    if footprint.area < 0.8 * house.area:
        inside, iou = _score(house, footprint)
        return {"dx": 0.0, "dy": 0.0, "deg": 0.0, "cx": house.centroid.x, "cy": house.centroid.y,
                "inside_before": round(inside, 3), "inside_after": round(inside, 3),
                "iou_before": round(iou, 3), "iou_after": round(iou, 3), "quality": "approximate"}
    fit = refine(house, footprint)
    if fit["inside_after"] < 0.8:
        fit["quality"] = "poor"
    elif footprint.area > 1.8 * house.area:
        fit["quality"] = "loose"
    elif fit["inside_after"] >= 0.93:
        fit["quality"] = "good"
    else:
        fit["quality"] = "fair"
    return fit


def point_in(poly: Polygon, x: float, y: float) -> bool:
    return poly.contains(Point(x, y))
