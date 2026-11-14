"""The building portfolio: CoStar's commercial properties, their owners, managers and tenants.

The kit's property file is large, so a slim index is built once and cached.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from functools import lru_cache
from typing import Any

from .config import CACHE_DIR, KIT_DIR

INDEX = CACHE_DIR / "portfolio.json"
INDEX_VERSION = 3

TYPE_LABEL = {
    "Multifamily": "Apartment community", "Office": "Office", "Industrial": "Industrial", "GeneralRetail": "Retail",
    "Hospitality": "Hotel", "Flex": "Flex", "Specialty": "Specialty", "Healthcare": "Healthcare", "Land": "Land",
}
ROLE_KEY = {"TrueOwner": "owner", "RecordedOwner": "recorded_owner", "PropertyManager": "manager",
            "PrimaryLeasingCompany": "leasing", "AssetManager": "asset_manager", "HotelOperator": "operator"}


@lru_cache(maxsize=1)
def _enums() -> dict:
    return json.loads((KIT_DIR / "schemas" / "enums.json").read_text())


def _enum(name: str, value: Any) -> str | None:
    label = _enums().get(name, {}).get(str(value))
    return None if label in (None, "Unknown") else label


@lru_cache(maxsize=1)
def _companies() -> dict[int, dict]:
    out = {}
    with open(KIT_DIR / "data" / "company-detail.jsonl") as f:
        for line in f:
            r = json.loads(line)
            out[r["id"]] = {"name": r.get("name"), "employees": r.get("numEmployees"), "suite": (r.get("suite") or "").strip() or None}
    return out


def _address(a: dict) -> str:
    parts = [a.get("streetNumber"), a.get("streetDirection"), a.get("streetName"), a.get("streetType"), a.get("streetSuffix")]
    return " ".join(str(p) for p in parts if p)


def _slim(r: dict, models: list[str], companies: dict[int, dict]) -> dict:
    a = r.get("primaryAddress") or {}
    ptype = _enum("PropertyType", r.get("propertyType")) or "Unknown"
    apt = r.get("propertyApartment") or {}
    ind = r.get("propertyIndustrial") or {}
    events = {e.get("eventType"): e.get("year") for e in r.get("constructionEvents") or [] if e.get("year")}
    contacts: dict[str, str] = {}
    for c in r.get("contacts") or []:
        role = ROLE_KEY.get(_enum("ContactRole", c.get("contactRole")) or "")
        name = (companies.get(c.get("locationId")) or {}).get("name")
        if role and name and role not in contacts:
            contacts[role] = name
    parking = r.get("parking") or []
    return {
        "id": r["id"],
        "name": r.get("buildingName") or _address(a),
        "address": _address(a), "city": a.get("city"), "state": a.get("state"), "zip": (a.get("postcode") or "")[:5],
        "lat": a.get("latitude"), "lon": a.get("longitude"),
        "type": ptype, "type_label": TYPE_LABEL.get(ptype, ptype),
        "style": _enum("ApartmentStyleType", apt.get("apartmentStyleType")),
        "year_built": events.get(2), "renovated": events.get(4) or events.get(16),
        "stories": r.get("numStoriesAboveGrade"),
        "gba_sqft": round(r["grossBuildingAreaSquareFeet"]) if r.get("grossBuildingAreaSquareFeet") else None,
        "units": apt.get("totalNumUnits"), "num_buildings": apt.get("numBuildings"), "walkup": apt.get("isWalkup"),
        "construction": _enum("BuildingConstructionMaterialType", r.get("buildingConstructionMaterial")),
        "sprinklers": r.get("hasSprinklers"),
        "building_class": _enum("BuildingClass", r.get("buildingClass")),
        "photo": (r.get("primaryPhoto") or {}).get("attachmentUri"),
        "parking_spaces": sum(p.get("totalSpaces") or 0 for p in parking) or None,
        "covered_parking": any(_enum("ParkingType", p.get("parkingType")) in ("Covered", "CoveredTandem", "AttachedGarage") for p in parking),
        "loading_docks": ind.get("numExternalLoadingDocks"), "drive_in_bays": (ind.get("driveInBays") or {}).get("numDriveInBays"),
        "clear_height_ft": (ind.get("structural") or {}).get("ceilingHeightFeet"),
        "contacts": contacts,
        "model_ids": models,
    }


def last_sales(comps: list[dict]) -> dict[str, dict]:
    """The most recent priced sale of each property: {property id: {price, date, basis, portfolio}}.

    A comp that covers one property carries the sale price. A portfolio comp covers several,
    and only an allocated share is known for each, so that share is used and marked as such.
    `basis` is CoStar's own label for how the price was established; it travels with the price.
    """
    best: dict[str, dict] = {}
    for c in comps:
        entities = c.get("entities") or []
        date = (c.get("soldDate") or "")[:10]
        if not date:
            continue
        for e in entities:
            pid = e.get("propertyId")
            if pid is None:
                continue
            if len(entities) == 1 and c.get("soldForPrice"):
                sale = {"price": c["soldForPrice"], "basis": _enum("SalePriceStatus", c.get("salePriceStatus")) or "Unknown", "portfolio": False}
            elif len(entities) > 1 and e.get("allocatedPrice"):
                sale = {"price": e["allocatedPrice"], "basis": "Allocated", "portfolio": True}
            else:
                continue
            if str(pid) not in best or date > best[str(pid)]["date"]:
                best[str(pid)] = {**sale, "date": date}
    return best


def _build() -> dict:
    models: dict[int, list[str]] = defaultdict(list)
    with open(KIT_DIR / "commercial-properties.csv") as f:
        for row in csv.DictReader(f):
            if row["MatterportModelId"]:
                models[int(row["PropertyId"])].append(row["MatterportModelId"])
    companies = _companies()
    buildings = {}
    with open(KIT_DIR / "data" / "commercial-property.jsonl") as f:
        for line in f:
            r = json.loads(line)
            a = r.get("primaryAddress") or {}
            if a.get("latitude") is None:
                continue
            buildings[str(r["id"])] = _slim(r, models.get(r["id"], []), companies)
    tenants: dict[str, list[dict]] = defaultdict(list)
    with open(KIT_DIR / "data" / "location-occupancy.jsonl") as f:
        for line in f:
            o = json.loads(line)
            if o.get("toDate") or str(o["propertyId"]) not in buildings:
                continue  # only who is there now
            c = companies.get(o.get("tenantLocationId")) or {}
            if not c.get("name"):
                continue
            tenants[str(o["propertyId"])].append({
                "name": c["name"], "employees": c.get("employees"), "suite": c.get("suite"),
                "industry": _enum("IndustryType", o.get("industryType")), "since": (o.get("fromDate") or "")[:4] or None})
    with open(KIT_DIR / "data" / "commercial-sale-comp.jsonl") as f:
        sales = last_sales([json.loads(line) for line in f])
    for pid, b in buildings.items():
        b["tenant_count"] = len(tenants.get(pid, []))
        b["last_sale"] = sales.get(pid)
    return {"version": INDEX_VERSION, "buildings": buildings, "tenants": tenants}


@lru_cache(maxsize=1)
def _index() -> dict:
    if INDEX.exists():
        data = json.loads(INDEX.read_text())
        if data.get("version") == INDEX_VERSION:
            return data
    data = _build()
    INDEX.write_text(json.dumps(data))
    return data


def buildings() -> list[dict]:
    return list(_index()["buildings"].values())


def building(property_id: int) -> dict:
    return _index()["buildings"][str(property_id)]


_RENTS: dict[int, dict] | None = None


def rent(property_id: int) -> dict | None:
    """What a building's homes are advertised at, from its CoStar apartment listing. None when it has no listing.

    These are asking rents and the listing's own count of homes, which can differ from the property record's:
    both are shown with where they came from, and nothing is multiplied into a total.
    """
    global _RENTS
    if _RENTS is None:
        found: dict[int, dict] = {}
        try:
            with open(KIT_DIR / "data" / "apartment-listing.jsonl") as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("propertyId") and r.get("minRent") and r.get("maxRent"):
                        found[int(r["propertyId"])] = {
                            "low": r["minRent"], "high": r["maxRent"], "currency": r.get("monetaryUnit") or "USD",
                            "homes_listed": r.get("totalNumUnits"), "available": r.get("numUnitsAvailable"),
                            "floor_plans": len(r.get("apartmentModels") or []), "source": "CoStar apartment listing"}
        except OSError:
            pass
        _RENTS = found
    return _RENTS.get(int(property_id))


_PLANS: dict[int, list[dict]] | None = None


def floor_plans(property_id: int) -> list[dict]:
    """The kinds of home a community lists, from its Apartments.com listing in the kit: bedrooms, bathrooms, size, how many
    there are and what they are advertised at. Empty when it has no listing. Counts are the listing's, which can differ
    from the property record's."""
    global _PLANS
    if _PLANS is None:
        found: dict[int, list[dict]] = {}
        try:
            with open(KIT_DIR / "data" / "apartment-listing.jsonl") as f:
                for line in f:
                    r = json.loads(line)
                    plans = [{"name": m.get("name"), "beds": m.get("numBeds"), "baths": m.get("numBaths"), "homes": m.get("numUnits"),
                              "sqft_low": m.get("minSquareFeet"), "sqft_high": m.get("maxSquareFeet"), "rent_low": m.get("minRent"), "rent_high": m.get("maxRent")}
                             for m in r.get("apartmentModels") or [] if m.get("numUnits")]
                    if r.get("propertyId") and plans:
                        found[int(r["propertyId"])] = plans
        except OSError:
            pass
        _PLANS = found
    return _PLANS.get(int(property_id), [])


def homes_available_near(property_id: int, within_km: float = 3.0, limit: int = 4) -> list[dict]:
    """Where a household could go if its home cannot be lived in: apartment communities with homes listed as
    available, this one first and then the nearest, each with its asking rents.

    From the CoStar apartment listings as they stand in the kit. Availability is what the listing says, not a
    reservation, and the rents are asking rents. Empty when the building has no position or nothing is near.
    """
    import math
    try:
        here = building(property_id)
    except KeyError:
        return []
    lat, lon = here.get("lat"), here.get("lon")
    if lat is None or lon is None:
        return []
    found = []
    try:
        with open(KIT_DIR / "data" / "apartment-listing.jsonl") as f:
            for line in f:
                r = json.loads(line)
                a = r.get("address") or {}
                if not r.get("numUnitsAvailable") or not r.get("minRent") or a.get("latitude") is None or a.get("longitude") is None:
                    continue
                km = math.hypot((a["latitude"] - lat) * 111.2, (a["longitude"] - lon) * 111.2 * math.cos(math.radians(lat)))
                same = r.get("propertyId") == property_id
                if same or km <= within_km:
                    found.append({"property_id": r.get("propertyId"), "name": r.get("buildingName") or _address(a), "same_community": same, "km": round(km, 1),
                                  "available": r["numUnitsAvailable"], "low": r["minRent"], "high": r.get("maxRent") or r["minRent"],
                                  "source": "CoStar apartment listing"})
    except OSError:
        return []
    return sorted(found, key=lambda h: (not h["same_community"], h["km"]))[:limit]


def tenants(property_id: int) -> list[dict]:
    """Companies recorded as occupying the building now, largest first."""
    rows = _index()["tenants"].get(str(property_id), [])
    return sorted(rows, key=lambda t: -(t.get("employees") or 0))
