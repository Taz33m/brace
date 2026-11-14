"""Wind at a point from an NHC forecast advisory. Pure maths, no network.

Method (kept simple on purpose)
-------------------------------
An NHC forecast advisory gives, for "now" and for each forecast time, the storm
centre, the maximum sustained wind, and how far 34, 50 and 64 kt winds reach
from the centre in each quadrant (NE, SE, SW, NW), in nautical miles. Each
radius is the LARGEST reach expected anywhere in that quadrant.

1. The track is sampled every 10 minutes. Centre position, maximum wind and
   every quadrant radius are interpolated linearly in time between the
   advisory's points. A radius that is absent at a forecast point counts as 0.
2. For a building, at each sample we take its distance and bearing from the
   centre, pick the quadrant by bearing, and compare the distance with that
   quadrant's radii. Inside the 64 kt radius means hurricane-force wind, inside
   the 50 kt radius strong tropical storm, inside the 34 kt radius tropical
   storm force.
3. To report one number, wind is interpolated linearly between the thresholds:
   34 kt at the 34 kt radius rising to 50 kt at the 50 kt radius, and so on.
   Inside the innermost radius it rises toward the storm's maximum wind at the
   centre. If the advisory says a threshold does not reach into a quadrant
   (radius 0) the estimate stays below that threshold there. If the advisory
   gives no radii at all for a threshold the storm exceeds (NHC only forecasts
   64 kt radii to 48 hours and 34/50 kt radii to 72 hours) the rise is allowed
   to continue up to the maximum wind.
4. Outside the 34 kt radius there is no forecast information. We report a rough
   figure that decays with the square root of distance and is capped just below
   34 kt, and label it as an extrapolation.

Limits to keep in mind
----------------------
* Sustained wind over open terrain, not gusts. Gusts run roughly 20-30% higher.
* Quadrant radii are maximum extents, so this leans high near the edge of a
  quadrant, and it steps where two quadrants with different radii meet.
* This is one forecast. It carries no track or intensity uncertainty; the cone
  is the only uncertainty information, and it covers the centre track only.
* Forecast points are 12 hours apart (24 beyond day 3), so a storm that
  strengthens or weakens quickly between two points is smoothed.
* No allowance for terrain, buildings or the faster decay of wind over land
  beyond what the forecast points themselves show.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .util import KT_TO_MPH, NM_TO_KM

QUADRANTS = ("NE", "SE", "SW", "NW")
THRESHOLDS = (34, 50, 64)
SAMPLE_MINUTES = 10.0
_FALLBACK_SCALE_NM = 30.0  # only used where a storm has no 34 kt radius at all

BASIS_TEXT = {
    64: "inside the forecast 64 kt wind radius",
    50: "inside the forecast 50 kt wind radius",
    34: "inside the forecast 34 kt wind radius",
    0: "outside the forecast 34 kt wind radius (rough extrapolation)",
}


@dataclass(frozen=True)
class Samples:
    """A forecast track resampled at a fixed time step (all arrays length n)."""
    t: np.ndarray          # hours from the advisory issue time
    lat: np.ndarray
    lon: np.ndarray
    vmax: np.ndarray       # kt
    r34: np.ndarray        # (n, 4) nautical miles, quadrant order NE SE SW NW
    r50: np.ndarray
    r64: np.ndarray
    unk50: np.ndarray      # True where the advisory gives no 50 kt radii although vmax >= 50
    unk64: np.ndarray
    head_e: np.ndarray     # direction of motion (east, north components)
    head_n: np.ndarray


def wind_band(kt: float) -> str:
    if kt >= 64:
        return "hurricane"
    if kt >= 50:
        return "strong tropical storm"
    if kt >= 34:
        return "tropical storm"
    return "below tropical storm"


def build_samples(points: list[dict], step_minutes: float = SAMPLE_MINUTES) -> Samples:
    """Resample advisory track points (see nhc.parse_forecast_advisory) in time."""
    pts = sorted(points, key=lambda p: p["hours_from_issue"])
    if not pts:
        raise ValueError("no track points")
    tp = np.array([p["hours_from_issue"] for p in pts], dtype=float)
    latp = np.array([p["lat"] for p in pts], dtype=float)
    lonp = np.array([p["lon"] for p in pts], dtype=float)
    vp = np.array([p["wind_kt"] for p in pts], dtype=float)

    def radii(threshold: int) -> tuple[np.ndarray, np.ndarray]:
        vals = np.zeros((len(pts), 4))
        unknown = np.zeros(len(pts), dtype=bool)
        for i, p in enumerate(pts):
            r = (p.get("radii") or {}).get(str(threshold))
            if r is not None:
                vals[i] = r
            elif p["wind_kt"] >= threshold:
                unknown[i] = True
        return vals, unknown

    r34p, _ = radii(34)
    r50p, unk50p = radii(50)
    r64p, unk64p = radii(64)

    if len(pts) == 1:
        ts = tp.copy()
    else:
        grid = np.arange(tp[0], tp[-1] + 1e-9, step_minutes / 60.0)
        ts = np.unique(np.concatenate([grid, tp]))
    seg = np.clip(np.searchsorted(tp, ts, side="right") - 1, 0, max(len(pts) - 2, 0))

    def interp(col: np.ndarray) -> np.ndarray:
        return np.interp(ts, tp, col)

    def interp4(mat: np.ndarray) -> np.ndarray:
        return np.stack([np.interp(ts, tp, mat[:, q]) for q in range(4)], axis=1)

    def either(flags: np.ndarray) -> np.ndarray:
        if len(pts) == 1:
            return flags[seg]
        return flags[seg] | flags[seg + 1]

    # Direction of motion per segment, carried over stalls.
    head_e = np.zeros(len(pts))
    head_n = np.ones(len(pts))
    last = (0.0, 1.0)
    for i in range(len(pts) - 1):
        de = (lonp[i + 1] - lonp[i]) * np.cos(np.radians((latp[i] + latp[i + 1]) / 2))
        dn = latp[i + 1] - latp[i]
        if abs(de) + abs(dn) > 1e-9:
            last = (float(de), float(dn))
        head_e[i], head_n[i] = last
    if len(pts) > 1:
        head_e[-1], head_n[-1] = head_e[-2], head_n[-2]

    return Samples(
        t=ts, lat=interp(latp), lon=interp(lonp), vmax=interp(vp),
        r34=interp4(r34p), r50=interp4(r50p), r64=interp4(r64p),
        unk50=either(unk50p), unk64=either(unk64p),
        head_e=head_e[seg], head_n=head_n[seg],
    )


def effective_radii(s: Samples) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Quadrant radii (n, 4) with a threshold dropped wherever the storm is weaker than it."""
    v = s.vmax[:, None]
    r64 = np.where(v >= 64, s.r64, 0.0)
    r50 = np.maximum(np.where(v >= 50, s.r50, 0.0), r64)
    r34 = np.maximum(np.where(v >= 34, s.r34, 0.0), r50)
    return r34, r50, r64


def wind_series(s: Samples, lat: float, lon: float) -> dict[str, np.ndarray]:
    """Estimated sustained wind (kt) at the point for every sample, plus working arrays."""
    dy = (lat - s.lat) * 60.0
    dx = (lon - s.lon) * 60.0 * np.cos(np.radians((lat + s.lat) / 2.0))
    d = np.hypot(dx, dy)                                   # nautical miles
    quad = np.where(dx >= 0, np.where(dy >= 0, 0, 1), np.where(dy < 0, 2, 3))
    rows = np.arange(len(s.t))
    e34, e50, e64 = effective_radii(s)
    r34, r50, r64 = e34[rows, quad], e50[rows, quad], e64[rows, quad]
    v = s.vmax
    tiny = 1e-6

    in64 = (r64 > 0) & (d <= r64)
    in50 = ~in64 & (r50 > 0) & (d <= r50)
    in34 = ~in64 & ~in50 & (r34 > 0) & (d <= r34)

    w64 = 64.0 + (v - 64.0) * (1.0 - d / np.maximum(r64, tiny))
    top50 = np.maximum(50.0, np.where(r64 > 0, 64.0, np.where(s.unk64, v, np.minimum(v, 63.9))))
    w50 = 50.0 + (top50 - 50.0) * (r50 - d) / np.maximum(r50 - r64, tiny)
    top34 = np.maximum(34.0, np.where(r50 > 0, 50.0, np.where(s.unk50, v, np.minimum(v, 49.9))))
    w34 = 34.0 + (top34 - 34.0) * (r34 - d) / np.maximum(r34 - r50, tiny)

    widest = e34.max(axis=1)
    ref = np.where(r34 > 0, r34, np.where(widest > 0, widest, _FALLBACK_SCALE_NM))
    base = np.where(r34 > 0, 34.0, np.minimum(v, 33.9))
    wout = np.minimum(33.9, base * np.sqrt(ref / np.maximum(d, ref)))

    wind = np.select([in64, in50, in34], [w64, w50, w34], default=wout)
    basis = np.select([in64, in50, in34], [64, 50, 34], default=0)
    return {"wind": wind, "basis": basis, "dist_nm": d, "dx": dx, "dy": dy}


def point_exposure(s: Samples, lat: float, lon: float) -> dict:
    """Peak wind, arrival of tropical-storm-force wind and closest approach for one point.

    Times are hours from the advisory issue time. See the module docstring for
    the method and its limits.
    """
    series = wind_series(s, lat, lon)
    wind, d = series["wind"], series["dist_nm"]
    k = int(np.argmax(wind))
    peak = float(wind[k])
    peak_kt = int(np.floor(round(peak, 3)))  # whole knots, rounded down so the number never overstates the band

    inside = series["basis"] > 0
    first = int(np.argmax(inside)) if inside.any() else -1
    hours_ts = max(0.0, round(float(s.t[first]), 1)) if first >= 0 else None

    j = int(np.argmin(d))
    cross = s.head_e[j] * series["dy"][j] - s.head_n[j] * series["dx"][j]
    return {
        "peak_wind_kt": peak_kt,
        "peak_wind_mph": int(round(peak_kt * KT_TO_MPH)),
        "wind_band": wind_band(peak),
        "hours_until_tropical_storm_wind": hours_ts,
        "closest_approach_km": round(float(d[j]) * NM_TO_KM, 1),
        "track_side": "right" if cross < 0 else "left",
        "hours_until_peak_wind": round(float(s.t[k]), 1),
        "hours_until_closest_approach": round(float(s.t[j]), 1),
        "wind_basis": BASIS_TEXT[int(series["basis"][k])],
    }


def _sector(lat: float, lon: float, radius_nm: float, quadrant: int) -> list[tuple[float, float]]:
    """Quarter-circle as (lon, lat) points: centre, arc, centre."""
    bearings = np.radians(np.linspace(quadrant * 90.0, quadrant * 90.0 + 90.0, 13))
    kx = 60.0 * np.cos(np.radians(lat))
    ring = [(lon, lat)]
    ring += [(lon + radius_nm * np.sin(b) / kx, lat + radius_nm * np.cos(b) / 60.0) for b in bearings]
    ring.append((lon, lat))
    return [(float(x), float(y)) for x, y in ring]


def swath_polygons(s: Samples, every: int = 2) -> dict[int, dict | None]:
    """Area swept by the 34, 50 and 64 kt wind radii over the whole forecast.

    Returns {34: GeoJSON, 50: GeoJSON, 64: GeoJSON}; a value is None when the
    storm never has that radius. Built only from the advisory's radii (the
    union of the quadrant wedges at each time sample), so it is the map twin
    of the bands used in point_exposure.
    """
    from shapely.geometry import Polygon, mapping
    from shapely.ops import unary_union

    from .util import round_geometry

    out: dict[int, dict | None] = {}
    picks = sorted(set(range(0, len(s.t), max(1, every))) | {len(s.t) - 1})
    for threshold, radii in zip(THRESHOLDS, effective_radii(s)):
        wedges = []
        for i in picks:
            for q in range(4):
                r = float(radii[i, q])
                if r > 0.5:
                    wedges.append(Polygon(_sector(float(s.lat[i]), float(s.lon[i]), r, q)))
        if not wedges:
            out[threshold] = None
            continue
        merged = unary_union(wedges).buffer(0).simplify(0.01, preserve_topology=True)
        out[threshold] = None if merged.is_empty else round_geometry(mapping(merged), 3)
    return out
