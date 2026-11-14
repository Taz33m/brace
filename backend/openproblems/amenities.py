"""Open problem: find and count amenities, place them, and check them against CoStar's listing.

Five sources can see an amenity, and each sighting keeps its source, its place and a confidence:

  aerial attribute  Vexcel's parcel record (pool, sport court, playground). Parcel-wide: no point.
  aerial detector   Vexcel's open-vocabulary detector on the straight-down photo. A box on the site.
  scan name         the title a person gave a Matterport scan ("Fitness Center").
  room label        the room type Matterport assigned inside a scan ("Laundry").
  panorama          what the vision model reports from a scan position (cached surveys, plus a
                    short amenity look at shared-space scans).

Merging rule (see `merge`): an amenity is counted once per PLACE, never once per source.
  1. Boxes of one kind that overlap (detector boxes, Vexcel footprints) are one place.
  2. A sighting standing in the amenity with a site point joins a place of that kind within 30 m,
     otherwise it is a new place.
  3. A sighting that only looks at the amenity from nearby joins the nearest place within 60 m.
  4. A sighting with no site point (a parcel-wide attribute, a scan with no GPS fix) confirms the
     kind but never adds to the count. If nothing else placed the kind, all of them together are 1.
     A scan with no GPS fix that sees a placed scan's amenity nearby borrows that point, and is
     then treated as rule 3: it can join a place, never make one.

CoStar side: the kit's property record carries `amenities[]` as ids without names, so those cannot
be compared. What the listing names is in the captions of its published media (`attachments[].caption`,
for example "Pool #3", "Laundry Room") and in its parking types; that is what `listed` reads.

Paid calls are capped and counted in a ledger on disk; every result is cached under
data/cache/open/amenities/ so nothing is paid for twice.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Callable

from shapely.geometry import Point, Polygon, box
from shapely import wkt as shapely_wkt

from .. import geo
from ..building import BUNDLE_VERSION, BuildingError, Site, building_dir, upgrade_cached_bundle
from ..config import CACHE_DIR, KIT_DIR, VISION_MODEL

CACHE = CACHE_DIR / "open" / "amenities"
DETECTOR_LIMIT = 30
VISION_LIMIT = 60
MAX_LOOKS_PER_SCAN = 6
PARCEL_SLACK_M = 8.0
SAME_PLACE_M = 30.0     # a scan standing in an amenity and a box of that amenity
SEEN_FROM_M = 60.0      # a camera that only looks at the amenity from nearby
LOOSE_ITEM_M = 15.0     # loose furniture counted with a pool
CONFIRMED_AT = 0.6      # below this, and seen by one source only, an amenity is reported as unconfirmed

AERIAL_ATTRIBUTE, AERIAL_DETECTOR, SCAN_NAME, ROOM_LABEL, PANORAMA = (
    "aerial attribute", "aerial detector", "scan name", "room label", "panorama")
WHOLE_SITE = (AERIAL_ATTRIBUTE, AERIAL_DETECTOR)  # sources that cover the whole parcel
SCAN_BASED = (SCAN_NAME, ROOM_LABEL, PANORAMA)    # sources that cover only the scanned rooms

# kind -> which sources are able to see it, how CoStar's captions name it, how scans name it.
KINDS: dict[str, dict[str, Any]] = {
    "pool": {"sources": (AERIAL_ATTRIBUTE, AERIAL_DETECTOR, SCAN_NAME, PANORAMA),
             "caption": r"\bpool(side)?s?\b(?! table)", "scan": r"\bpool\b(?! table)"},
    "fitness room": {"sources": SCAN_BASED, "caption": r"fitness|\bgym\b|exercise|weight room", "scan": r"fitness|\bgym\b"},
    "clubhouse or lounge": {"sources": SCAN_BASED, "caption": r"club ?house|club ?room|lounge|community room|game room",
                            "scan": r"club|lounge|community room|game room"},
    "laundry room": {"sources": SCAN_BASED, "caption": r"laundry", "scan": r"laundry"},
    "leasing office": {"sources": SCAN_BASED, "caption": r"leasing|management office", "scan": r"leasing|\boffice$"},
    "lobby": {"sources": SCAN_BASED, "caption": r"\blobby\b", "scan": r"\blobby\b"},
    "playground": {"sources": WHOLE_SITE, "caption": r"playground|tot lot|play area", "scan": r"playground"},
    "sport court": {"sources": WHOLE_SITE, "caption": r"tennis|basketball|volleyball|pickleball|sport", "scan": r"court\b"},
    "dog park": {"sources": (), "caption": r"dog park|bark park|pet park|dog run", "scan": r"dog park"},
    "covered parking": {"sources": (AERIAL_ATTRIBUTE, AERIAL_DETECTOR), "caption": r"carport|covered parking|garage", "scan": r"garage|carport"},
    "grill or picnic area": {"sources": (PANORAMA,), "caption": r"grill|bbq|barbe|picnic", "scan": r"grill|picnic"},
    "business centre": {"sources": SCAN_BASED, "caption": r"business cent|conference|co-?work", "scan": r"business|conference"},
    "mail room": {"sources": SCAN_BASED, "caption": r"\bmail|package", "scan": r"\bmail|package"},
    "gazebo or cabana": {"sources": (AERIAL_DETECTOR, PANORAMA), "caption": r"gazebo|cabana|pergola|pergula|pavilion", "scan": r"gazebo|cabana"},
    "courtyard": {"sources": (PANORAMA,), "caption": r"courtyard", "scan": r"courtyard"},
}
IN_UNIT_LAUNDRY = "in-unit laundry"  # found inside apartment scans; not a shared amenity, kept out of the comparison

# Detector label -> amenity kind. Two requests per building: fixed amenities, then loose things.
DETECT_AMENITIES = {"swimming pool": "pool", "carport": "covered parking", "playground": "playground",
                    "tennis court": "sport court", "basketball court": "sport court", "gazebo": "gazebo or cabana"}
# "carport" itself returned nothing on these sites; a carport row seen from above is a long pale shed roof.
# That label is loose (it also fires on buildings), so a box is kept only off building footprints and at 0.5 or more.
DETECT_CARPORT = {"long white shed roof": "covered parking"}
CARPORT_MIN_SCORE = 0.5
# Loose furniture is too small to find across a whole site, so it is looked for in a small window around each pool.
DETECT_LOOSE = ["lounge chair", "patio table", "patio umbrella"]
POOL_WINDOW_M = 18.0
# A carport row in Vexcel's footprints: one parking stall deep, at least two stalls long, not a shingle roof.
CARPORT_DEPTH_M = (4.8, 6.6)
CARPORT_MIN_LENGTH_M = 10.0

_UNIT_CAPTION = re.compile(r"\b\d\s*(br|bd|bed|ba)\b|studio|bedroom|bathroom|kitchen|living|dining|closet", re.I)
_UNIT_SCAN = re.compile(r"\b\d\s*(br|bd|bed)|studio|\bunit\b|\bplan\b|\bloft\b|penthouse|\bmodel\b", re.I)
_NUMBERED = re.compile(r"#\s*(\d+)")
_COVERED_PARKING = {"Covered", "CoveredTandem", "AttachedGarage", "OneCarGarage", "TwoCarGarage"}
_COVERED_POLICY = {"CoveredLot", "Carport", "Garage", "GarageAttached", "GarageDetached"}

LOOK_PROMPT = (
    "These four photos are the four horizontal views from one camera position in a shared space of an apartment "
    "community, in clockwise order. We are listing the community's amenities and what must be secured at each before "
    "a severe storm. Report only what is visible. `here`: the amenity the camera is standing in. `visible_nearby`: "
    "other amenities you can see from here, through a door or window or across a deck. `loose_items`: things that "
    "could be thrown or broken (chairs, tables, umbrellas, grills, decor). `equipment`: machines or electronics that "
    "sit on the floor. Leave a list empty rather than guess."
)
_LOOK_KINDS = ["pool", "fitness room", "clubhouse or lounge", "laundry room", "leasing office", "lobby", "playground",
               "sport court", "dog park", "covered parking", "grill or picnic area", "business centre", "mail room",
               "gazebo or cabana", "courtyard"]
LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "here": {"type": "array", "items": {"type": "string", "enum": _LOOK_KINDS}},
        "visible_nearby": {"type": "array", "items": {"type": "string", "enum": _LOOK_KINDS}},
        "loose_items": {"type": "array", "items": {"type": "string"}, "description": "Up to six short noun phrases."},
        "equipment": {"type": "array", "items": {"type": "string"}, "description": "Up to six short noun phrases."},
        "glass": {"type": "string", "enum": ["none", "some windows", "large windows", "mostly glass"]},
        "sure": {"type": "string", "enum": ["high", "medium", "low"]},
        "note": {"type": "string", "description": "One sentence on what this space is."},
    },
    "required": ["here", "visible_nearby", "loose_items", "equipment", "glass", "sure", "note"],
    "additionalProperties": False,
}
_SURE = {"high": 0.9, "medium": 0.7, "low": 0.5}
_GLASS_ORDER = ["none", "some windows", "large windows", "mostly glass"]


class BudgetExceeded(RuntimeError):
    pass


class NoPanorama(RuntimeError):
    """The scan position's images could not be read, so there was nothing to show the model."""


class Budget:
    """Counts paid calls across runs. A call is charged before it is made; a cached result is never charged."""

    def __init__(self, path: Path | None = None, detector_limit: int = DETECTOR_LIMIT, vision_limit: int = VISION_LIMIT):
        self.path = path or CACHE / "ledger.json"
        self.limits = {"detector": detector_limit, "vision": vision_limit}
        self.used = {"detector": 0, "vision": 0}
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            self.used = {k: int(saved.get("used", {}).get(k, 0)) for k in self.used}

    def left(self, kind: str) -> int:
        return self.limits[kind] - self.used[kind]

    def charge(self, kind: str, what: str = "") -> None:
        if self.left(kind) <= 0:
            raise BudgetExceeded(f"{kind} budget of {self.limits[kind]} calls is spent")
        self.used[kind] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        log = json.loads(self.path.read_text()).get("log", []) if self.path.exists() else []
        log.append({"kind": kind, "what": what, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        self.path.write_text(json.dumps({"limits": self.limits, "used": self.used, "log": log}, indent=1))

    def summary(self) -> dict:
        return {"detector_calls_used": self.used["detector"], "detector_limit": self.limits["detector"],
                "vision_calls_used": self.used["vision"], "vision_limit": self.limits["vision"]}


# --- CoStar: what the listing says ------------------------------------------------

def _enum(enums: dict, name: str, value: Any) -> str | None:
    return (enums.get(name) or {}).get(str(value))


def listed_from_record(record: dict, enums: dict, has_apartment_listing: bool | None = None) -> dict:
    """What a CoStar property record says the property has. No contact fields are read."""
    captions: dict[tuple[str, bool], dict] = {}
    for a in record.get("attachments") or []:
        text = (a.get("caption") or "").strip()
        if not text or _UNIT_CAPTION.search(text):
            continue  # unit photos ("2 BR, 1 BA - Kitchen") describe a floor plan, not a shared amenity
        tour = a.get("videoExternalReferenceType") in (36, 234)
        row = captions.setdefault((text, tour), {"caption": text, "photos": 0, "is_3d_tour": tour,
                                                 "type": _enum(enums, "AttachmentType", a.get("attachmentType"))})
        row["photos"] += 1
    listed: dict[str, dict] = {}
    for row in captions.values():
        for kind, spec in KINDS.items():
            if re.search(spec["caption"], row["caption"], re.I):
                item = listed.setdefault(kind, {"kind": kind, "count": None, "evidence": []})
                item["evidence"].append({"field": "attachments[].caption", "value": row["caption"], "photos": row["photos"],
                                         "is_3d_tour": row["is_3d_tour"]})
                n = _NUMBERED.search(row["caption"])
                if n:  # "Pool #3" says there are at least three
                    item["count"] = max(item["count"] or 0, int(n.group(1)))
    parking = sorted({_enum(enums, "ParkingType", p.get("parkingType")) or "Unknown" for p in record.get("parking") or []})
    profile = ((record.get("propertyApartment") or {}).get("residentialProfile") or {})
    policies = sorted({_enum(enums, "ResidentialParkingType", p.get("parkingType")) or "Unknown"
                       for p in profile.get("parkingPolicies") or []})
    for field, values, wanted in (("parking[].parkingType", parking, _COVERED_PARKING),
                                  ("propertyApartment.residentialProfile.parkingPolicies[].parkingType", policies, _COVERED_POLICY)):
        for v in values:
            if v in wanted:
                item = listed.setdefault("covered parking", {"kind": "covered parking", "count": None, "evidence": []})
                item["evidence"].append({"field": field, "value": v, "is_3d_tour": False})
    for item in listed.values():
        item["tour_caption_only"] = all(e.get("is_3d_tour") for e in item["evidence"])
    ids = record.get("amenities") or []
    return {
        "property_id": record.get("id"), "name": record.get("buildingName"),
        "source": "CoStar kit data/commercial-property.jsonl, joined on the record's `id` (the property id); "
                  "apartment-listing.jsonl joins on `propertyId` and carries rents only, no amenities",
        "has_apartment_listing": has_apartment_listing,
        "amenity_ids": ids,
        "amenity_ids_note": f"{len(ids)} amenity ids on the record; the kit gives ids without names, so they are not compared",
        "captions_read": sorted(captions.values(), key=lambda r: (-r["photos"], r["caption"])),
        "parking_types": parking, "parking_policy_types": policies,
        "listed": sorted(listed.values(), key=lambda i: i["kind"]),
    }


def listing(property_id: int, cache_dir: Path | None = None) -> dict:
    """The listing facts for one property, read once from the kit and cached."""
    path = (cache_dir or CACHE) / "listing" / f"{property_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    enums = json.loads((KIT_DIR / "schemas" / "enums.json").read_text())
    record = None
    needle = f'"id": {property_id},'
    with open(KIT_DIR / "data" / "commercial-property.jsonl") as f:
        for line in f:
            if needle in line[:200] or f'"id":{property_id},' in line[:200]:
                r = json.loads(line)
                if r.get("id") == property_id:
                    record = r
                    break
    if record is None:
        raise KeyError(f"property {property_id} is not in the CoStar kit")
    has_listing = False
    with open(KIT_DIR / "data" / "apartment-listing.jsonl") as f:
        for line in f:
            if f'"propertyId": {property_id},' in line or f'"propertyId":{property_id},' in line:
                has_listing = True
                break
    out = listed_from_record(record, enums, has_listing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return out


# --- our side: sightings ----------------------------------------------------------

def load_site(property_id: int) -> Site:
    """The cached bundle, read only. An older bundle is upgraded in memory and never written back."""
    path = building_dir(property_id) / "building.json"
    if not path.exists():
        raise BuildingError("no cached bundle for this property")
    data = json.loads(path.read_text())
    if data.get("version") != BUNDLE_VERSION:
        data = upgrade_cached_bundle(data)
    return Site(data)


def _sighting(kind: str, source: str, confidence: float, basis: str, place: dict, detail: str,
              anchor: str = "at", storm: dict | None = None) -> dict:
    return {"kind": kind, "source": source, "confidence": round(float(confidence), 2), "confidence_basis": basis,
            "anchor": anchor, "place": place, "detail": detail, **({"storm": storm} if storm else {})}


def _site_place(site: Site, lon: float, lat: float, bbox: list[float] | None = None) -> dict:
    st = site.structure_at(lon, lat)
    place = {"type": "site point", "lon": round(lon, 7), "lat": round(lat, 7), "cell": site.cell_of(lon, lat),
             "structure": st["id"] if st else None}
    if bbox:
        place["bbox"] = [round(v, 7) for v in bbox]
    return place


def _scan_place(site: Site, scan: dict, sweep: dict | None = None, room: dict | None = None) -> dict:
    lon, lat = (sweep or {}).get("lon"), (sweep or {}).get("lat")
    if lon is None and scan.get("origin"):
        lon, lat = scan["origin"]
    place = {"type": "scan", "scan_id": scan["id"], "scan_name": scan["name"], "structure": scan.get("structure"),
             "lon": lon, "lat": lat, "cell": site.cell_of(lon, lat) if lon is not None else None}
    if lon is None:
        place["note"] = "this scan has no GPS fix, so it is placed by scan only"
    if sweep:
        place["sweep_id"] = sweep["id"]
    if room:
        place["room_id"], place["room_type"] = room.get("id"), room.get("type")
    return place


def attribute_sightings(site: Site, attributes: dict | None) -> tuple[list[dict], dict]:
    """Vexcel's parcel-wide attributes. They say an amenity exists on the parcel, not where or how many."""
    if attributes is None:
        return [], {"status": "not checked", "detail": "no cached Vexcel parcel record for this address"}
    parcel = Polygon(site.d["site"]["parcel"]).centroid
    place = {"type": "parcel", "lon": round(parcel.x, 7), "lat": round(parcel.y, 7),
             "note": "parcel-wide attribute: the parcel centre is given, not the amenity's own position"}
    out = []
    if attributes.get("pool.detected"):
        kinds = [t for t in ("in-ground", "above-ground", "hot-tub") if attributes.get(f"pool.types.{t}.detected")]
        area = attributes.get("pool.total-area")
        out.append(_sighting("pool", AERIAL_ATTRIBUTE, attributes.get("pool.score") or 0.5, "Vexcel attribute score", place,
                             f"pool.detected ({', '.join(kinds) or 'type not given'}; {round(area) if area else '?'} sq ft of water in total; no count given)",
                             anchor="parcel"))
    if attributes.get("sport-court.detected"):
        out.append(_sighting("sport court", AERIAL_ATTRIBUTE, attributes.get("sport-court.score") or 0.5,
                             "Vexcel attribute score", place, "sport-court.detected", anchor="parcel"))
    if attributes.get("playground.detected"):
        out.append(_sighting("playground", AERIAL_ATTRIBUTE, attributes.get("playground.score") or 0.5,
                             "Vexcel attribute score", place, "playground.detected", anchor="parcel"))
    carports = 0
    for st in attributes.get("structures") or []:
        dims = _footprint_dims(st)
        if dims and _is_carport(st, dims):
            poly = geo.largest_polygon(shapely_wkt.loads(st["footprint.wkt"]))
            c = poly.centroid
            spot = _site_place(site, c.x, c.y, list(poly.bounds))
            spot["footprint"] = [[round(x, 7), round(y, 7)] for x, y in poly.exterior.coords]
            out.append(_sighting("covered parking", AERIAL_ATTRIBUTE, 0.7,
                                 "assigned: shape rule on a Vexcel footprint, not a Vexcel class", spot,
                                 f"footprint {dims[0]:.1f} m deep and {dims[1]:.1f} m long with a "
                                 f"{st.get('roof-characteristics.material.class') or 'unclassed'} roof: one parking stall deep"))
            carports += 1
    date = (attributes.get("metadata.ortho-date-estimate") or "")[:10]
    return out, {"status": "checked", "carport_shaped_footprints": carports,
                 "detail": f"Vexcel parcel record (pool, sport court, playground; carport rows by footprint shape), imagery of {date or 'unknown date'}"}


def _footprint_dims(structure: dict) -> tuple[float, float] | None:
    """(short side, long side) in metres of a structure footprint's tightest rectangle."""
    if not structure.get("footprint.wkt"):
        return None
    rect = geo.largest_polygon(shapely_wkt.loads(structure["footprint.wkt"])).minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    a = _metres((xs[0], ys[0]), (xs[1], ys[1]))
    b = _metres((xs[1], ys[1]), (xs[2], ys[2]))
    return min(a, b), max(a, b)


def _is_carport(structure: dict, dims: tuple[float, float]) -> bool:
    return (CARPORT_DEPTH_M[0] <= dims[0] <= CARPORT_DEPTH_M[1] and dims[1] >= CARPORT_MIN_LENGTH_M
            and structure.get("roof-characteristics.material.class") != "shingle")


def _iou(a, b) -> float:
    union = a.union(b).area
    return a.intersection(b).area / union if union else 0.0


def _detect_cached(site: Site, labels: list[str], detector: Callable | None, budget: Budget, cache_dir: Path,
                   area: str | None = None) -> tuple[list[dict] | None, str]:
    """Detector rows for an area (the whole aerial frame by default). Returns (rows or None, how they were obtained)."""
    threshold = 0.35  # vexcel.detect's own default; part of the cache key
    if area is None:
        w, s, e, n = site.bounds
        area = Polygon([(w, s), (e, s), (e, n), (w, n)]).wkt
    labels = sorted(set(labels))
    key = hashlib.sha1(json.dumps([area, labels, threshold]).encode()).hexdigest()[:16]
    path = cache_dir / "detect" / f"{site.id}_{key}.json"
    if path.exists():
        return json.loads(path.read_text())["rows"], "cache"
    if detector is None:
        return None, "no detector given and nothing cached"
    try:
        budget.charge("detector", f"{site.id}: {', '.join(labels)}")
    except BudgetExceeded as ex:
        return None, str(ex)
    try:
        rows = detector(area, labels)
    except Exception as ex:  # a failed call is still counted; it is not cached
        return None, f"detector error: {type(ex).__name__}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"property_id": site.id, "area_wkt": area, "labels": labels, "threshold": threshold,
                                "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows}))
    return rows, "call"


def detector_sightings(site: Site, detector: Callable | None, budget: Budget, cache_dir: Path,
                       attributes: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """Boxes from the aerial detector inside the parcel: (amenity sightings, loose-item boxes, source status)."""
    parcel = Polygon(site.d["site"]["parcel"]).buffer(PARCEL_SLACK_M / geo.M_PER_DEG_LAT)
    # Footprints that are buildings, not carport rows. A "shed roof" box that matches one of these is the building
    # itself. A box beside or partly on one is kept: Vexcel sometimes fuses a carport row into the building next to it.
    buildings = []
    for st in (attributes or {}).get("structures") or []:
        dims = _footprint_dims(st)
        if dims and not _is_carport(st, dims):
            buildings.append(geo.largest_polygon(shapely_wkt.loads(st["footprint.wkt"])))
    sightings, loose, how = [], [], []
    dropped = {"outside_parcel": 0, "is_a_building": 0, "low_score": 0}
    checked_labels: list[str] = []
    for group in (DETECT_AMENITIES, DETECT_CARPORT):
        rows, got = _detect_cached(site, list(group), detector, budget, cache_dir)
        how.append(got)
        if rows is None:
            continue
        checked_labels += sorted(group)
        for r in rows:
            b = shapely_wkt.loads(r["bbox_wkt"])
            c = b.centroid
            if not parcel.contains(c):
                dropped["outside_parcel"] += 1
                continue
            if group is DETECT_CARPORT:
                if r["confidence"] < CARPORT_MIN_SCORE:
                    dropped["low_score"] += 1
                    continue
                if any(_iou(b, box(*f.bounds)) >= 0.5 for f in buildings):
                    dropped["is_a_building"] += 1
                    continue
            sightings.append(_sighting(group[r["label"]], AERIAL_DETECTOR, r["confidence"], "detector score",
                                       _site_place(site, c.x, c.y, list(b.bounds)), f"detector label '{r['label']}'"))
    rejected = None
    if dropped["is_a_building"]:
        # Self-check: where the carport label fires on roofs we know are buildings, it cannot tell the two apart
        # on this site, so none of its boxes are trusted here.
        n = sum(1 for x in sightings if x["kind"] == "covered parking")
        sightings = [x for x in sightings if x["kind"] != "covered parking"]
        rejected = (f"'{next(iter(DETECT_CARPORT))}' fired on {dropped['is_a_building']} building roofs here, "
                    f"so its other {n} boxes were not trusted")
    windows = 0
    done: list[tuple[float, float]] = []
    for s in [x for x in sightings if x["kind"] == "pool"]:
        pt = (s["place"]["lon"], s["place"]["lat"])
        if any(_metres(pt, d) < 10 for d in done):
            continue
        done.append(pt)
        dy = POOL_WINDOW_M / geo.M_PER_DEG_LAT
        dx = dy / math.cos(math.radians(pt[1]))
        rows, got = _detect_cached(site, DETECT_LOOSE, detector, budget, cache_dir,
                                   area=box(pt[0] - dx, pt[1] - dy, pt[0] + dx, pt[1] + dy).wkt)
        how.append(got)
        if rows is None:
            continue
        windows += 1
        for r in rows:
            c = shapely_wkt.loads(r["bbox_wkt"]).centroid
            loose.append({"label": r["label"], "confidence": r["confidence"], "lon": round(c.x, 7), "lat": round(c.y, 7),
                          "cell": site.cell_of(c.x, c.y), "near_pool_at": s["place"]["cell"]})
    if not checked_labels:
        status = {"status": "not checked", "detail": "; ".join(sorted(set(how)))}
    else:
        full = len(checked_labels) == len(DETECT_AMENITIES) + len(DETECT_CARPORT)
        status = {"status": "checked" if full else "partly checked", "labels": checked_labels,
                  "obtained": {g: how.count(g) for g in sorted(set(how))},
                  "boxes_kept": len(sightings), "boxes_dropped": dropped,
                  "pool_windows_checked_for_loose_furniture": windows, "loose_furniture_boxes": len(loose),
                  "detail": "Vexcel detector over the aerial frame, kept only inside the parcel"}
        if rejected:
            status["carport_label_rejected"] = rejected
    return sightings, loose, status


def scan_kind(name: str | None) -> str | None:
    """The amenity a scan title names, or None for an apartment unit or an untitled space."""
    name = name or ""
    if _UNIT_SCAN.search(name):
        return None
    for kind, spec in KINDS.items():
        if re.search(spec["scan"], name, re.I):
            return kind
    return None


def scan_sightings(site: Site) -> tuple[list[dict], dict, dict]:
    """Scan titles and Matterport room types."""
    out, labelled, rooms_total = [], 0, 0
    scans = site.d["scans"]
    for sc in scans:
        kind = scan_kind(sc["name"])
        if kind:
            out.append(_sighting(kind, SCAN_NAME, 0.9, "assigned: a person titled the scan", _scan_place(site, sc),
                                 f"scan titled '{sc['name']}'"))
        for room in sc.get("rooms") or []:
            rooms_total += 1
            rtype, label = room.get("type") or "", room.get("label") or ""
            if rtype not in ("", "Unlabelled", "Void") or label:
                labelled += 1
            text = f"{label} {rtype}"
            if kind is None and _UNIT_SCAN.search(sc["name"] or ""):
                if re.search(r"laundry", text, re.I):
                    out.append(_sighting(IN_UNIT_LAUNDRY, ROOM_LABEL, 0.8, "assigned: Matterport's own room type",
                                         _scan_place(site, sc, room=room), f"room typed '{rtype or label}' inside unit scan '{sc['name']}'"))
                continue
            for k, spec in KINDS.items():
                if re.search(spec["scan"], text, re.I):
                    out.append(_sighting(k, ROOM_LABEL, 0.8, "assigned: Matterport's own room type",
                                         _scan_place(site, sc, room=room), f"room typed '{rtype or label}' in scan '{sc['name']}'"))
    names = {"status": "checked" if scans else "not checked",
             "detail": f"{len(scans)} scan titles read" if scans else "no scans are attached to this property"}
    rooms = {"status": "checked" if rooms_total else "not checked",
             "detail": f"{labelled} of {rooms_total} rooms across {len(scans)} scans carry a room type or label"
             if rooms_total else "the scans carry no rooms"}
    return out, names, rooms


def _pano_image(scan_id: str, sweep_id: str):
    from .. import vision  # imported late: it loads the Anthropic SDK
    return vision.image_block(vision.strip(scan_id, sweep_id), max_side=2048)


def look(scan_id: str, sweep_id: str, client, budget: Budget, cache_dir: Path) -> dict | None:
    """One amenity look at one scan position, called the way backend/vision.py calls the model. Cached."""
    path = cache_dir / "looks" / f"{scan_id}_{sweep_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    if client is None:
        return None
    try:
        image = _pano_image(scan_id, sweep_id)
    except Exception as ex:  # no panorama to show; nothing was paid for
        raise NoPanorama(f"{type(ex).__name__}") from ex
    budget.charge("vision", f"{scan_id}/{sweep_id}")
    resp = client.messages.create(
        model=VISION_MODEL, max_tokens=1024,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": LOOK_SCHEMA}},
        messages=[{"role": "user", "content": [image, {"type": "text", "text": LOOK_PROMPT}]}],
    )
    if resp.stop_reason == "refusal":
        return None
    try:
        out = {"scan_id": scan_id, "sweep_id": sweep_id, "model": VISION_MODEL,
               **json.loads(next(b.text for b in resp.content if b.type == "text"))}
    except (StopIteration, json.JSONDecodeError):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return out


def _spread(items: list, n: int) -> list:
    if len(items) <= n:
        return list(items)
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]


def panorama_sightings(site: Site, client, budget: Budget, cache_dir: Path) -> tuple[list[dict], dict]:
    """What the vision model saw from scan positions in shared-space scans.

    Cached general surveys are read first (free). A short amenity look is added for up to
    MAX_LOOKS_PER_SCAN positions of each shared-space scan when a client is given.
    """
    out: list[dict] = []
    looked, not_looked, stopped = [], [], None
    no_image: set[str] = set()
    for sc in site.d["scans"]:
        kind = scan_kind(sc["name"])
        if kind is None:
            continue  # apartment units are not amenities
        sweeps = {s["id"]: s for s in sc["sweeps"]}
        seen_here = 0
        survey_path = site.dir / "surveys" / f"{sc['id']}.json"
        survey_rows = json.loads(survey_path.read_text()) if survey_path.exists() else []
        for row in survey_rows:
            sweep = sweeps.get(row["sweep_id"])
            storm = {"glass": row.get("glass"), "exterior_doors": row.get("exterior_doors"),
                     "loose_items": row.get("floor_level_items") or [], "equipment": []}
            note = row.get("note") or ""
            place = _scan_place(site, sc, sweep or {"id": row["sweep_id"]})
            if re.search(KINDS[kind]["scan"], note, re.I):
                out.append(_sighting(kind, PANORAMA, 0.7, "assigned: the cached survey's description names it", place,
                                     note, storm=storm))
                seen_here += 1
            if kind != "pool" and re.search(r"\bpool\b(?! table)", note, re.I):
                out.append(_sighting("pool", PANORAMA, 0.6, "assigned: the cached survey's description mentions a pool outside",
                                     place, note, anchor="from"))
        # Positions the cached survey already used have their images on disk, so those are looked at first.
        surveyed = [r["sweep_id"] for r in survey_rows if r["sweep_id"] in sweeps]
        picks = _spread(surveyed or list(sweeps), MAX_LOOKS_PER_SCAN)
        for sweep_id in picks:
            try:
                row = look(sc["id"], sweep_id, client, budget, cache_dir)
            except BudgetExceeded as ex:
                stopped, row = str(ex), None
            except NoPanorama:
                no_image.add(sc["name"])
                row = None
            if not row:
                continue
            place = _scan_place(site, sc, sweeps[sweep_id])
            storm = {"glass": row.get("glass"), "exterior_doors": None, "loose_items": row.get("loose_items") or [],
                     "equipment": row.get("equipment") or []}
            conf = _SURE.get(row.get("sure"), 0.5)
            here = list(dict.fromkeys(row.get("here") or []))
            # One room is one amenity. The scan's title names the room, so whatever the model calls this position
            # is a sighting of the titled kind, at lower confidence when the model used another word for it.
            other = [k for k in here if k != kind]
            out.append(_sighting(kind, PANORAMA, conf if kind in here else max(0.4, conf - 0.2),
                                 "the vision model's own rating" if kind in here
                                 else "the vision model's own rating, lowered: it used another word for this room",
                                 place, (row.get("note") or "") + (f" [the model also called this position: {', '.join(other)}]" if other else ""),
                                 storm=storm))
            seen_here += 1
            for k in dict.fromkeys(row.get("visible_nearby") or []):
                if k != kind and k not in here:
                    out.append(_sighting(k, PANORAMA, max(0.4, conf - 0.2), "the vision model's own rating, lowered: seen from nearby",
                                         place, row.get("note") or "", anchor="from"))
        (looked if seen_here or survey_path.exists() else not_looked).append(sc["name"])
    if not looked and not not_looked:
        status = {"status": "not checked", "detail": "no shared-space scan to look at"}
    else:
        status = {"status": "checked" if not not_looked else ("partly checked" if looked else "not checked"),
                  "shared_scans_looked_at": looked, "shared_scans_not_looked_at": not_looked,
                  "detail": "shared-space scans only; apartment-unit scans are not amenities"}
        if stopped:
            status["stopped"] = stopped
        if no_image:
            status["no_panorama_image_available"] = sorted(no_image)
        if client is None and not_looked:
            status["detail"] += "; no vision client was given, so only cached looks were used"
    return out, status


# --- merging ----------------------------------------------------------------------

def borrow_positions(sightings: list[dict]) -> None:
    """Give a scan with no GPS fix an approximate point when it can see an amenity that another scan places.

    The borrowed point only lets the scan's sightings join a place that already exists (within SEEN_FROM_M);
    it never creates one, so it cannot add to a count.
    """
    placed: dict[str, list[dict]] = {}
    for s in sightings:
        if s["source"] == SCAN_NAME and s["place"].get("lon") is not None:
            placed.setdefault(s["kind"], []).append(s["place"])
    by_scan: dict[str, list[dict]] = {}
    for s in sightings:
        if s["place"]["type"] == "scan" and s["place"].get("lon") is None:
            by_scan.setdefault(s["place"]["scan_id"], []).append(s)
    for group in by_scan.values():
        seen = dict.fromkeys(s["kind"] for s in group if s["anchor"] == "from")
        lender = next((placed[k][0] for k in seen if len(placed.get(k, [])) == 1), None)
        if not lender:
            continue
        for s in group:
            s["place"].update(lon=lender["lon"], lat=lender["lat"], cell=lender["cell"],
                              position_basis=(f"borrowed: this scan has no GPS fix; it sees '{lender['scan_name']}' nearby, "
                                              "so that scan's point stands in for its own"))
            s["place"].pop("note", None)
            if s["anchor"] == "at":
                s["anchor"] = "near"


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * geo.M_PER_DEG_LAT * math.cos(lat), (a[1] - b[1]) * geo.M_PER_DEG_LAT)


def _point(s: dict) -> tuple[float, float] | None:
    p = s["place"]
    return (p["lon"], p["lat"]) if p.get("lon") is not None and p["type"] != "parcel" else None


def _same_box(a: dict, b: dict) -> bool:
    """Two boxed places are one when they overlap by 30% of the smaller. Two Vexcel footprints are never one."""
    if a.get("footprint") and b.get("footprint"):
        return False
    A = Polygon(a["footprint"]) if a.get("footprint") else box(*a["bbox"])
    B = Polygon(b["footprint"]) if b.get("footprint") else box(*b["bbox"])
    inter = A.intersection(B).area
    return inter > 0 and inter / min(A.area, B.area) >= 0.3


def merge(sightings: list[dict]) -> list[dict]:
    """Group sightings into amenities, one entry per kind, counted once per place (rules in the module docstring)."""
    by_kind: dict[str, list[dict]] = {}
    for s in sightings:
        by_kind.setdefault(s["kind"], []).append(s)
    amenities = []
    for kind, group in by_kind.items():
        places: list[dict] = []   # {"point": (lon, lat), "bbox": [...] | None, "sightings": [...]}
        unplaced: list[dict] = []

        def nearest(pt, limit):
            best = min(places, key=lambda pl: _metres(pt, pl["point"]), default=None)
            return best if best and _metres(pt, best["point"]) <= limit else None

        boxes = [s for s in group if s["place"].get("bbox")]
        for s in sorted(boxes, key=lambda s: (not s["place"].get("footprint"), -s["confidence"])):
            hit = next((pl for pl in places if any(_same_box(o["place"], s["place"]) for o in pl["sightings"])), None)
            if hit:
                hit["sightings"].append(s)
            else:
                places.append({"point": _point(s), "bbox": s["place"]["bbox"], "sightings": [s]})
        rest = [s for s in group if not s["place"].get("bbox")]
        for s in [x for x in rest if x["anchor"] == "at"]:
            pt = _point(s)
            if pt is None:
                unplaced.append(s)
                continue
            hit = nearest(pt, SAME_PLACE_M)
            if hit:
                hit["sightings"].append(s)
            else:
                places.append({"point": pt, "bbox": None, "sightings": [s]})
        for s in [x for x in rest if x["anchor"] != "at"]:
            pt = _point(s)
            hit = nearest(pt, SEEN_FROM_M) if pt else None
            (hit["sightings"] if hit else unplaced).append(s)

        if not places and unplaced:  # nothing placed it: everything unplaced is one amenity, at least
            first = next((s for s in unplaced if s["anchor"] in ("at", "near")), unplaced[0])
            places.append({"point": None, "bbox": None, "sightings": unplaced, "place": first["place"]})
            unplaced = []
        elif len(places) == 1 and unplaced:  # only one candidate, so the unplaced sightings are of it
            places[0]["sightings"] += unplaced
            unplaced = []

        instances = []
        for n, pl in enumerate(places, 1):
            ss = pl["sightings"]
            best = max(ss, key=lambda s: (bool(s["place"].get("bbox")), s["anchor"] == "at", s["confidence"]))
            place = pl.get("place") or best["place"]
            if any(s["place"].get("bbox") for s in ss):
                how = "boxed on the aerial photo"
            elif place.get("position_basis"):
                how = "approximate: " + place["position_basis"]
            elif all(s["anchor"] == "from" for s in ss):
                how = "seen from this scan position; the amenity itself has no point of its own"
            elif place.get("lon") is not None and place["type"] == "scan":
                how = "the scan's own GPS fix"
            elif place["type"] == "scan":
                how = "by scan only; the scan has no GPS fix"
            else:
                how = "parcel-wide; no point"
            instances.append({
                "n": n, "place": place, "how_placed": how,
                "confidence": max(s["confidence"] for s in ss),
                "sources": sorted({s["source"] for s in ss}),
                "sightings": ss,
                "before_a_storm": _storm(ss),
            })
        scans_at = {s["place"].get("scan_id") for inst in instances for s in inst["sightings"]
                    if s["anchor"] == "at" and s["place"]["type"] == "scan" and s["place"].get("lon") is None}
        # A source that covers the whole parcel and boxes each one gives a full count. Without one the count
        # is a floor: scans cover a few rooms, and a parcel-wide attribute cannot say how many there are.
        boxed = any(s["place"].get("bbox") for i in instances for s in i["sightings"])
        minimum = not boxed and (bool(unplaced) or len(scans_at) > 1
                                 or any(i["place"]["type"] == "parcel" for i in instances))
        amenities.append({
            "kind": kind, "count": len(instances), "count_is_minimum": minimum,
            "count_basis": ("seen, but no source gives it a point on the site, so it is counted once"
                            if not any(s["anchor"] == "at" and _point(s) for i in instances for s in i["sightings"])
                            else f"{len(instances)} separate place(s) on the site"),
            "confidence": max(i["confidence"] for i in instances),
            "confirmed": (max(i["confidence"] for i in instances) >= CONFIRMED_AT
                          or len({s["source"] for i in instances for s in i["sightings"]}) > 1),
            "sources": sorted({s["source"] for i in instances for s in i["sightings"]} | {s["source"] for s in unplaced}),
            "instances": instances,
            "unplaced_sightings": unplaced,
            "unplaced_note": "these confirm the kind but not which place, and add nothing to the count" if unplaced else None,
        })
    order = list(KINDS) + [IN_UNIT_LAUNDRY]
    return sorted(amenities, key=lambda a: order.index(a["kind"]) if a["kind"] in order else len(order))


def _storm(sightings: list[dict]) -> dict | None:
    """What was actually seen at this place that matters before a storm. None when nothing was seen up close."""
    seen = [s for s in sightings if s.get("storm")]
    if not seen:
        return None
    loose, equipment = [], []
    for s in seen:
        loose += s["storm"].get("loose_items") or []
        equipment += s["storm"].get("equipment") or []
    glass = max((s["storm"].get("glass") for s in seen if s["storm"].get("glass") in _GLASS_ORDER),
                key=_GLASS_ORDER.index, default=None)
    doors = sorted({s["storm"]["exterior_doors"] for s in seen
                    if s["storm"].get("exterior_doors") not in (None, "none seen")})
    return {"glass": glass, "exterior_doors": doors, "loose_items": list(dict.fromkeys(loose))[:10],
            "equipment": list(dict.fromkeys(equipment))[:10],
            "seen_by": sorted({f"{s['source']}: {s['place'].get('scan_name') or s['place'].get('cell')}" for s in seen}),
            "positions": len({s["place"].get("sweep_id") for s in seen if s["place"].get("sweep_id")})}


def attach_loose_items(amenities: list[dict], loose: list[dict]) -> None:
    """Loose furniture the aerial detector boxed within LOOSE_ITEM_M of a pool is recorded with that pool."""
    for a in amenities:
        if a["kind"] != "pool":
            continue
        for inst in a["instances"]:
            p = inst["place"]
            if p["type"] != "site point":
                continue
            near = [x for x in loose if _metres((p["lon"], p["lat"]), (x["lon"], x["lat"])) <= LOOSE_ITEM_M]
            if not near:
                continue
            counts: dict[str, int] = {}
            for x in near:
                counts[x["label"]] = counts.get(x["label"], 0) + 1
            storm = inst["before_a_storm"] or {"glass": None, "exterior_doors": [], "loose_items": [], "equipment": [],
                                               "seen_by": [], "positions": 0}
            storm["aerial_loose_items"] = {**counts, "within_m": LOOSE_ITEM_M,
                                           "best_score": max(x["confidence"] for x in near)}
            storm["seen_by"] = sorted(set(storm["seen_by"]) | {f"{AERIAL_DETECTOR}: {p['cell']}"})
            inst["before_a_storm"] = storm


# --- comparison with the listing ----------------------------------------------------

def compare(listed: list[dict], amenities: list[dict], source_status: dict[str, dict], whole_site: bool | None = True) -> dict:
    """Listed and found, listed but not found (checked, not visible, or not checked), found but not listed.

    `whole_site` False means the aerial sources covered only part of the community; "not seen" is then weaker.
    """
    found = {a["kind"]: a for a in amenities if a["kind"] in KINDS}
    both, missing, extra, unsure = [], [], [], []
    for item in listed:
        kind = item["kind"]
        a = found.get(kind)
        if a:
            scan_only = set(a["sources"]) <= set(SCAN_BASED)
            both.append({
                "kind": kind, "listed_count": item["count"], "found_count": a["count"],
                "found_count_is_minimum": a["count_is_minimum"],
                "counts_agree": None if item["count"] is None else (item["count"] == a["count"]),
                "found_sources": a["sources"], "listing_evidence": item["evidence"],
                "independent": not (item.get("tour_caption_only") and scan_only),
            })
            continue
        able = KINDS[kind]["sources"]
        ran = [s for s in able if source_status.get(s, {}).get("status") in ("checked", "partly checked")]
        not_run = [s for s in able if s not in ran]
        whole_ran = [s for s in ran if s in WHOLE_SITE]
        whole_not_run = [s for s in not_run if s in WHOLE_SITE]
        if not able:
            status, why = "not checked", "none of our sources looks for this kind"
        elif whole_ran and not whole_not_run:
            status = "checked, not seen"
            why = f"{' and '.join(whole_ran)} {'covers' if len(whole_ran) == 1 else 'cover'} the whole parcel and did not show one"
        elif whole_ran:
            status = "checked, not seen"
            why = f"{' and '.join(whole_ran)} did not show one; {' and '.join(whole_not_run)} was not run"
        elif whole_not_run:
            status, why = "not checked", f"{' and '.join(whole_not_run)} can see this kind but was not run"
        elif ran:
            status = "not visible to our sources"
            why = ("only scans can show this indoor space; the scans cover a few rooms and none of them is one, "
                   "so its absence from them says nothing")
        else:
            status, why = "not checked", "the scan sources were not run"
        partly = [x for x in ran if source_status.get(x, {}).get("status") == "partly checked"]
        if partly:
            why += f"; {' and '.join(partly)} ran only in part"
        if status == "checked, not seen" and whole_site is False:
            status = "checked on part of the site, not seen"
            why += "; the parcel we looked at holds only part of the community"
        missing.append({"kind": kind, "listed_count": item["count"], "status": status, "why": why,
                        "sources_checked": ran, "sources_not_checked": not_run, "listing_evidence": item["evidence"]})
    listed_kinds = {i["kind"] for i in listed}
    for kind, a in found.items():
        if kind not in listed_kinds:
            (extra if a.get("confirmed", True) else unsure).append(
                {"kind": kind, "found_count": a["count"], "found_count_is_minimum": a["count_is_minimum"],
                 "found_sources": a["sources"], "confidence": a["confidence"]})
    tally: dict[str, int] = {}
    for m in missing:
        tally[m["status"]] = tally.get(m["status"], 0) + 1
    return {
        "listed_and_found": both, "listed_not_found": missing, "found_not_listed": extra,
        "found_not_listed_unconfirmed": unsure,
        "unconfirmed_note": f"one source only, below {CONFIRMED_AT} confidence: kept apart, not counted as found" if unsure else None,
        "counts": {"listed": len(listed), "found": len(found) - len(unsure), "listed_and_found": len(both),
                   "listed_not_found": len(missing), "listed_not_found_by_status": tally, "found_not_listed": len(extra),
                   "found_not_listed_unconfirmed": len(unsure)},
    }


# --- the inventory ------------------------------------------------------------------

def site_coverage(site: Site, attributes: dict | None) -> dict:
    """How much of the community the parcel we looked at holds, against CoStar's own building count."""
    listed = site.d["record"].get("num_buildings")
    if attributes is None:
        return {"costar_buildings": listed, "buildings_on_parcel": None, "whole_site": None,
                "note": "no parcel record, so coverage is unknown"}
    on_parcel = 0
    for st in attributes.get("structures") or []:
        dims = _footprint_dims(st)
        if dims and not _is_carport(st, dims):
            on_parcel += 1
    whole = None if not listed or not on_parcel else on_parcel >= 0.8 * listed
    note = (f"the parcel at the listing's address holds {on_parcel} structures other than carport rows; "
            f"CoStar counts {listed} buildings"
            + ("" if whole or whole is None else
               ", so the aerial sources saw only part of the community and cannot rule anything out for the rest"))
    return {"costar_buildings": listed, "buildings_on_parcel": on_parcel, "whole_site": whole, "note": note}


def _parcel_attributes(site: Site) -> dict | None:
    from .. import vexcel
    r = site.d["record"]
    path = vexcel.VX_CACHE / "parcel" / f"{r['lat']:.6f}_{r['lon']:.6f}.json"
    data = json.loads(path.read_text()) if path.exists() else None
    return (data or {}).get("attributes")


def _default_detector(area_wkt: str, labels: list[str]) -> list[dict]:
    from .. import vexcel
    return vexcel.detect(area_wkt, labels)


_AUTO: Any = object()


def inventory(property_id: int, client=None, *, detector: Callable | None = _AUTO, budget: Budget | None = None,
              cache_dir: Path | None = None, site: Site | None = None, listing_facts: dict | None = None,
              attributes: dict | None = _AUTO) -> dict:
    """Every amenity our sources can see at a property, counted once per place, checked against CoStar's listing.

    `client` is an Anthropic client; without one no new vision call is made and only cached looks are used.
    The keyword arguments are for tests and offline runs: `detector=None` makes no detector call.
    """
    cache_dir = cache_dir or CACHE
    budget = budget or Budget(cache_dir / "ledger.json")
    site = site or load_site(property_id)
    before = dict(budget.used)

    attrs = _parcel_attributes(site) if attributes is _AUTO else attributes
    a_sight, a_status = attribute_sightings(site, attrs)
    d_sight, loose, d_status = detector_sightings(site, _default_detector if detector is _AUTO else detector, budget, cache_dir, attrs)
    s_sight, name_status, room_status = scan_sightings(site)
    p_sight, p_status = panorama_sightings(site, client, budget, cache_dir)
    status = {AERIAL_ATTRIBUTE: a_status, AERIAL_DETECTOR: d_status, SCAN_NAME: name_status,
              ROOM_LABEL: room_status, PANORAMA: p_status}

    sightings = d_sight + s_sight + p_sight + a_sight
    borrow_positions(sightings)
    amenities = merge(sightings)
    attach_loose_items(amenities, loose)
    facts = listing_facts if listing_facts is not None else listing(property_id, cache_dir)
    coverage = site_coverage(site, attrs)
    comparison = compare(facts["listed"], amenities, status, coverage["whole_site"])
    record = site.d["record"]
    return {
        "property_id": property_id, "name": record.get("name"), "city": record.get("city"), "units": record.get("units"),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": status,
        "site_coverage": coverage,
        "merging_rule": ("Counted once per place, never once per source: overlapping detector boxes are one place; a scan "
                         f"standing in an amenity joins a place of that kind within {SAME_PLACE_M:.0f} m; a view of it from nearby "
                         f"joins the nearest within {SEEN_FROM_M:.0f} m; a sighting with no site point confirms the kind but adds nothing."),
        "amenities": amenities,
        "loose_items_seen_from_the_air": loose,
        "costar": facts,
        "comparison": comparison,
        "calls": {"this_run": {k: budget.used[k] - before[k] for k in budget.used}, **budget.summary()},
    }


def one_line(result: dict) -> str:
    parts = []
    for a in result["amenities"]:
        n = f"{a['count']}+" if a["count_is_minimum"] and a["count"] == 1 and len(a["sources"]) == 1 and a["sources"][0] == AERIAL_ATTRIBUTE else str(a["count"])
        parts.append(f"{n} {a['kind']} ({', '.join(a['sources'])})")
    return "; ".join(parts) or "nothing found"


def save(result: dict, cache_dir: Path | None = None) -> Path:
    path = (cache_dir or CACHE) / f"{result['property_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1))
    return path
