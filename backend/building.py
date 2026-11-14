"""Builds and loads the per-building bundle: CoStar record + aerial site + attached scans, in one frame."""
from __future__ import annotations

import json
import math
import re
import shutil
import string
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely import wkt as shapely_wkt
from shapely.geometry import Point, Polygon, box

from . import geo, matterport, portfolio, vexcel
from .config import BUILDINGS_DIR

BUNDLE_VERSION = 4
MAX_AERIAL_PX = 1500
MAX_SCANS = 14
DEFECTS = ("missing-material", "tarp", "patch", "structural-damage", "rust", "debris")
STAINS = ("water-pooling", "algae-staining", "vegetation-on-roof")
ROOF_OBJECTS = ("ac-unit", "roof-vent", "skylight", "satellite-dish", "chimney")

_AMENITY = re.compile(r"fitness|gym|club|leasing|lobby|lounge|business|pool|amenit|conference|training|cafe|theat|game|"
                      r"mail|laundry|courtyard|rooftop|sky ?deck|ballroom|restaurant|office$", re.I)
_UNIT = re.compile(r"\b\d\s*(br|bd|bed)|studio|\bunit\b|\bplan\b|\bloft\b|penthouse|\bmodel\b", re.I)
_SUITE = re.compile(r"\b(?:suite|ste\.?|#)\s*([a-z]?\d{2,5})", re.I)
_FLOOR = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\s+floor|\bfloor\s+(\d{1,2})\b", re.I)
_WAREHOUSE = re.compile(r"warehouse|dock|industrial|bay\b|shop\b", re.I)


class BuildingError(RuntimeError):
    pass


def building_dir(property_id: int) -> Path:
    return BUILDINGS_DIR / str(property_id)


def classify_scan(name: str | None) -> tuple[str, int | None]:
    """What kind of space a scan shows and, when the title gives it away, which floor it is on."""
    name = name or ""
    level: int | None = None
    m = _FLOOR.search(name)
    if m:
        level = int(m.group(1) or m.group(2))
    s = _SUITE.search(name)
    if s and level is None:
        digits = re.sub(r"\D", "", s.group(1))
        if len(digits) >= 3:  # suite 750 is on floor 7, suite 1280 on floor 12
            level = int(digits[:-2])
    if _WAREHOUSE.search(name):
        return "warehouse", level or 1
    if _AMENITY.search(name) and not _UNIT.search(name):
        return "shared space", level
    if _UNIT.search(name):
        return "apartment unit", level
    if s or level:
        return "suite", level
    return "space", level


def _structure(s: dict, n: int) -> dict[str, Any]:
    defects = [d for d in DEFECTS if s.get(f"roof-defects.{d}.detected")]
    defects += [d for d in STAINS if s.get(f"roof-defects.discoloration.types.{d}.detected")]
    objects = {o: s.get(f"roof-objects.{o}.count") for o in ROOF_OBJECTS if s.get(f"roof-objects.{o}.count")}
    if s.get("roof-objects.solar.value"):
        objects["solar"] = s.get("roof-objects.solar-panel-photovoltaic.count") or 1
    poly = geo.largest_polygon(shapely_wkt.loads(s["footprint.wkt"]))
    return {
        "id": f"S{n}",
        "primary": bool(s.get("primary-structure")),
        "footprint_sqft": round(s.get("footprint.area") or 0),
        "roof_material": s.get("roof-characteristics.material.class"),
        "roof_shape": s.get("roof-characteristics.shape.value"),
        "roof_condition": s.get("roof-characteristics.condition"),
        "roof_defects": defects,
        "roof_objects": objects,
        "roof_tree_cover_percent": s.get("roof-characteristics.tree-cover.percent"),
        "trees_within_5ft_percent": s.get("defensible-space.zone1-tree"),
        "trees_5_to_30ft_percent": s.get("defensible-space.zone2-tree"),
        "trees_30_to_100ft_percent": s.get("defensible-space.zone3-tree"),
        "polygon": [[round(x, 7), round(y, 7)] for x, y in poly.exterior.coords],
        "centroid": [round(poly.centroid.x, 7), round(poly.centroid.y, 7)],
    }


def _scan(model_id: str, frame: geo.LocalFrame, model: dict | None = None) -> dict | None:
    try:
        m = model if model is not None else matterport.fetch_model(model_id)
    except matterport.MatterportError:
        return None
    kind, level = classify_scan(m.get("name"))
    g = m["geo"]
    sweeps = []
    if g.get("origin") and g.get("ex10") and g.get("ey10"):
        t = geo.initial_transform(frame, g["origin"], g["ex10"], g["ey10"])
        for s in m["sweeps"]:
            if not s["has_pano"]:
                continue
            x, y = t.apply(s["x"], s["y"])
            lon, lat = frame.to_lonlat(x, y)
            heading = None
            q = s.get("rotation")
            if q:  # face 1 looks along the sweep's yaw; faces 2-4 each turn 90 degrees clockwise
                yaw = math.atan2(2 * (q["w"] * q["z"] + q["x"] * q["y"]), 1 - 2 * (q["y"] ** 2 + q["z"] ** 2))
                (a, b), (c, d) = t.a
                heading = round(math.degrees(math.atan2(a * math.cos(yaw) + b * math.sin(yaw),
                                                        c * math.cos(yaw) + d * math.sin(yaw))) % 360, 1)
            sweeps.append({"id": s["id"], "lon": round(lon, 7), "lat": round(lat, 7), "heading": heading,
                           "room_id": s.get("room_id"), "floor_id": s.get("floor_id"),
                           "model_position": {k: s.get(k) for k in ("x", "y", "z")}})
        (a, _), (c, _) = t.a
        yaw_offset = round(-math.degrees(math.atan2(c, a)), 2)
    else:
        sweeps = [{"id": s["id"], "lon": None, "lat": None, "heading": None,
                   "room_id": s.get("room_id"), "floor_id": s.get("floor_id"),
                   "model_position": {k: s.get(k) for k in ("x", "y", "z")}}
                  for s in m["sweeps"] if s["has_pano"]]
        yaw_offset = None
    return {
        "id": m["id"], "name": m.get("name") or "Untitled scan", "kind": kind, "level": level,
        # Model API creation time is not the date the building was captured.
        "scanned": m.get("captured_at") or "",
        "captured_at": m.get("captured_at"), "model_created_at": m.get("created"),
        "rooms": m.get("rooms") or [], "floors": m.get("floors") or [],
        "association_basis": "sponsor_property_link; structure GPS candidate only",
        "area_sqft": m.get("area_with_walls_sqft") or m.get("area_indoor_sqft") or None,
        "origin": g.get("origin"), "altitude_m": g.get("altitude_m"),
        "sdk_yaw_offset": yaw_offset,  # viewer yaw that faces north; yaw = offset - bearing
        "sweeps": sweeps,
    }


def upgrade_cached_bundle(cached: dict) -> dict:
    """Migrate v3 metadata using local model caches only, without network calls."""
    if cached.get("version") == BUNDLE_VERSION:
        return cached
    frame = geo.LocalFrame(**cached["frame"])
    for old in cached.get("scans", []):
        model_path = matterport.MP_CACHE / old["id"] / "model.json"
        if model_path.exists():
            new = _scan(old["id"], frame, json.loads(model_path.read_text()))
            if new:
                old.update(new)
        else:
            old.update(model_created_at=old.get("scanned") or None, captured_at=None,
                       scanned="", rooms=[], floors=[],
                       association_basis="sponsor_property_link; structure GPS candidate only")
    cached["version"] = BUNDLE_VERSION
    return cached


def build(property_id: int, refresh: bool = False) -> dict:
    out_dir = building_dir(property_id)
    path = out_dir / "building.json"
    if path.exists() and not refresh:
        cached = json.loads(path.read_text())
        if cached.get("version") == BUNDLE_VERSION:
            return cached
        if cached.get("version") == 3:
            cached = upgrade_cached_bundle(cached)
            path.write_text(json.dumps(cached))
            return cached
    try:
        b = portfolio.building(property_id)
    except KeyError:
        raise BuildingError("unknown property")
    par = vexcel.parcel(b["lat"], b["lon"])
    if par is None:
        raise BuildingError("no aerial parcel record at this address")
    attrs = par["attributes"]
    raw = sorted([s for s in attrs.get("structures") or [] if s.get("footprint.wkt")],
                 key=lambda s: -(s.get("footprint.area") or 0))
    if not raw:
        raise BuildingError("no building footprint in the aerial data")
    structures = [_structure(s, i + 1) for i, s in enumerate(raw[:24])]

    frame = geo.LocalFrame(b["lat"], b["lon"])
    parcel = geo.largest_polygon(shapely_wkt.loads(par["parcel_wkt"]))
    # Frame the photo on the buildings; a parcel can be far larger than what stands on it.
    w, s_, e, n = Polygon([p for st in structures for p in st["polygon"]]).envelope.buffer(0).bounds if len(structures) > 1 \
        else Polygon(structures[0]["polygon"]).bounds
    span_x = (e - w) * geo.M_PER_DEG_LAT * math.cos(math.radians(b["lat"])) + 24
    span_y = (n - s_) * geo.M_PER_DEG_LAT + 24
    scale = min(1.0, MAX_AERIAL_PX / (max(span_x, span_y) / 0.075))
    max_px = (max(256, round(span_x / 0.075 * scale)), max(256, round(span_y / 0.075 * scale)))
    out_dir.mkdir(parents=True, exist_ok=True)
    img, info = vexcel.ortho(box(w, s_, e, n).wkt, buffer_m=12, max_px=max_px)
    shutil.copyfile(img, out_dir / "aerial.jpg")
    with Image.open(img) as im:
        width, height = im.size
    cell = max(5.0, math.ceil(max(span_x, span_y) / 16 / 5) * 5)  # metres, a multiple of 5
    try:
        obliques = vexcel.oblique_directions(Polygon(structures[0]["polygon"]).wkt)
    except vexcel.VexcelError:
        obliques = []

    scans = [sc for sc in (_scan(m, frame) for m in b["model_ids"][:MAX_SCANS]) if sc]
    polys = {st["id"]: Polygon(st["polygon"]) for st in structures}
    for sc in scans:  # which building on the site each scan was taken in (from the scan's own GPS fix)
        sc["structure"] = None
        if sc.get("origin"):
            pt = Point(sc["origin"])
            sid, poly = min(polys.items(), key=lambda kv: kv[1].distance(pt))
            if poly.distance(pt) <= 15 / geo.M_PER_DEG_LAT:
                sc["structure"] = sid
    bundle = {
        "version": BUNDLE_VERSION,
        "id": property_id,
        "record": b,
        "tenants": portfolio.tenants(property_id)[:40],
        "site": {
            "parcel": [[round(x, 7), round(y, 7)] for x, y in parcel.exterior.coords],
            "tree_cover_percent": attrs.get("parcel-tree-cover.percent"),
            "hardscape_percent": attrs.get("hardscapes.percent"),
            "vehicles_seen": attrs.get("vehicles.count"),
            "pool": bool(attrs.get("pool.detected")),
            "roof_analysis_date": (attrs.get("metadata.ortho-date-estimate") or "")[:10] or None,
            "structure_count": len(raw),
        },
        "structures": structures,
        "aerial": {"bounds": info["bounds"], "width": width, "height": height, "captured": info.get("last_capture"),
                   "collection": info.get("collection"),
                   "obliques": obliques, "grid": {"cols": max(3, math.ceil(span_x / cell)), "rows": max(3, math.ceil(span_y / cell)),
                                                  "cell_m": cell}},
        "scans": scans,
        "frame": {"lat0": frame.lat0, "lon0": frame.lon0},
    }
    path.write_text(json.dumps(bundle))
    return bundle


class Site:
    """A loaded bundle with geometry helpers for the agent and the API."""

    def __init__(self, data: dict):
        self.d = data
        self.id: int = data["id"]
        self.dir = building_dir(self.id)
        self.bounds = data["aerial"]["bounds"]
        self.size = (data["aerial"]["width"], data["aerial"]["height"])
        self.cols = data["aerial"]["grid"]["cols"]
        self.rows = data["aerial"]["grid"]["rows"]
        self.structures = {s["id"]: s for s in data["structures"]}
        self.polys = {s["id"]: Polygon(s["polygon"]) for s in data["structures"]}
        self.scans = {s["id"]: s for s in data["scans"]}
        self.frame = geo.LocalFrame(**data["frame"])

    @classmethod
    def load(cls, property_id: int) -> "Site":
        return cls(build(property_id))

    # --- aerial geometry -------------------------------------------------------
    def to_px(self, lon: float, lat: float) -> tuple[float, float]:
        w, s, e, n = self.bounds
        return (lon - w) / (e - w) * self.size[0], (n - lat) / (n - s) * self.size[1]

    def to_lonlat(self, px: float, py: float) -> tuple[float, float]:
        w, s, e, n = self.bounds
        return w + px / self.size[0] * (e - w), n - py / self.size[1] * (n - s)

    def cell_name(self, col: int, row: int) -> str:
        return f"{string.ascii_uppercase[col]}{row + 1}"

    def parse_cell(self, cell: str) -> tuple[int, int]:
        cell = cell.strip().upper()
        if len(cell) < 2 or cell[0] not in string.ascii_uppercase or not cell[1:].isdigit():
            raise ValueError(f"'{cell}' is not a grid cell like C4")
        col, row = string.ascii_uppercase.index(cell[0]), int(cell[1:]) - 1
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            raise ValueError(f"cell {cell} is outside the grid (columns A-{string.ascii_uppercase[self.cols - 1]}, rows 1-{self.rows})")
        return col, row

    def cell_center(self, cell: str) -> tuple[float, float]:
        col, row = self.parse_cell(cell)
        return self.to_lonlat((col + 0.5) / self.cols * self.size[0], (row + 0.5) / self.rows * self.size[1])

    def cell_of(self, lon: float, lat: float) -> str | None:
        px, py = self.to_px(lon, lat)
        col, row = int(px / self.size[0] * self.cols), int(py / self.size[1] * self.rows)
        return self.cell_name(col, row) if 0 <= col < self.cols and 0 <= row < self.rows else None

    def structure_at(self, lon: float, lat: float, slack_m: float = 3.0) -> dict | None:
        pt = Point(lon, lat)
        best = min(self.polys.items(), key=lambda kv: kv[1].distance(pt), default=None)
        if best and best[1].distance(pt) <= slack_m / geo.M_PER_DEG_LAT:
            return self.structures[best[0]]
        return None

    def face_for(self, scan_id: str, sweep_id: str, direction: str) -> tuple[int, float | None]:
        """Cube face of a sweep that looks up, down or toward a compass direction, with its true bearing."""
        direction = direction.lower()
        if direction == "up":
            return matterport.FACE_UP, None
        if direction == "down":
            return matterport.FACE_DOWN, None
        want = {"north": 0, "east": 90, "south": 180, "west": 270}[direction]
        sweep = next((s for s in self.scans[scan_id]["sweeps"] if s["id"] == sweep_id), None)
        h1 = sweep.get("heading") if sweep else None
        if h1 is None:
            return {"north": 1, "east": 2, "south": 3, "west": 4}[direction], None
        k = min(range(4), key=lambda i: abs(((h1 + 90 * i - want + 180) % 360) - 180))
        return k + 1, round((h1 + 90 * k) % 360, 1)

    # --- rendering -------------------------------------------------------------
    def render_aerial(self, grid: bool = True, labels: bool = True, markers: list[dict] | None = None,
                      scans: bool = False, crop_cell: str | None = None) -> Image.Image:
        """The site photo with structure outlines, an optional grid and markers ({lon, lat, label?, color?})."""
        im = Image.open(self.dir / "aerial.jpg").convert("RGB")
        w, h = im.size
        k = 2 if max(w, h) < 800 else 1
        if k > 1:
            im = im.resize((w * k, h * k), Image.LANCZOS)
        d = ImageDraw.Draw(im, "RGBA")
        font, small = _font(13 * k if k > 1 else 15), _font(9 * k if k > 1 else 11)

        def P(lon, lat):
            x, y = self.to_px(lon, lat)
            return x * k, y * k

        if grid:
            for c in range(self.cols + 1):
                x = c / self.cols * w * k
                d.line([(x, 0), (x, h * k)], fill=(255, 255, 255, 60), width=1)
            for r in range(self.rows + 1):
                y = r / self.rows * h * k
                d.line([(0, y), (w * k, y)], fill=(255, 255, 255, 60), width=1)
            for c in range(self.cols):
                for r in range(self.rows):
                    _text(d, ((c + 0.05) / self.cols * w * k, (r + 0.04) / self.rows * h * k), self.cell_name(c, r), small, (255, 255, 255, 230))
        for s in self.d["structures"]:
            d.line([P(*p) for p in s["polygon"]], fill=(255, 204, 0, 255), width=2 * k)
            if labels:
                _text(d, P(*s["centroid"]), s["id"], font, (255, 204, 0, 255))
        if scans:
            for sc in self.d["scans"]:
                if sc.get("origin"):
                    x, y = P(*sc["origin"])
                    d.ellipse([x - 5 * k, y - 5 * k, x + 5 * k, y + 5 * k], fill=(0, 229, 255, 255), outline=(0, 0, 0, 255))
        for m in markers or []:
            x, y = P(m["lon"], m["lat"])
            col = m.get("color") or (255, 64, 64, 255)
            rad = 9 * k
            d.ellipse([x - rad, y - rad, x + rad, y + rad], outline=col, width=3 * k)
            if m.get("label"):
                _text(d, (x + rad + 4, y - rad), m["label"], font, col)
        if crop_cell:
            col, row = self.parse_cell(crop_cell)
            cw, ch = im.width / self.cols, im.height / self.rows
            im = im.crop((int(max(0, (col - 1.5) * cw)), int(max(0, (row - 1.5) * ch)),
                          int(min(im.width, (col + 2.5) * cw)), int(min(im.height, (row + 2.5) * ch))))
            if max(im.size) < 900:
                f = 900 / max(im.size)
                im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        return im


def _font(size: int):
    for name in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/SFNS.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(d: ImageDraw.ImageDraw, xy, text: str, font, fill):
    x, y = xy
    d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 200))
    d.text((x, y), text, font=font, fill=fill)
