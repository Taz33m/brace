"""Matterport Model API client (GraphQL).

Gives us, per scan: rooms with outlines, scan positions ("sweeps"), the six
panorama faces at each sweep, measured areas, and the model's own GPS
registration. Asset URLs expire, so faces are downloaded to disk on demand.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from .config import CACHE_DIR, MATTERPORT_API_KEY, MATTERPORT_API_TOKEN

GRAPH_URL = "https://api.matterport.com/api/models/graph"
MP_CACHE = CACHE_DIR / "matterport"
MP_CACHE.mkdir(parents=True, exist_ok=True)

SQFT_PER_SQM = 10.7639
# Skybox cube faces. Face 0 looks straight up, face 5 straight down; 1-4 are the sides.
FACE_UP, FACE_DOWN = 0, 5
SIDE_FACES = (1, 2, 3, 4)


class MatterportError(RuntimeError):
    pass


def gql(query: str, retries: int = 4) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.post(
                GRAPH_URL,
                json={"query": query},
                auth=(MATTERPORT_API_KEY, MATTERPORT_API_TOKEN),
                timeout=90,
            )
            if r.status_code in (429, 500, 502, 503, 504):
                raise MatterportError(f"HTTP {r.status_code}")
            r.raise_for_status()
            body = r.json()
            if body.get("errors") and not body.get("data"):
                raise MatterportError(json.dumps(body["errors"])[:400])
            return body["data"]
        except (httpx.HTTPError, MatterportError) as e:
            last = e
            if isinstance(e, MatterportError) and "Validation" in str(e):
                raise
            time.sleep(1.5 * (attempt + 1))
    raise MatterportError(f"Matterport request failed: {last}")


_MODEL_QUERY = """{ model(id:"%s"){
  id name created modified
  geocoordinates{ latitude longitude altitude source
    o: geoLocationOf(modelLocation:{x:0,y:0,z:0}){lat long}
    ex: geoLocationOf(modelLocation:{x:10,y:0,z:0}){lat long}
    ey: geoLocationOf(modelLocation:{x:0,y:10,z:0}){lat long} }
  dimensionEstimates(units:metric){ areaIndoor areaIndoorWithWalls }
  floors{ id label sequence dimensionEstimates(units:metric){ areaIndoor areaIndoorWithWalls } }
  rooms{ id label floor{id} classifications{label confidence}
    dimensionEstimates(units:metric){ areaIndoor height }
    boundary{ edges{ vertices{ position{x y} } } } }
  locations{ id position{x y z} neighbors floor{id} room{id} }
  panoLocations{ id position{x y z} rotation{x y z w} }
} }"""


def _room_polygon(room: dict) -> list[list[float]] | None:
    """Chain a room's boundary edges into one ring of [x, y] model coordinates."""
    lines = []
    for e in ((room.get("boundary") or {}).get("edges")) or []:
        v = e.get("vertices") or []
        if len(v) == 2:
            a, b = v[0]["position"], v[1]["position"]
            lines.append(LineString([(a["x"], a["y"]), (b["x"], b["y"])]))
    if len(lines) < 3:
        return None
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        return None
    poly: Polygon = max(polys, key=lambda p: p.area)
    return [[round(x, 3), round(y, 3)] for x, y in poly.exterior.coords]


def fetch_model(model_id: str, refresh: bool = False) -> dict[str, Any]:
    """Structure of one scan, normalised and cached on disk."""
    path = MP_CACHE / model_id / "model.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    m = gql(_MODEL_QUERY % model_id)["model"]
    if not m:
        raise MatterportError(f"model {model_id} not found")
    geo = m.get("geocoordinates") or {}

    def ll(k):
        g = geo.get(k) or {}
        return [float(g["long"]), float(g["lat"])] if g.get("long") else None

    rooms = []
    for r in m.get("rooms") or []:
        cls = (r.get("classifications") or [{}])[0].get("label") or "Unlabelled"
        dim = r.get("dimensionEstimates") or {}
        rooms.append({
            "id": r["id"],
            "type": cls,
            "label": r.get("label") or "",
            "floor_id": (r.get("floor") or {}).get("id"),
            "area_sqft": round((dim.get("areaIndoor") or 0) * SQFT_PER_SQM, 1),
            "height_m": dim.get("height") or None,
            "polygon": _room_polygon(r),
        })
    pano = {p["id"]: p for p in m.get("panoLocations") or []}
    sweeps = []
    for loc in m.get("locations") or []:
        p = pano.get(loc["id"])
        pos = (p or loc)["position"]
        sweeps.append({
            "id": loc["id"],
            "x": pos["x"], "y": pos["y"], "z": pos["z"],
            "rotation": (p or {}).get("rotation"),
            "room_id": (loc.get("room") or {}).get("id"),
            "floor_id": (loc.get("floor") or {}).get("id"),
            "neighbors": loc.get("neighbors") or [],
            "has_pano": p is not None,
        })
    dim = m.get("dimensionEstimates") or {}
    out = {
        "id": m["id"],
        "name": m.get("name"),
        "created": m.get("created"),
        "modified": m.get("modified"),
        "geo": {
            "source": geo.get("source"), "altitude_m": geo.get("altitude"),
            "origin": ll("o"), "ex10": ll("ex"), "ey10": ll("ey"),
        },
        "area_indoor_sqft": round((dim.get("areaIndoor") or 0) * SQFT_PER_SQM),
        "area_with_walls_sqft": round((dim.get("areaIndoorWithWalls") or 0) * SQFT_PER_SQM),
        "floors": sorted(
            [{"id": f["id"], "label": f.get("label"), "sequence": f.get("sequence") or 0,
              "area_with_walls_sqft": round(((f.get("dimensionEstimates") or {}).get("areaIndoorWithWalls") or 0) * SQFT_PER_SQM)}
             for f in m.get("floors") or []],
            key=lambda f: f["sequence"]),
        "rooms": rooms,
        "sweeps": sweeps,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def _face_path(model_id: str, sweep_id: str, face: int) -> Path:
    return MP_CACHE / model_id / "faces" / f"{sweep_id}_{face}.jpg"


def face_image(model_id: str, sweep_id: str, face: int) -> Path:
    """Path to one panorama cube face on disk, downloading it if needed."""
    path = _face_path(model_id, sweep_id, face)
    if path.exists():
        return path
    download_faces(model_id, [sweep_id], [face])
    if not path.exists():
        raise MatterportError(f"no panorama face {face} for sweep {sweep_id}")
    return path


def download_faces(model_id: str, sweep_ids: list[str], faces: list[int]) -> int:
    """Fetch fresh signed URLs for the given sweeps and download the missing faces."""
    todo = [s for s in sweep_ids if any(not _face_path(model_id, s, f).exists() for f in faces)]
    done = 0
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        ids = ",".join(f'"{s}"' for s in chunk)
        data = gql('{ model(id:"%s"){ panoLocations(ids:[%s]){ id skybox(resolution:"2k"){ status children } } } }' % (model_id, ids))
        with httpx.Client(timeout=90) as client:
            for p in data["model"]["panoLocations"]:
                children = (p.get("skybox") or {}).get("children") or []
                for f in faces:
                    path = _face_path(model_id, p["id"], f)
                    if path.exists() or f >= len(children):
                        continue
                    r = client.get(children[f])
                    if r.status_code == 200:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(r.content)
                        done += 1
    return done
