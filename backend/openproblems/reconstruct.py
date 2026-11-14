"""Open problem "splats from sparse imagery": the furthest honest step.

We do not train gaussian splats and we do not generate anything. What exists, and what this module
uses, is measured 3D that the sponsors already publish:

* Vexcel serves a surface model (heights of roofs and tree tops, ``dsm/extract``) and a terrain model
  (bare ground, ``dtm/extract``) as GeoTIFF through the same REST API as the aerial photo. Subtracting
  one from the other gives a real height above ground for every half-metre of the site, on the same
  bounds as the cached aerial, so a web page can draw the outside as a displaced, photo-textured surface.
* Matterport's MatterPak for a scan holds the interior as a point cloud and a mesh, in the same
  coordinate frame as the scan's sweep positions.

Everything here is either a sponsor measurement or simple arithmetic on one, and every derived number
is labelled as derived, with its source collection and capture dates. Results live under
``data/cache/open/reconstruct/`` (never in git). Each request is cached so nothing is fetched twice.
"""
from __future__ import annotations

import io
import json
import math
import re
import struct
import zipfile
import zlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from PIL import Image, ImageDraw
from shapely import transform as shapely_transform
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from .. import matterport, vexcel
from ..config import BUILDINGS_DIR, CACHE_DIR, VEXCEL_LAYERS

OUT = CACHE_DIR / "open" / "reconstruct"
M_PER_DEG_LAT = 111_320.0
EARTH_RADIUS_M = 6378137.0     # the sphere Web Mercator (EPSG:3857) is defined on
HEIGHT_UNIT_M = 0.01           # one stored step is one centimetre, so 16 bits reach 655 m
NO_DATA = 65535                # stored value meaning "the source had no height here"
CELL_M = 0.5                   # grid spacing: finer than a tree crown, coarse enough for a web mesh
NEAR_M = 10.0                  # how far from a wall a tall thing still matters in a wind storm
EDGE_M = 1.0                   # footprints and heights never line up to the cell; keep this far from a roof edge
MIN_TALL_M = 2.5               # below this it is a car or a fence, not something that falls on a roof
MAX_PAK_MB = 150               # never pull a larger MatterPak than this without being asked


class ReconstructError(RuntimeError):
    pass


# --- reading Vexcel's height rasters ------------------------------------------------------------
# The environment has no GeoTIFF library and Pillow trips over these files' embedded XMP, so this is
# a small reader for exactly what the API returns: one band of 32-bit floats, deflate-compressed, in
# tiles or strips, positioned in Web Mercator.

_TIFF_TYPES = {1: ("B", 1), 2: ("c", 1), 3: ("H", 2), 4: ("I", 4), 5: ("II", 8), 11: ("f", 4), 12: ("d", 8)}


def _tiff_tags(data: bytes) -> tuple[str, dict[int, Any]]:
    if data[:2] not in (b"II", b"MM"):
        raise ReconstructError("not a TIFF file")
    e = "<" if data[:2] == b"II" else ">"
    if struct.unpack(e + "H", data[2:4])[0] != 42:
        raise ReconstructError("unsupported TIFF variant")
    off = struct.unpack(e + "I", data[4:8])[0]
    tags: dict[int, Any] = {}
    for i in range(struct.unpack(e + "H", data[off:off + 2])[0]):
        entry = data[off + 2 + 12 * i: off + 14 + 12 * i]
        tag, typ, count = struct.unpack(e + "HHI", entry[:8])
        if typ not in _TIFF_TYPES:
            continue
        fmt, size = _TIFF_TYPES[typ]
        total = size * count
        raw = entry[8:8 + total] if total <= 4 else data[struct.unpack(e + "I", entry[8:12])[0]:][:total]
        if typ == 2:
            tags[tag] = raw.rstrip(b"\0").decode("utf-8", "replace")
        elif typ == 5:
            pairs = struct.unpack(e + "I" * (2 * count), raw)
            tags[tag] = tuple(a / b if b else 0.0 for a, b in zip(pairs[::2], pairs[1::2]))
        else:
            tags[tag] = struct.unpack(e + fmt * count, raw)
    return e, tags


def read_height_tiff(data: bytes) -> tuple[np.ndarray, dict]:
    """A Vexcel height GeoTIFF as (heights in metres with NaN where empty, where and when it was measured)."""
    e, t = _tiff_tags(data)
    width, height = t[256][0], t[257][0]
    if t.get(258, (1,))[0] != 32 or t.get(339, (1,))[0] != 3 or t.get(277, (1,))[0] != 1:
        raise ReconstructError("expected one band of 32-bit float heights")
    if t.get(317, (1,))[0] != 1:
        raise ReconstructError("unsupported TIFF predictor")
    compression = t.get(259, (1,))[0]
    if compression not in (1, 8, 32946):
        raise ReconstructError(f"unsupported TIFF compression {compression}")
    if 324 in t:   # tiles
        block_w, block_h, offsets, counts = t[322][0], t[323][0], t[324], t[325]
    else:          # strips are tiles as wide as the image
        block_w, block_h, offsets, counts = width, t.get(278, (height,))[0], t[273], t[279]
    across = -(-width // block_w)
    out = np.full((height, width), np.nan, dtype=np.float32)
    for i, (o, c) in enumerate(zip(offsets, counts)):
        raw = data[o:o + c] if compression == 1 else zlib.decompress(data[o:o + c])
        r, k = divmod(i, across)
        y, x = r * block_h, k * block_w
        rows = min(block_h, height - y)
        # A tile is always full size; the last strip is only as tall as what is left.
        full = np.frombuffer(raw, dtype=e + "f4")
        block = full.reshape(-1, block_w)[:rows, :min(block_w, width - x)]
        out[y:y + rows, x:x + block.shape[1]] = block
    nodata = t.get(42113)
    if nodata:
        try:
            out[out == np.float32(float(nodata))] = np.nan
        except ValueError:
            pass

    # Where the pixels are. The tie point says which map position one raster position has; the scale
    # says how far apart pixels are. Vexcel uses Web Mercator, where east-west is linear in longitude
    # and north-south is not quite linear in latitude, so pixel centres are converted exactly.
    epsg = None
    keys = t.get(34735) or ()
    for j in range(4, len(keys) - 3, 4):
        if keys[j] in (3072, 2048) and keys[j + 1] == 0:
            epsg = keys[j + 3]
    if 33550 not in t or 33922 not in t or epsg not in (3857, 4326):
        raise ReconstructError("height raster has no usable position")
    sx, sy = t[33550][0], t[33550][1]
    pi, pj, _, mx, my, _ = t[33922][:6]
    xs = mx + (np.arange(width) + 0.5 - pi) * sx
    ys = my - (np.arange(height) + 0.5 - pj) * sy
    if epsg == 3857:
        lons, lats = mercator_to_lonlat(xs, ys)
        west, north = mercator_to_lonlat(mx - pi * sx, my + pj * sy)
        east, south = mercator_to_lonlat(mx + (width - pi) * sx, my - (height - pj) * sy)
        ground_m = sx * math.cos(math.radians(float(lats.mean())))  # Mercator stretches distances by 1/cos(latitude)
    else:
        lons, lats = xs, ys
        west, north, east, south = mx - pi * sx, my + pj * sy, mx + (width - pi) * sx, my - (height - pj) * sy
        ground_m = sy * M_PER_DEG_LAT
    i, j = data.find(b"<x:xmpmeta"), data.find(b"</x:xmpmeta>")
    x = dict(re.findall(r"<Vexcel:([\w-]+)>(.*?)</Vexcel:", data[i:j].decode("utf-8", "ignore"))) if 0 <= i < j else {}
    meta = {
        "bounds": [float(west), float(south), float(east), float(north)],
        "lons": lons, "lats": lats, "metres_per_pixel": float(ground_m),
        "product": x.get("product-type"), "collection": x.get("collection"), "layer": x.get("layer"),
        "first_capture": _day(x.get("first-capture-date")), "last_capture": _day(x.get("last-capture-date")),
        "native_gsd_m": [_float(x.get("min-gsd")), _float(x.get("max-gsd"))],
    }
    return out, meta


def mercator_to_lonlat(x, y):
    lon = np.degrees(np.asarray(x, dtype=float) / EARTH_RADIUS_M)
    lat = np.degrees(2 * np.arctan(np.exp(np.asarray(y, dtype=float) / EARTH_RADIUS_M)) - math.pi / 2)
    return lon, lat


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> str | None:
    """Vexcel writes dates two ways (ISO in lists, 'Thu Feb 12 16:44:18 UTC 2026' inside files); return the day."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        try:
            return datetime.strptime(value, "%a %b %d %H:%M:%S %Z %Y").date().isoformat()
        except ValueError:
            return None


# --- pure grid arithmetic -----------------------------------------------------------------------

def grid_axes(bounds: list[float], rows: int, cols: int) -> tuple[np.ndarray, np.ndarray]:
    """Longitude of each column centre and latitude of each row centre (row 0 is the north edge, like an image)."""
    w, s, e, n = bounds
    return w + (np.arange(cols) + 0.5) / cols * (e - w), n - (np.arange(rows) + 0.5) / rows * (n - s)


def reduce_to_grid(src: np.ndarray, src_lons: np.ndarray, src_lats: np.ndarray, bounds: list[float],
                   rows: int, cols: int, how: str = "max") -> np.ndarray:
    """Gather a fine raster into a coarser grid, keeping the highest, lowest or mean value in each cell.

    The surface uses "max" because a tree top or a roof ridge is exactly the thing a cell must not
    average away. Cells that receive no source pixel stay NaN rather than being filled in.
    """
    w, s, e, n = bounds
    ci = np.floor((np.asarray(src_lons) - w) / (e - w) * cols).astype(int)
    ri = np.floor((n - np.asarray(src_lats)) / (n - s) * rows).astype(int)
    ok_r, ok_c = (ri >= 0) & (ri < rows), (ci >= 0) & (ci < cols)
    values = src[np.ix_(ok_r, ok_c)].astype(np.float64)
    index = (ri[ok_r][:, None] * cols + ci[ok_c][None, :]).ravel()
    values = values.ravel()
    keep = np.isfinite(values)
    index, values = index[keep], values[keep]
    if how == "mean":
        total = np.bincount(index, weights=values, minlength=rows * cols)
        count = np.bincount(index, minlength=rows * cols)
        out = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    elif how in ("max", "min"):
        out = np.full(rows * cols, -np.inf if how == "max" else np.inf)
        (np.maximum if how == "max" else np.minimum).at(out, index, values)
        out[~np.isfinite(out)] = np.nan
    else:
        raise ValueError(how)
    return out.reshape(rows, cols).astype(np.float32)


def sample_bilinear(src: np.ndarray, src_lons: np.ndarray, src_lats: np.ndarray,
                    lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    """Read a smooth raster (the bare ground) at the given column longitudes and row latitudes."""
    h, w = src.shape
    fx = np.interp(lons, src_lons, np.arange(w))
    fy = np.interp(lats, src_lats[::-1], np.arange(h)[::-1])  # latitudes run north to south, interp needs ascending
    x0, y0 = np.clip(np.floor(fx).astype(int), 0, max(w - 2, 0)), np.clip(np.floor(fy).astype(int), 0, max(h - 2, 0))
    x1, y1 = np.minimum(x0 + 1, w - 1), np.minimum(y0 + 1, h - 1)
    ax, ay = (fx - x0)[None, :], (fy - y0)[:, None]
    top = src[np.ix_(y0, x0)] * (1 - ax) + src[np.ix_(y0, x1)] * ax
    bottom = src[np.ix_(y1, x0)] * (1 - ax) + src[np.ix_(y1, x1)] * ax
    return (top * (1 - ay) + bottom * ay).astype(np.float32)


def ground_offset(surface: np.ndarray, terrain: np.ndarray, window_m: float = 3.0, band_m: float = 0.25,
                  min_share: float = 0.10) -> dict:
    """How far the surface model sits above or below the terrain model on open ground.

    The two models can come from different flights whose heights were levelled separately, which
    leaves a constant step between them (about a metre at the demo site). Open ground is the one thing
    both models measure, and it is the most common thing on a site, so the step is where surface minus
    terrain piles up. If no clear pile exists nothing is corrected, and the result says so.
    """
    d = (surface.astype(np.float64) - terrain.astype(np.float64)).ravel()
    d = d[np.isfinite(d)]
    none = {"offset_m": 0.0, "applied": False, "share_of_cells": 0.0, "spread_m": None,
            "method": "no clear open-ground peak in surface minus terrain; nothing corrected"}
    near = d[np.abs(d) <= window_m]
    if d.size == 0 or near.size == 0:
        return none
    step = 0.05
    hist, edges = np.histogram(near, bins=np.arange(-window_m, window_m + step, step))
    smooth = np.convolve(hist, np.ones(5), mode="same")  # one noisy bin must not decide the peak
    peak = edges[int(np.argmax(smooth))] + step / 2
    band = d[np.abs(d - peak) <= band_m]
    share = band.size / d.size
    if share < min_share:
        return {**none, "share_of_cells": round(share, 3)}
    offset = float(np.median(band))
    return {"offset_m": round(offset, 3), "applied": True, "share_of_cells": round(share, 3),
            "spread_m": round(float(np.median(np.abs(band - offset))), 3),
            "method": f"median of (surface - terrain) within {band_m} m of its most common value; "
                      "derived, not a sponsor figure"}


def height_above_ground(surface: np.ndarray, terrain: np.ndarray, offset_m: float = 0.0) -> np.ndarray:
    """Surface minus ground. Small negatives are measurement noise on flat ground and become zero; gaps stay gaps."""
    h = surface.astype(np.float32) - (terrain.astype(np.float32) + np.float32(offset_m))
    return np.where(np.isnan(h), np.nan, np.maximum(h, 0)).astype(np.float32)


def pack_heights(heights: np.ndarray) -> np.ndarray:
    """Heights in metres to whole centimetres in 16 bits, with 65535 kept for "no data"."""
    cm = np.round(np.nan_to_num(heights, nan=0.0) / HEIGHT_UNIT_M)
    out = np.clip(cm, 0, NO_DATA - 1).astype(np.uint16)
    out[~np.isfinite(heights)] = NO_DATA
    return out


def unpack_heights(packed: np.ndarray) -> np.ndarray:
    out = packed.astype(np.float32) * np.float32(HEIGHT_UNIT_M)
    out[packed == NO_DATA] = np.nan
    return out


def save_height_png(packed: np.ndarray, path: Path) -> None:
    """Write the 16-bit grid as an ordinary 8-bit colour PNG: red is the high byte, green the low byte.

    Browsers hand a canvas only 8 bits per channel, so a true 16-bit grey PNG would lose its low byte
    on the way in. Split across two channels the same numbers survive: height = (R * 256 + G) * 0.01 m.
    Blue is 255 where there is no data, so a page can test one channel.
    """
    rgb = np.stack([packed >> 8, packed & 255, np.where(packed == NO_DATA, 255, 0)], axis=-1).astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(path, optimize=True)


def load_height_png(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB")).astype(np.uint16)
    return (rgb[..., 0] << 8) | rgb[..., 1]


def shaded_relief(heights: np.ndarray, cell_x_m: float, cell_y_m: float, azimuth: float = 315.0,
                  altitude: float = 45.0) -> np.ndarray:
    """Brightness 0..1 of each cell as if lit from the north-west, the usual way to make height readable."""
    h = np.nan_to_num(heights.astype(np.float64), nan=0.0)
    d_south, d_east = np.gradient(h, cell_y_m, cell_x_m)   # rows run north to south
    d_north = -d_south
    az, alt = math.radians(azimuth), math.radians(altitude)
    light = (math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt))  # east, north, up
    shade = (-d_east * light[0] - d_north * light[1] + light[2]) / np.sqrt(d_east ** 2 + d_north ** 2 + 1)
    return np.clip(shade, 0, 1)


# --- roofs and what stands next to them ----------------------------------------------------------

def _metres(bounds: list[float]):
    """Functions that move coordinate lists between lon/lat and metres east/north of the grid's south-west corner."""
    w, s, _, n = bounds
    corner = np.array([w, s])
    scale = np.array([M_PER_DEG_LAT * math.cos(math.radians((s + n) / 2)), M_PER_DEG_LAT])
    return (lambda c: (np.asarray(c) - corner) * scale), (lambda c: np.asarray(c) / scale + corner)


def _mask(geom, bounds: list[float], rows: int, cols: int) -> np.ndarray:
    """Which grid cells a lon/lat shape covers."""
    w, s, e, n = bounds
    im = Image.new("1", (cols, rows), 0)
    d = ImageDraw.Draw(im)
    for part in getattr(geom, "geoms", [geom]):
        if part.is_empty or part.geom_type != "Polygon":
            continue
        px = lambda ring: [((x - w) / (e - w) * cols, (n - y) / (n - s) * rows) for x, y in ring.coords]
        d.polygon(px(part.exterior), fill=1)
        for hole in part.interiors:
            d.polygon(px(hole), fill=0)
    return np.asarray(im, dtype=bool)


def summarise_structures(heights: np.ndarray, bounds: list[float], structures: list[dict],
                         other_footprints: list[list[list[float]]] | None = None, *, terrain: np.ndarray | None = None,
                         colours: np.ndarray | None = None, near_m: float = NEAR_M, edge_m: float = EDGE_M,
                         min_tall_m: float = MIN_TALL_M) -> list[dict]:
    """For each building footprint: how high its roof is, and the tallest thing standing within ``near_m`` of it.

    "Tallest thing" is the highest cell that is close to the walls but not on any mapped building.
    Heights alone cannot tell a tree from a pole or an unmapped shed, so it is reported as a tall
    object with its position; the aerial colour at that spot is passed through as a hint only.
    """
    rows, cols = heights.shape
    to_m, to_ll = _metres(bounds)
    lons, lats = grid_axes(bounds, rows, cols)
    w, s, e, n = bounds
    cell_area = ((e - w) / cols * M_PER_DEG_LAT * math.cos(math.radians((s + n) / 2))) * ((n - s) / rows * M_PER_DEG_LAT)
    polys = [shapely_transform(Polygon(st["polygon"]).buffer(0), to_m) for st in structures]
    others = [shapely_transform(Polygon(p).buffer(0), to_m) for p in other_footprints or []]
    # Roof edges bleed a cell or so past the drawn footprint; widen every building before calling
    # anything beside it "not a building", or each roof's own eave would be its tallest neighbour.
    built = unary_union(polys + others).buffer(edge_m)
    finite = np.isfinite(heights)
    out = []
    for st, poly in zip(structures, polys):
        inner = poly.buffer(-edge_m)
        roof = _mask(shapely_transform(inner if not inner.is_empty else poly, to_ll), bounds, rows, cols) & finite
        row: dict[str, Any] = {"id": st["id"], "roof_cells": int(roof.sum()), "roof_height_m": None, "roof_ridge_m": None,
                               "roof_max_m": None, "ground_elevation_m": None, "tallest_nearby": None,
                               "area_above_roof_within_near_sqm": None}
        if roof.any():
            v = heights[roof]
            row.update(roof_height_m=round(float(np.median(v)), 2), roof_ridge_m=round(float(np.percentile(v, 95)), 2),
                       roof_max_m=round(float(v.max()), 2))
            if terrain is not None and np.isfinite(terrain[roof]).any():
                row["ground_elevation_m"] = round(float(np.nanmedian(terrain[roof])), 2)
        ring = _mask(shapely_transform(poly.buffer(near_m).difference(built), to_ll), bounds, rows, cols) & finite
        if ring.any():
            if row["roof_height_m"] is not None:
                row["area_above_roof_within_near_sqm"] = round(float((ring & (heights > row["roof_height_m"])).sum() * cell_area), 1)
            masked = np.where(ring, heights, -np.inf)
            r, c = np.unravel_index(int(np.argmax(masked)), masked.shape)
            top = float(heights[r, c])
            if top >= min_tall_m:
                x, y = to_m([float(lons[c]), float(lats[r])])
                tall: dict[str, Any] = {"height_m": round(top, 2), "lon": round(float(lons[c]), 7), "lat": round(float(lats[r]), 7),
                                        "distance_to_wall_m": round(float(Point(x, y).distance(poly)), 1), "row": int(r), "col": int(c)}
                if row["roof_height_m"] is not None:
                    tall["above_roof_m"] = round(top - row["roof_height_m"], 2)
                    tall["overtops_roof"] = bool(top > row["roof_height_m"])
                if colours is not None:
                    red, green, blue = (int(k) for k in colours[r, c][:3])
                    tall["aerial_rgb"] = [red, green, blue]
                    tall["aerial_looks_green"] = bool(green > red and green > blue)  # a hint; bare winter trees fail it
                row["tallest_nearby"] = tall
        out.append(row)
    return out


# --- Vexcel: which height models exist, and fetching them -------------------------------------------

def elevation_collections(kind: str, area_wkt: str, cache: Path, refresh: bool = False) -> list[dict]:
    """Every surface ("dsm") or terrain ("dtm") model covering an area, newest first."""
    if kind not in ("dsm", "dtm"):
        raise ValueError(kind)
    path = cache / f"{kind}_collections.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    r = vexcel._send("GET", f"{kind}/collections", timeout=120, params={
        "wkt": area_wkt, "srid": 4326,
        "include": "collection,first-capture-date,last-capture-date,layer,min-gsd,max-gsd,product-type"})
    if r.status_code == 404:
        rows: list[dict] = []
    elif not r.is_success:
        raise vexcel.VexcelError(r.status_code, r.text[:300])
    else:
        rows = [{"collection": p.get("collection"), "layer": p.get("layer"), "product": p.get("product-type"),
                 "first_capture": _day(p.get("first-capture-date")), "last_capture": _day(p.get("last-capture-date")),
                 "min_gsd_m": p.get("min-gsd"), "max_gsd_m": p.get("max-gsd")}
                for p in (f["properties"] for f in r.json().get("features") or [])]
        rows.sort(key=lambda c: c["last_capture"] or "", reverse=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def elevation_raster(kind: str, area_wkt: str, collection: str, size: tuple[int, int], cache: Path,
                     refresh: bool = False) -> tuple[np.ndarray, dict]:
    """One height raster from Vexcel, downloaded once and kept as the GeoTIFF the API returned."""
    path = cache / f"{kind}_{collection}_{size[0]}x{size[1]}.tif"
    if not path.exists() or refresh:
        r = vexcel._send("POST", f"{kind}/extract", body={
            "wkt": area_wkt, "srid": 4326, "layer": VEXCEL_LAYERS, "crop": "bounding_box", "buffer-meter": 0,
            "destination-dimensions": f"{size[0]},{size[1]}", "collection": collection})
        if not r.is_success:
            raise vexcel.VexcelError(r.status_code, r.text[:300])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
    arr, meta = read_height_tiff(path.read_bytes())
    meta["file"] = str(path)
    meta["endpoint"] = f"POST {vexcel.API}/{kind}/extract"
    return arr, meta


def _source(meta: dict) -> dict:
    return {k: meta.get(k) for k in ("endpoint", "product", "collection", "layer", "first_capture", "last_capture",
                                     "native_gsd_m", "metres_per_pixel", "file")}


def site_heights(property_id: int, refresh: bool = False, cell_m: float = CELL_M, cross_check: bool = True) -> dict:
    """Real height above ground for the area of a building's cached aerial photo, on a regular grid.

    Returns the grid's shape, lon/lat bounds, metres per cell, sources and capture dates, the path of
    the packed height image and of a texture on the same bounds, and per-structure roof heights with
    the tallest object near each. ``available`` is False, with the reason, when Vexcel has no height
    model here; nothing is estimated in its place.
    """
    out_dir = OUT / str(property_id)
    result_path = out_dir / "heights.json"
    if result_path.exists() and not refresh:
        return json.loads(result_path.read_text())
    bundle_path = BUILDINGS_DIR / str(property_id) / "building.json"
    if not bundle_path.exists():
        raise ReconstructError(f"building {property_id} has no cached bundle; prepare the building first")
    bundle = json.loads(bundle_path.read_text())
    aerial = bundle["aerial"]
    bounds = [float(v) for v in aerial["bounds"]]
    area = box(*bounds).wkt
    src_dir = out_dir / "source"
    out_dir.mkdir(parents=True, exist_ok=True)

    surfaces = elevation_collections("dsm", area, src_dir, refresh)
    terrains = elevation_collections("dtm", area, src_dir, refresh)
    if not surfaces or not terrains:
        missing = " and ".join(k for k, v in (("surface model", surfaces), ("terrain model", terrains)) if not v)
        out = {"available": False, "property_id": property_id,
               "reason": f"Vexcel returned no {missing} for this site", "surface_collections": surfaces,
               "terrain_collections": terrains}
        result_path.write_text(json.dumps(out, indent=1))
        return out

    # Use the surface model from the same flight as the photo it will be textured with, when there is one.
    photo_day = _day(aerial.get("captured"))
    surface_pick = next((c for c in surfaces if photo_day and c["last_capture"] == photo_day), surfaces[0])
    terrain_pick = terrains[0]
    photo_px = (int(aerial["width"]), int(aerial["height"]))
    dsm, dsm_meta = elevation_raster("dsm", area, surface_pick["collection"], photo_px, src_dir, refresh)
    # Bare ground is smooth, so half the resolution loses nothing and halves the download.
    dtm, dtm_meta = elevation_raster("dtm", area, terrain_pick["collection"], (photo_px[0] // 2, photo_px[1] // 2), src_dir, refresh)

    w, s, e, n = bounds
    width_m = (e - w) * M_PER_DEG_LAT * math.cos(math.radians((s + n) / 2))
    height_m = (n - s) * M_PER_DEG_LAT
    cols, rows = max(2, round(width_m / cell_m)), max(2, round(height_m / cell_m))
    lons, lats = grid_axes(bounds, rows, cols)
    surface = reduce_to_grid(dsm, dsm_meta["lons"], dsm_meta["lats"], bounds, rows, cols, "max")
    terrain = sample_bilinear(dtm, dtm_meta["lons"], dtm_meta["lats"], lons, lats)
    # The step between the two flights is measured on mean heights; the tallest point of a cell would bias it upward.
    step = ground_offset(reduce_to_grid(dsm, dsm_meta["lons"], dsm_meta["lats"], bounds, rows, cols, "mean"), terrain)
    heights = height_above_ground(surface, terrain, step["offset_m"])

    packed = pack_heights(heights)
    save_height_png(packed, out_dir / "heights.png")
    heights = unpack_heights(packed)  # summarise exactly what a page will read back

    texture = BUILDINGS_DIR / str(property_id) / "aerial.jpg"
    colours = None
    if texture.exists():
        with Image.open(texture) as im:
            colours = np.asarray(im.convert("RGB").resize((cols, rows), Image.BOX))
    others = _all_footprints(bundle)
    summaries = summarise_structures(heights, bounds, bundle["structures"], others, terrain=terrain, colours=colours)
    for st, row in zip(bundle["structures"], summaries):  # Vexcel's own tree figures, for comparison with ours
        row["vexcel_roof_tree_cover_percent"] = st.get("roof_tree_cover_percent")
        row["vexcel_trees_within_5ft_percent"] = st.get("trees_within_5ft_percent")
        row["vexcel_trees_5_to_30ft_percent"] = st.get("trees_5_to_30ft_percent")
        if row["tallest_nearby"]:
            # Two independent readings agreeing is the nearest thing to "this is a tree" that we can say.
            near = (st.get("trees_within_5ft_percent") or 0) + (st.get("trees_5_to_30ft_percent") or 0)
            row["tallest_nearby"]["vexcel_reports_trees_within_30ft"] = bool(near > 0)

    check = None
    if cross_check and surface_pick["collection"] != terrain_pick["collection"] \
            and any(c["collection"] == terrain_pick["collection"] for c in surfaces):
        # A second opinion needing no correction: surface and terrain from one and the same flight.
        dsm2, meta2 = elevation_raster("dsm", area, terrain_pick["collection"], photo_px, src_dir, refresh)
        h2 = height_above_ground(reduce_to_grid(dsm2, meta2["lons"], meta2["lats"], bounds, rows, cols, "max"), terrain)
        rows2 = summarise_structures(h2, bounds, bundle["structures"], others)
        diffs = [a["roof_height_m"] - b["roof_height_m"] for a, b in zip(summaries, rows2)
                 if a["roof_height_m"] is not None and b["roof_height_m"] is not None]
        check = {"what": "roof heights recomputed from the surface and terrain of one flight, with no correction",
                 "source": _source(meta2), "structures_compared": len(diffs),
                 "median_roof_difference_m": round(float(np.median(diffs)), 2) if diffs else None,
                 "largest_roof_difference_m": round(float(np.max(np.abs(diffs))), 2) if diffs else None}

    valid = np.isfinite(heights)
    out = {
        "available": True, "property_id": property_id, "name": (bundle.get("record") or {}).get("name"),
        "rows": rows, "cols": cols, "bounds": bounds,
        "metres_per_cell": round((width_m / cols + height_m / rows) / 2, 4),
        "cell_m": [round(width_m / cols, 4), round(height_m / rows, 4)],
        "heights_png": str(out_dir / "heights.png"),
        "encoding": {"what": "height above ground in metres, row 0 at the north edge, column 0 at the west edge",
                     "decode": "height_m = (R * 256 + G) * 0.01; B == 255 means no data",
                     "unit_m": HEIGHT_UNIT_M, "no_data": NO_DATA, "cell_value": "highest surface point in the cell"},
        "texture": str(texture) if texture.exists() else None,
        "texture_bounds": bounds if texture.exists() else None,
        "texture_note": "the building's cached Vexcel aerial; same bounds as the grid" if texture.exists() else None,
        "capture_date": dsm_meta["last_capture"],
        "source": {
            "surface": _source(dsm_meta), "terrain": _source(dtm_meta),
            "derived": "height above ground = surface model - (terrain model + step between flights); "
                       "arithmetic on two Vexcel measurements, not a Vexcel product",
            "step_between_flights": step,
            "elevations": "metres as delivered by Vexcel; the vertical datum is not stated in the files",
        },
        "stats": {"cells": int(valid.sum()), "no_data_cells": int((~valid).sum()),
                  "max_height_m": round(float(np.nanmax(heights)), 2),
                  "share_above_2m": round(float((heights[valid] > 2).mean()), 3),
                  "ground_elevation_m": [round(float(np.nanmin(terrain)), 2), round(float(np.nanmedian(terrain)), 2),
                                         round(float(np.nanmax(terrain)), 2)]},
        "structures": summaries,
        "structure_notes": {
            "roof_height_m": f"median height above ground of cells at least {EDGE_M} m inside the footprint",
            "roof_ridge_m": "95th percentile of the same cells",
            "tallest_nearby": f"highest cell within {NEAR_M} m of the walls that is not on a mapped building "
                              f"(buildings widened by {EDGE_M} m) and is at least {MIN_TALL_M} m tall; usually a tree, "
                              "but heights alone cannot prove it",
            "area_above_roof_within_near_sqm": f"ground area within {NEAR_M} m where something stands higher than the roof",
        },
        "cross_check": check,
        "all_surface_collections": surfaces, "all_terrain_collections": terrains,
    }
    proof = render_proof(heights, bounds, bundle["structures"], summaries, texture if texture.exists() else None, out_dir)
    out.update(proof)
    result_path.write_text(json.dumps(out, indent=1))
    return out


def _all_footprints(bundle: dict) -> list[list[list[float]]]:
    """Footprints of every structure on the parcel, including those the bundle left out (it keeps 24).

    Read from the parcel record already cached by the Vexcel client; no request is made on a miss.
    """
    rec = bundle.get("record") or {}
    try:
        path = vexcel.VX_CACHE / "parcel" / f"{rec['lat']:.6f}_{rec['lon']:.6f}.json"
        data = json.loads(path.read_text()) or {}
    except (KeyError, TypeError, ValueError, OSError):
        return []
    from shapely import wkt as shapely_wkt
    out = []
    for st in (data.get("attributes") or {}).get("structures") or []:
        try:
            g = shapely_wkt.loads(st["footprint.wkt"])
        except Exception:
            continue
        for part in getattr(g, "geoms", [g]):
            if part.geom_type == "Polygon" and not part.is_empty:
                out.append([[x, y] for x, y in part.exterior.coords])
    return out


# --- the proof picture ----------------------------------------------------------------------------

_RAMP = [(0.0, (62, 72, 88)), (2.5, (96, 138, 122)), (7.0, (214, 190, 112)), (12.0, (232, 124, 72)), (20.0, (250, 240, 236))]


def _tint(heights: np.ndarray) -> np.ndarray:
    """Colour by height only (never by a guess at what the thing is)."""
    h = np.nan_to_num(heights, nan=0.0)
    stops = np.array([s for s, _ in _RAMP])
    return np.stack([np.interp(h, stops, [c[k] for _, c in _RAMP]) for k in range(3)], axis=-1)


def render_proof(heights: np.ndarray, bounds: list[float], structures: list[dict], summaries: list[dict],
                 texture: Path | None, out_dir: Path) -> dict:
    """Shaded relief of the height grid with footprints drawn on it, alone and beside the aerial photo."""
    rows, cols = heights.shape
    w, s, e, n = bounds
    cx = (e - w) / cols * M_PER_DEG_LAT * math.cos(math.radians((s + n) / 2))
    cy = (n - s) / rows * M_PER_DEG_LAT
    shade = shaded_relief(heights, cx, cy)
    rgb = _tint(heights) * (0.30 + 0.70 * shade[..., None]) / (0.30 + 0.70 * math.sin(math.radians(45)))
    rgb[~np.isfinite(heights)] = (255, 0, 255)  # gaps in the source stay loud
    k = max(1, round(1400 / rows))
    relief = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").resize((cols * k, rows * k), Image.NEAREST)

    def annotate(im: Image.Image) -> Image.Image:
        d = ImageDraw.Draw(im)
        P = lambda lon, lat: ((lon - w) / (e - w) * im.width, (n - lat) / (n - s) * im.height)
        for st in structures:
            d.line([P(*p) for p in st["polygon"]], fill=(255, 214, 10), width=2)
        by_id = {r["id"]: r for r in summaries}
        for st in structures:
            row = by_id.get(st["id"]) or {}
            x, y = P(*st["centroid"])
            label = st["id"] if row.get("roof_height_m") is None else f"{st['id']} {row['roof_height_m']:.1f}m"
            d.text((x - 3 * len(label) + 1, y - 5 + 1), label, fill=(0, 0, 0))
            d.text((x - 3 * len(label), y - 5), label, fill=(255, 255, 255))
            tall = row.get("tallest_nearby")
            if tall:
                tx, ty = P(tall["lon"], tall["lat"])
                colour = (255, 60, 60) if tall.get("overtops_roof") else (80, 200, 255)
                d.ellipse([tx - 6, ty - 6, tx + 6, ty + 6], outline=colour, width=2)
        return im

    relief = annotate(relief)
    d = ImageDraw.Draw(relief)
    x0, y0 = 12, relief.height - 34
    for i in range(200):  # legend: the colour ramp with its heights
        c = tuple(int(v) for v in _tint(np.array([[i / 200 * 20.0]]))[0, 0])
        d.line([(x0 + i, y0), (x0 + i, y0 + 12)], fill=c)
    for m in (0, 5, 10, 15, 20):
        d.text((x0 + m * 10 - 3, y0 + 14), str(m), fill=(255, 255, 255))
    d.text((x0, y0 - 14), "height above ground, m (Vexcel surface - terrain). red ring: tallest object near a "
                          "building, above its roof; blue ring: below", fill=(255, 255, 255))
    relief_path = out_dir / "proof_relief.jpg"
    relief.save(relief_path, quality=90)
    out = {"proof_relief": str(relief_path), "proof_side_by_side": None}
    if texture is not None:
        with Image.open(texture) as im:
            photo = annotate(im.convert("RGB").resize(relief.size, Image.LANCZOS))
        both = Image.new("RGB", (relief.width * 2 + 8, relief.height), (0, 0, 0))
        both.paste(photo, (0, 0))
        both.paste(relief, (relief.width + 8, 0))
        side = out_dir / "proof_side_by_side.jpg"
        both.save(side, quality=88)
        out["proof_side_by_side"] = str(side)
    return out


# --- Matterport: what 3D exists for a scan, and the interior geometry ------------------------------

_ASSET_FIELDS = """id name
  splat: bundle(id:"mp:exteriorsplat"){ availability processing{ status } assets{ filename format status } }
  pak: bundle(id:"mp:matterpak"){ availability processing{ status } assets{ filename format status } }
  e57: bundle(id:"mp:e57"){ availability assets{ filename format status } }
  views{ id type enabled }
  assets{ meshes{ filename format resolution status } resources{ id format status } }"""
EXTERIOR_VIEW = "matterport.model.exterior"  # the view type a model gains when it carries an exterior splat


def scan_assets(scan_ids: list[str], refresh: bool = False) -> dict[str, dict]:
    """Which downloadable 3D assets the Model API lists for each scan (mesh, MatterPak, point cloud, splat)."""
    path = OUT / "scan_assets.json"
    known: dict[str, dict] = json.loads(path.read_text()) if path.exists() else {}
    todo = [s for s in dict.fromkeys(scan_ids) if refresh or s not in known]
    for i in range(0, len(todo), 30):   # thirty scans per request keeps us far inside the call budget
        chunk = todo[i:i + 30]
        data = matterport.gql("{ " + " ".join(f'm{j}: model(id:"{m}"){{ {_ASSET_FIELDS} }}' for j, m in enumerate(chunk)) + " }")
        for m in data.values():
            if m:
                known[m["id"]] = m
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known))
    return {s: summarise_scan_assets(known[s]) for s in scan_ids if s in known}


def summarise_scan_assets(m: dict) -> dict:
    """One scan's raw asset listing boiled down to yes/no answers."""
    pak, splat, e57 = m.get("pak") or {}, m.get("splat") or {}, m.get("e57") or {}
    ready = lambda b: any(a.get("status") == "available" for a in b.get("assets") or [])
    return {
        "id": m.get("id"), "name": m.get("name"),
        "meshes": [f"{x.get('format')} {x.get('resolution')} ({x.get('status')})" for x in (m.get("assets") or {}).get("meshes") or []],
        "matterpak": bool(pak.get("availability") == "unlocked" and ready(pak)),
        "e57_point_cloud": bool(ready(e57)),
        "exterior_splat": bool(ready(splat) or any(v.get("type") == EXTERIOR_VIEW for v in m.get("views") or [])),
        "exterior_splat_bundle": splat.get("availability"),
    }


def splat_models(refresh: bool = False) -> list[dict]:
    """Every model in the sponsor account that carries a gaussian splat, from the Model API's own search."""
    path = OUT / "splat_models.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    data = matterport.gql('{ models(query:"splats.count:[1 TO *]", pageSize:300){ totalResults results{ id name '
                          'splats{ count ids } address{ address } geolocation{ lat long } } } }')
    rows = data["models"]["results"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def cached_building_scans() -> dict[int, list[dict]]:
    """Scans of every building that has a cached bundle: {property id: [{id, name}]}."""
    out: dict[int, list[dict]] = {}
    for p in sorted(BUILDINGS_DIR.glob("*/building.json")):
        b = json.loads(p.read_text())
        out[int(b["id"])] = [{"id": s["id"], "name": s.get("name")} for s in b.get("scans") or []]
    return out


def inventory(refresh: bool = False) -> dict:
    """What 3D Matterport has for the scans of the cached buildings, and where the real splats are."""
    buildings = cached_building_scans()
    assets = scan_assets([s["id"] for scans in buildings.values() for s in scans], refresh)
    splats = {m["id"]: m for m in splat_models(refresh)}
    return {
        "buildings": len(buildings), "scans": len(assets),
        "scans_with_matterpak": sorted(s for s, a in assets.items() if a["matterpak"]),
        "scans_with_mesh": sorted(s for s, a in assets.items() if any("(available)" in m for m in a["meshes"])),
        "scans_with_e57": sorted(s for s, a in assets.items() if a["e57_point_cloud"]),
        "scans_with_exterior_splat": sorted(s for s, a in assets.items() if a["exterior_splat"] or s in splats),
        "splat_models_in_account": len(splats),
        "by_scan": assets,
    }


def interior_geometry(scan_id: str, refresh: bool = False, download: bool = True) -> dict:
    """Fetch a scan's MatterPak once and describe its point cloud and mesh. Nothing is rendered.

    The archive is read in place (never unpacked) and only numbers are parsed out of it.
    """
    out_dir = OUT / "matterpak" / scan_id
    summary_path = out_dir / "summary.json"
    if summary_path.exists() and not refresh:
        return json.loads(summary_path.read_text())
    archive = next(iter(out_dir.glob("*.zip")), None) if out_dir.exists() else None
    if archive is None:
        data = matterport.gql('{ model(id:"%s"){ bundle(id:"mp:matterpak"){ availability assets{ filename format status url } } } }' % scan_id)
        bundle = ((data.get("model") or {}).get("bundle")) or {}
        asset = next((a for a in bundle.get("assets") or [] if a.get("status") == "available" and a.get("url")), None)
        if not asset:
            return {"scan": scan_id, "available": False,
                    "reason": f"MatterPak bundle is {bundle.get('availability') or 'not listed'} for this scan"}
        # A one-byte request reveals the size before committing to the download.
        probe = httpx.get(asset["url"], headers={"Range": "bytes=0-0"}, timeout=60, follow_redirects=True)
        total = int((probe.headers.get("content-range") or "/0").rsplit("/", 1)[-1] or 0)
        if not download or total > MAX_PAK_MB * 1e6:
            return {"scan": scan_id, "available": True, "downloaded": False, "bytes": total, "filename": asset["filename"]}
        out_dir.mkdir(parents=True, exist_ok=True)
        archive = out_dir / Path(asset["filename"]).name
        part = archive.with_suffix(".part")
        with httpx.stream("GET", asset["url"], timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with part.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        part.rename(archive)
    summary = describe_matterpak(archive, scan_id)
    summary_path.write_text(json.dumps(summary, indent=1))
    return summary


def describe_matterpak(archive: Path, scan_id: str) -> dict:
    out: dict[str, Any] = {"scan": scan_id, "available": True, "downloaded": True, "archive": str(archive),
                           "bytes": archive.stat().st_size, "source": "Matterport Model API, bundle mp:matterpak"}
    with zipfile.ZipFile(archive) as z:
        out["contents"] = [{"name": i.filename, "bytes": i.file_size} for i in z.infolist()]
        cloud_name = next((i.filename for i in z.infolist() if i.filename.lower().endswith(".xyz")), None)
        mesh_name = next((i.filename for i in z.infolist() if i.filename.lower().endswith(".obj")), None)
        cloud = None
        if cloud_name:
            with z.open(cloud_name) as f:
                cloud = np.loadtxt(io.TextIOWrapper(f, encoding="ascii", errors="replace"), dtype=np.float32, ndmin=2)
            out["point_cloud"] = {
                "file": cloud_name, "format": "plain text, one point per line: x y z r g b (metres, colour 0-255)",
                "points": int(cloud.shape[0]), "columns": int(cloud.shape[1]),
                "min_xyz": [round(float(v), 3) for v in cloud[:, :3].min(0)],
                "max_xyz": [round(float(v), 3) for v in cloud[:, :3].max(0)]}
        if mesh_name:
            verts: list[list[bytes]] = []
            faces = 0
            with z.open(mesh_name) as f:
                for line in f:
                    if line.startswith(b"v "):
                        verts.append(line.split()[1:4])
                    elif line.startswith(b"f "):
                        faces += 1
            v = np.array(verts, dtype=np.float32)
            out["mesh"] = {"file": mesh_name, "format": "Wavefront OBJ with an MTL file and JPEG textures",
                           "vertices": int(v.shape[0]), "faces": faces,
                           # the mesh's own texture sheets share its file name; floor plan pictures do not
                           "textures": sum(1 for i in z.infolist() if i.filename.startswith(Path(mesh_name).stem + "_")
                                           and i.filename.lower().endswith(".jpg")),
                           "min_xyz": [round(float(k), 3) for k in v.min(0)], "max_xyz": [round(float(k), 3) for k in v.max(0)]}
    model_path = matterport.MP_CACHE / scan_id / "model.json"
    if model_path.exists():
        out["frame"] = relate_to_sweeps(json.loads(model_path.read_text()), cloud, out.get("mesh"))
    return out


def relate_to_sweeps(model: dict, cloud: np.ndarray | None, mesh: dict | None) -> dict:
    """Check, with numbers, that the MatterPak geometry is in the same frame as the scan's sweep positions."""
    sweeps = np.array([[s["x"], s["y"], s["z"]] for s in model.get("sweeps") or [] if s.get("has_pano")], dtype=np.float64)
    out: dict[str, Any] = {
        "units": "metres", "up_axis": "z",
        "statement": "Matterport model frame: the same x, y, z as sweep positions and room outlines from the Model API. "
                     "It becomes lon/lat through the scan's own GPS fix (geo.initial_transform in backend/building.py).",
        "sweeps": int(len(sweeps))}
    if len(sweeps) == 0:
        return out
    out["sweep_height_range_m"] = [round(float(sweeps[:, 2].min()), 2), round(float(sweeps[:, 2].max()), 2)]
    box_min = (mesh or {}).get("min_xyz") or (cloud[:, :3].min(0).tolist() if cloud is not None else None)
    box_max = (mesh or {}).get("max_xyz") or (cloud[:, :3].max(0).tolist() if cloud is not None else None)
    if box_min:
        out["sweeps_inside_geometry_box"] = int(((sweeps >= np.array(box_min)) & (sweeps <= np.array(box_max))).all(1).sum())
    if cloud is None:
        return out
    # Floor level: the most common height among points below the cameras.
    below = cloud[cloud[:, 2] < sweeps[:, 2].min() - 0.5, 2]
    if below.size:
        hist, edges = np.histogram(below, bins=np.arange(float(below.min()), float(below.max()) + 0.05, 0.05))
        floor = float(edges[int(np.argmax(hist))] + 0.025)
        out["floor_z_m"] = round(floor, 2) + 0.0  # adding zero turns a rounded "-0.0" into "0.0"
        out["camera_height_above_floor_m"] = round(float(np.median(sweeps[:, 2])) - floor, 2)
    # A camera cannot see itself, so each sweep should sit in a small empty pocket of the cloud, about
    # a tripod's height from the nearest measured point. Far larger would mean a different frame.
    sample = cloud[:: max(1, len(cloud) // 400_000), :3].astype(np.float64)
    nearest = [float(np.sqrt(((sample - s) ** 2).sum(1).min())) for s in sweeps]
    out["sweep_to_nearest_point_m"] = [round(min(nearest), 2), round(max(nearest), 2)]
    # Points beyond the rooms: what the scanner saw of the outside through doors and windows.
    polys = [Polygon(r["polygon"]) for r in model.get("rooms") or [] if r.get("polygon") and len(r["polygon"]) >= 4]
    if polys:
        rooms = unary_union([p.buffer(0) for p in polys]).buffer(0.5)  # walls are thicker than a line
        x0, y0, x1, y1 = rooms.bounds
        res = 0.05
        w, h = int(math.ceil((x1 - x0) / res)) + 1, int(math.ceil((y1 - y0) / res)) + 1
        im = Image.new("1", (w, h), 0)
        d = ImageDraw.Draw(im)
        for part in getattr(rooms, "geoms", [rooms]):
            d.polygon([((x - x0) / res, (y - y0) / res) for x, y in part.exterior.coords], fill=1)
        inside_mask = np.asarray(im, dtype=bool)
        ix, iy = np.floor((cloud[:, 0] - x0) / res).astype(int), np.floor((cloud[:, 1] - y0) / res).astype(int)
        ok = (ix >= 0) & (ix < w) & (iy >= 0) & (iy < h)
        inside = np.zeros(len(cloud), dtype=bool)
        inside[ok] = inside_mask[iy[ok], ix[ok]]
        outside = cloud[~inside]
        out["points_outside_room_outlines"] = int(len(outside))
        out["share_outside_room_outlines"] = round(float(len(outside) / len(cloud)), 3)
        if len(outside):
            far = np.array([Point(float(x), float(y)).distance(rooms) for x, y in outside[:: max(1, len(outside) // 2000), :2]])
            out["outside_points_reach_m"] = round(float(np.percentile(far, 99)), 1)
            out["outside_note"] = ("points the interior scanner measured beyond the room outlines (through doors and "
                                   "windows, plus wall and clutter noise): real exterior geometry, but sparse and one-sided")
    return out
