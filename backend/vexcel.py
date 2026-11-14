"""Vexcel API 2.0 client: parcel attributes, aerial imagery and open-vocabulary detection.

WKT is longitude-first. Every response is cached on disk, keyed by the request,
because the API is rate limited and detection is slow.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import httpx
from shapely import wkt as shapely_wkt
from shapely.geometry import shape

from .config import CACHE_DIR, VEXCEL_API_KEY, VEXCEL_LAYERS

API = "https://api.vexcelgroup.com/v2"
VX_CACHE = CACHE_DIR / "vexcel"
VX_CACHE.mkdir(parents=True, exist_ok=True)
OBLIQUES = ("oblique-north", "oblique-east", "oblique-south", "oblique-west")


class VexcelError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Vexcel {status}: {message}")
        self.status = status


def _send(method: str, path: str, *, params: dict | None = None, body: dict | None = None, timeout: float = 300) -> httpx.Response:
    last: httpx.Response | None = None
    for attempt in range(7):
        try:
            r = httpx.request(method, f"{API}/{path}", headers={"X-API-KEY": VEXCEL_API_KEY},
                              params=params, json=body, timeout=timeout)
        except httpx.HTTPError as e:
            if attempt == 6:
                raise VexcelError(0, str(e)) from e
            time.sleep(min(2 ** attempt, 20) + random.random())
            continue
        last = r
        if r.status_code not in (429, 502, 503, 504):
            return r
        time.sleep(min(2 ** attempt, 30) + random.random())
    assert last is not None
    return last


def _key(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:20]


def to_wkt(geometry: Any) -> str:
    if isinstance(geometry, str):
        return shapely_wkt.loads(geometry).wkt
    return shape(geometry).wkt


def parcel(lat: float, lon: float, refresh: bool = False) -> dict | None:
    """Parcel polygon, structures and attributes at a point. None if there is no parcel there."""
    path = VX_CACHE / "parcel" / f"{lat:.6f}_{lon:.6f}.json"
    if path.exists() and not refresh:
        data = json.loads(path.read_text())
        return data or None
    r = _send("GET", "property/extract", timeout=120, params={
        "wkt": f"POINT({lon} {lat})", "srid": 4326, "layer": VEXCEL_LAYERS,
        "latest": "true", "include": "precomputed", "unit-system": "imperial"})
    path.parent.mkdir(parents=True, exist_ok=True)
    if r.status_code == 404:
        path.write_text("null")
        return None
    if not r.is_success:
        raise VexcelError(r.status_code, r.text[:300])
    feats = r.json().get("features") or []
    if not feats:
        path.write_text("null")
        return None
    f = feats[0]
    out = {"parcel_wkt": to_wkt(f["geometry"]), "attributes": f["properties"]}
    path.write_text(json.dumps(out))
    return out


def _xmp(image: bytes) -> dict[str, str]:
    i, j = image.find(b"<x:xmpmeta"), image.find(b"</x:xmpmeta>")
    if i < 0 or j < 0:
        return {}
    text = image[i:j].decode("utf-8", "ignore")
    return dict(re.findall(r"<Vexcel:([\w-]+)>(.*?)</Vexcel:", text))


def _image(endpoint: str, body: dict, refresh: bool = False) -> tuple[Path, dict]:
    key = _key(endpoint, body)
    img = VX_CACHE / "images" / f"{key}.jpg"
    meta = VX_CACHE / "images" / f"{key}.json"
    if img.exists() and meta.exists() and not refresh:
        return img, json.loads(meta.read_text())
    r = _send("POST", endpoint, body=body)
    if not r.is_success:
        raise VexcelError(r.status_code, r.text[:300])
    x = _xmp(r.content)
    info: dict[str, Any] = {
        "collection": x.get("collection"),
        "first_capture": x.get("first-capture-date"),
        "last_capture": x.get("last-capture-date"),
        "product": x.get("product-type"),
    }
    if x.get("geometry"):
        w, s, e, n = shapely_wkt.loads(x["geometry"]).bounds
        info["bounds"] = [w, s, e, n]
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(r.content)
    meta.write_text(json.dumps(info))
    return img, info


def ortho(area_wkt: str, buffer_m: float = 8, drawing: list[dict] | None = None, refresh: bool = False,
          collection: str | None = None, max_px: tuple[int, int] | None = None) -> tuple[Path, dict]:
    """Straight-down image of an area. Returns (file, info) where info['bounds'] is [west, south, east, north].

    Without `collection` the API picks the best current imagery; with it, that specific capture.
    """
    body: dict[str, Any] = {"wkt": area_wkt, "srid": 4326, "layer": VEXCEL_LAYERS,
                            "buffer-meter": buffer_m, "crop": "bounding_box", "image-format": "jpeg"}
    if collection:
        body["collection"] = collection
    if max_px:
        body["destination-dimensions"] = f"{max_px[0]},{max_px[1]}"  # large sites: ask for a downsized image
    if drawing:
        body["drawing"] = drawing
    return _image("ortho/extract", body, refresh)


def captures(area_wkt: str, max_gsd: float = 0.12, *, thin: bool = True,
             refresh: bool = False, cached_only: bool = False) -> list[dict]:
    """Every ortho capture covering an area, newest first: [{collection, date, layer, gsd}].

    ``thin=False`` preserves nearby flights for before/after recovery comparisons.
    The v2 cache stores the full inventory; old half-year caches are never treated
    as complete inventories. ``cached_only`` makes no request on a cache miss.
    """
    path = VX_CACHE / "captures_v2" / f"{_key(area_wkt, VEXCEL_LAYERS)}.json"
    if path.exists() and not refresh:
        rows = json.loads(path.read_text())
        return _select_captures(rows, max_gsd, thin)
    if cached_only:
        return []
    r = _send("GET", "ortho/collections", timeout=120, params={
        "wkt": area_wkt, "srid": 4326, "layer": VEXCEL_LAYERS,
        "include": "collection,last-capture-date,layer,min-gsd"})
    if r.status_code == 404:
        rows: list[dict] = []
    elif not r.is_success:
        raise VexcelError(r.status_code, r.text[:300])
    else:
        rows = [{"collection": f["properties"]["collection"], "date": (f["properties"].get("last-capture-date") or "")[:10],
                 "layer": f["properties"].get("layer"), "gsd": round(f["properties"].get("min-gsd") or 9, 3)}
                for f in r.json().get("features") or []]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return _select_captures(rows, max_gsd, thin)


def _select_captures(rows: list[dict], max_gsd: float, thin: bool) -> list[dict]:
    best: dict[tuple[str, int] | str, dict] = {}
    for c in rows:
        if not c["date"] or c["gsd"] > max_gsd:
            continue
        slot = (c["date"][:4], 0 if c["date"][5:7] <= "06" else 1) if thin else c["collection"]
        if slot not in best or c["gsd"] < best[slot]["gsd"]:
            best[slot] = c
    return sorted(best.values(), key=lambda c: (c["date"], c["collection"]), reverse=True)


def oblique_directions(area_wkt: str) -> list[str]:
    """Which of the four angled views exist here (newest capture only)."""
    path = VX_CACHE / "oblique_dirs" / f"{_key(area_wkt)}.json"
    if path.exists():
        return json.loads(path.read_text())
    r = _send("GET", "oriented/collections", timeout=120, params={
        "wkt": area_wkt, "srid": 4326, "layer": "urban", "product-type": "oblique",
        "include": "product-type,collection,last-capture-date"})
    dirs: list[str] = []
    if r.is_success:
        feats = r.json().get("features") or []
        newest = max((f["properties"]["last-capture-date"] for f in feats), default=None)
        have = {f["properties"]["product-type"] for f in feats if f["properties"]["last-capture-date"] == newest}
        dirs = [d for d in OBLIQUES if d in have]
    elif r.status_code != 404:
        raise VexcelError(r.status_code, r.text[:300])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dirs))
    return dirs


def oblique(area_wkt: str, direction: str, buffer_m: float = 8, drawing: list[dict] | None = None) -> tuple[Path, dict]:
    """Angled view of an area looking in one compass direction."""
    body: dict[str, Any] = {"wkt": area_wkt, "srid": 4326, "layer": "urban", "product-type": direction,
                            "rotation": "natural", "buffer-meter": buffer_m, "crop": "bbox",
                            "image-format": "jpeg/png"}
    if drawing:
        body["drawing"] = drawing
    return _image("oriented/extract", body)


def detect(area_wkt: str, labels: list[str], threshold: float = 0.35, refresh: bool = False) -> list[dict]:
    """Open-vocabulary detection on the ortho image of an area.

    Returns [{label, confidence, bbox_wkt}] with boxes in map coordinates.
    """
    labels = sorted(set(labels))
    path = VX_CACHE / "detect" / f"{_key(area_wkt, labels, threshold)}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    body = {
        "wkt": area_wkt, "srid": 4326, "buffer-meter": 0,
        "images": [{"endpoint": "ortho/extract",
                    "request": {"layer": VEXCEL_LAYERS, "srid": 4326, "wkt": area_wkt, "crop": "bounding_box"}}],
        "model-input": {
            "elements": [{"label": l, "model": "sam3", "detection-threshold": threshold} for l in labels],
            "include": ["bbox", "confidence"],
        },
    }
    r = _send("POST", "elements/detect", body=body)
    if not r.is_success:
        raise VexcelError(r.status_code, r.text[:300])
    out = []
    for feat in r.json().get("features") or []:
        label = feat["properties"].get("label")
        for d in feat["properties"].get("detections") or []:
            if d.get("bbox"):
                out.append({"label": label, "confidence": round(d.get("confidence") or 0, 3), "bbox_wkt": to_wkt(d["bbox"])})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out
