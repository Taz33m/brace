"""Dated, permission-neutral sponsor evidence for recovery analysis.

Nothing here asserts damage, makes household bindings, or exposes image files.
The service layer authorizes and resolves the private ``assets`` descriptors.
Default operation reads the sponsor kit and existing local caches only.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Point, box

from backend import building, geo, matterport, portfolio, vexcel
from backend.config import CACHE_DIR, KIT_DIR
from .spatial import location_ref, scan_locations
from .temporal import MODES, date_bounds, normalize_date, relative_to_incident, select_capture_pair, source_eligibility


def _read_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text())


def _id(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:24]


def _enum(enums: dict, name: str, value) -> str:
    if isinstance(value, str) and not value.isdigit():
        return value
    return enums.get(name, {}).get(str(value), "Unknown")


def normalize_sales(rows: list[dict], properties: dict[str, dict], enums: dict) -> list[dict]:
    """Keep allocated shares distinct; never assign a portfolio total to a building.

    Sales carry transaction-level provenance in ``source_ids`` and the source
    transaction date/status. They are financial evidence rows, rather than one
    additional image ``Evidence`` object for each of the thousands of sales.
    """
    out = []
    seen = set()
    for raw in rows:
        entities = raw.get("entities") or []
        portfolio_sale = len(entities) != 1 or (raw.get("numberOfEntities") or 1) > 1 or bool(raw.get("portfolioType"))
        for entity in entities:
            pid = entity.get("propertyId")
            if pid is None:
                continue
            key = (str(raw.get("id")), str(pid))
            if key in seen:
                continue
            seen.add(key)
            prop = properties.get(str(pid)) or {}
            currency = _enum(enums, "MonetaryUnit", raw.get("monetaryUnit"))
            currency = "USD" if currency == "UnitedStatesDollar" else currency
            price = entity.get("allocatedPrice") if portfolio_sale else raw.get("soldForPrice")
            price_status = _enum(enums, "SalePriceStatus", entity.get("allocatedPriceStatus") if portfolio_sale else raw.get("salePriceStatus"))
            conditions = [_enum(enums, "SaleCondition", c) for c in raw.get("saleConditions") or []]
            conditions += [_enum(enums, "BelowMarketSaleReason", c) for c in raw.get("belowMarketSaleReasons") or []]
            if raw.get("isLandValueSale"):
                conditions.append("LandValueSale")
            out.append({
                "comp_id": f"costar-sale:{raw.get('id')}:{pid}",
                "property_ref": {"dataset": "commercial_property", "id": str(pid)},
                "label": prop.get("name") or entity.get("buildingFullName") or f"Property {pid}",
                "transaction_date": normalize_date(raw.get("soldDate")), "available_at": None,
                "date_basis": "closed" if raw.get("soldDate") else "unknown",
                "price_usd": price if currency == "USD" else None,
                "price_status": price_status, "allocated": portfolio_sale, "currency": currency,
                "asset_type": prop.get("type"), "city": prop.get("city"), "state": prop.get("state"),
                "latitude": prop.get("lat"), "longitude": prop.get("lon"),
                # Sale-time quantities take precedence over a later property record.
                "units": entity.get("numberOfUnits") or prop.get("units"),
                "gba_sqft": entity.get("totalSquarefeet") or prop.get("gba_sqft"),
                "sale_conditions": conditions,
                "source_ids": [f"costar:commercial-sale-comp:{raw.get('id')}"],
            })
    return out


def _evidence(source_id: str, kind: str, label: str, received_at: str, *,
              captured_at=None, effective_at=None, available_at=None, model_created_at=None,
              location=None, media=None, summary="", limitations=None) -> dict:
    return {"evidence_id": f"ev:{_id(source_id)}", "kind": kind, "source_id": source_id,
            "source_label": label, "captured_at": normalize_date(captured_at),
            "effective_at": normalize_date(effective_at), "available_at": normalize_date(available_at),
            "received_at": received_at, "model_created_at": normalize_date(model_created_at),
            "location": location, "media": media, "summary": summary,
            "limitations": limitations or []}


def _capture_catalog(area_wkt: str, allow_network: bool) -> tuple[list[dict], list[dict], list[str]]:
    """Keep routine and disaster catalogs separate in cache, then join source IDs."""
    rows, catalogs, limitations, seen = [], [], [], set()
    for layers in (vexcel.VEXCEL_LAYERS, "graysky,graysky-g"):
        try:
            found = vexcel.captures(area_wkt, max_gsd=None, thin=False, layers=layers,
                                    cached_only=not allow_network)
            if allow_network and any("first_date" not in row or "last_date" not in row for row in found):
                found = vexcel.captures(area_wkt, max_gsd=None, thin=False, layers=layers, refresh=True)
            catalogs.append({"layers": layers, "status": "available" if found else "unavailable", "count": len(found)})
        except (vexcel.VexcelError, OSError, ValueError):
            catalogs.append({"layers": layers, "status": "unavailable", "count": 0})
            limitations.append(f"Vexcel capture inventory is unavailable for layers {layers}.")
            continue
        for source in found:
            if not source.get("collection") or source["collection"] in seen:
                continue
            seen.add(source["collection"])
            row = copy.deepcopy(source)
            # Legacy caches retain a last day, but do not establish a whole
            # post-incident window. Never infer their missing first capture.
            row["first_date"] = normalize_date(row.get("first_date"))
            row["last_date"] = normalize_date(row.get("last_date") or row.get("date"))
            row["date"] = row["last_date"]
            row["available_at"] = normalize_date(row.get("last_publish"))
            row["query_layers"] = layers
            rows.append(row)
    return rows, catalogs, limitations


def _resolve_pair_capture(descriptor: dict, allow_network: bool) -> tuple[Path | None, str | None]:
    from .service import EvidenceImages

    cached = EvidenceImages({}, [], allow_network=False, cache_root=CACHE_DIR)
    last_reason = "Selected capture image is not cached."
    # Existing discovery images used both request sizes. Every candidate goes
    # through the same provenance/coverage checks before a path can be reused.
    layer_options = list(dict.fromkeys(filter(None, [descriptor.get("layers"), descriptor.get("catalog_layers")])))
    for layers in layer_options:
        for buffer_m in (8, 0):
            try:
                return cached._resolve({**descriptor, "layers": layers, "buffer_m": buffer_m}), None
            except ValueError as exc:
                last_reason = str(exc)
            except (OSError, vexcel.VexcelError):
                last_reason = "Selected capture image or its metadata is unavailable."
    if allow_network:
        try:
            return EvidenceImages({}, [], allow_network=True, cache_root=CACHE_DIR)._resolve(descriptor), None
        except ValueError as exc:
            last_reason = str(exc)
        except (OSError, vexcel.VexcelError):
            last_reason = "Selected Vexcel capture could not be fetched."
    return None, last_reason


def load_inventory(property_id: int, *, incident_at: str, assessment_as_of: str,
                   mode: str = "scenario_exercise", allow_network: bool = False) -> dict:
    if isinstance(property_id, bool) or not isinstance(property_id, int) or property_id <= 0:
        raise ValueError("A positive commercial property ID is required")
    if mode not in MODES:
        raise ValueError("Unknown recovery case mode")
    date_bounds(incident_at)
    date_bounds(assessment_as_of)
    if date_bounds(incident_at)[0] > date_bounds(assessment_as_of)[1]:
        raise ValueError("Recovery assessment cannot predate the incident")
    properties = {str(p["id"]): p for p in portfolio.buildings()}
    if str(property_id) not in properties:
        raise KeyError(f"Unknown commercial property {property_id}")
    subject = copy.deepcopy(properties[str(property_id)])
    subject["property_ref"] = {"dataset": "commercial_property", "id": str(property_id)}
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    evidence, locations, assets, limitations = [], [], {}, []
    image_hashes: dict[Path, str] = {}
    status = {"costar": {"status": "available", "excluded": 0},
              "vexcel": {"status": "unavailable", "excluded": 0},
              "matterport": {"status": "unavailable", "excluded": 0}}

    def local_image(path: Path) -> dict | None:
        """Freeze image bytes' identity and keep every permitted file in the cache."""
        resolved = path.resolve()
        if not resolved.is_relative_to(CACHE_DIR.resolve()):
            limitations.append("A cached image resolves outside the approved cache and cannot be used.")
            return None
        if not resolved.is_file():
            return None
        if resolved not in image_hashes:
            with resolved.open("rb") as stream:
                image_hashes[resolved] = hashlib.file_digest(stream, "sha256").hexdigest()
        return {"kind": "local_image", "path": str(resolved), "sha256": image_hashes[resolved]}

    def add(row: dict, layer: str, asset: dict | None = None):
        valid, reason = source_eligibility(row.get("captured_at") or row.get("effective_at"),
                                          row.get("available_at"), assessment_as_of, mode)
        # Creation is not capture time, nor a claimed publication timestamp.
        # It is nevertheless a lower bound: this model cannot have been
        # available before it existed, even when its capture date is unknown.
        created = row.get("model_created_at")
        if valid and created and date_bounds(created)[1] > date_bounds(assessment_as_of)[1]:
            valid, reason = False, "Model was created after the assessment cutoff"
        if not valid:
            status[layer]["excluded"] += 1
            limitations.append(f"{row['source_label']}: {reason}")
            return False
        if any(e["evidence_id"] == row["evidence_id"] for e in evidence):
            return True
        evidence.append(row)
        if asset:
            assets[row["evidence_id"]] = asset
        status[layer]["status"] = "available"
        return True

    property_row = _evidence(f"costar:commercial-property:{property_id}", "costar_record", "CoStar property record", now,
                             summary=f"{subject.get('name')}; {subject.get('type')}; units {subject.get('units') or 'unknown'}.",
                             limitations=["Property record effective/publication dates are not supplied by the kit.",
                                          "Last recorded sale is a historical transaction, not current value."])
    if not add(property_row, "costar"):
        # Identity can select a case; undated current dimensions cannot price a replay.
        subject.update(units=None, gba_sqft=None, last_sale=None, historical_record_unavailable=True)
        status["costar"]["status"] = "unavailable_at_cutoff"

    enums = _read_json(KIT_DIR / "schemas" / "enums.json", {})
    sales_path = KIT_DIR / "data" / "commercial-sale-comp.jsonl"
    if sales_path.exists():
        with sales_path.open() as stream:
            sales = normalize_sales([json.loads(line) for line in stream if line.strip()], properties, enums)
    else:
        sales = []
        limitations.append("Commercial sale-comp dataset is unavailable.")
    # Keep rejected rows for audit; the valuation engine applies its own date filter.
    for sale in sales:
        valid, reason = source_eligibility(sale["transaction_date"], sale["available_at"], assessment_as_of, mode)
        sale["temporal_eligible"], sale["temporal_exclusion_reason"] = valid, reason
    subject["source_ids"] = [property_row["source_id"]] if mode != "historical_replay" else []

    out_dir = building.building_dir(property_id)
    cached = _read_json(out_dir / "building.json")
    if cached:
        bundle = building.upgrade_cached_bundle(copy.deepcopy(cached))
    elif allow_network:
        try:
            bundle = building.build(property_id)
        except (building.BuildingError, vexcel.VexcelError, matterport.MatterportError):
            bundle = None
            limitations.append("Building imagery bundle could not be fetched.")
    else:
        bundle = None
    structures = copy.deepcopy((bundle or {}).get("structures") or [])
    roof_date = normalize_date(((bundle or {}).get("site") or {}).get("roof_analysis_date"))
    structure_source_id = f"vexcel:property-attributes:{property_id}:{roof_date or 'undated'}"
    for structure in structures:
        structure.update(source_id=structure_source_id, roof_analysis_date=roof_date,
                         limitations=["Roof attributes describe the dated aerial analysis, not verified disaster damage."])
    if structures:
        attribute_row = _evidence(structure_source_id, "vexcel_image", "Vexcel image-derived structure attributes", now,
                                  effective_at=roof_date, summary="Roof condition, objects and footprints from Vexcel property analysis.",
                                  limitations=["Attribute analysis date is separate from the displayed aerial capture.",
                                               "Pre-existing roof attributes are not evidence of damage caused by this incident."])
        if not add(attribute_row, "vexcel"):
            structures = []
    if mode == "historical_replay":
        # The bundle has no geometry publication dates. Do not leak present-day
        # structures into a replay just because a source has been audited out.
        structures = []
    for structure in structures:
        center = structure.get("centroid") or [None, None]
        locations.append(location_ref(f"structure:{structure['id']}", f"Structure {structure['id']}",
                                      structure_id=structure["id"], binding="unverified",
                                      longitude=center[0], latitude=center[1]))
    captures, pair = [], select_capture_pair([], incident_at, assessment_as_of, mode)
    if bundle:
        aerial = bundle.get("aerial") or {}
        captured = normalize_date(aerial.get("captured"))
        collection = aerial.get("collection")
        source_id = f"vexcel:{collection or 'cached-site'}:{property_id}:{captured or 'undated'}"
        aerial_path = out_dir / "aerial.jpg"
        row = _evidence(source_id, "vexcel_image", "Vexcel aerial site image", now, captured_at=captured,
                        summary=f"Site imagery; {relative_to_incident(captured, incident_at)} the incident.",
                        limitations=["Aerial pixels do not establish indoor damage, causation or unit occupancy.",
                                     "Source publication date is unknown."])
        add(row, "vexcel", local_image(aerial_path) if aerial_path.exists() else None)
    bounds = ((bundle or {}).get("aerial") or {}).get("bounds")
    point = {"longitude": subject.get("lon"), "latitude": subject.get("lat")}
    valid_point = all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                      for value in point.values()) and abs(point["longitude"]) <= 180 and abs(point["latitude"]) <= 90
    valid_bounds = isinstance(bounds, (list, tuple)) and len(bounds) == 4 and all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in bounds
    ) and -180 <= bounds[0] < bounds[2] <= 180 and -90 <= bounds[1] < bounds[3] <= 90
    area_wkt = box(*bounds).wkt if valid_bounds else Point(point["longitude"], point["latitude"]).wkt if valid_point else None
    if area_wkt:
        captures, catalogs, catalog_limits = _capture_catalog(area_wkt, allow_network)
        status["vexcel"]["catalogs"] = catalogs
        limitations.extend(catalog_limits)
        pair = select_capture_pair(captures, incident_at, assessment_as_of, mode)
        # Freeze only the chosen pair, never fetch the complete catalog of images.
        for role in ("before", "after"):
            candidate = pair[role]
            if not candidate:
                continue
            capture = copy.deepcopy(candidate)
            capture.update(catalog_first_date=candidate.get("first_date"), catalog_last_date=candidate.get("last_date"),
                           image_available=False, unavailable_reason=None)
            pair[role] = capture
            descriptor = {"kind": "vexcel_capture", "area_wkt": area_wkt,
                          "collection": capture["collection"], "layers": capture.get("layer") or capture["query_layers"],
                          "catalog_layers": capture["query_layers"],
                          "expected_first_date": capture.get("first_date"), "expected_date": capture["last_date"],
                          "incident_at": incident_at, "role": role, "assessment_as_of": assessment_as_of,
                          "property_point": point, "buffer_m": 8}
            asset, image = None, None
            if valid_point:
                image, capture["unavailable_reason"] = _resolve_pair_capture(descriptor, allow_network)
            else:
                capture["unavailable_reason"] = "Property coordinates are unavailable; image coverage cannot be verified."
            if image is not None:
                try:
                    asset = local_image(image)
                    if asset is None:
                        raise ValueError("Selected image is outside the approved cache or is unavailable.")
                    raw = image.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
                        raise ValueError("Selected image changed while its evidence identity was frozen.")
                    metadata = vexcel._image_info(raw)
                    first = normalize_date(metadata.get("first_capture"))
                    last = normalize_date(metadata.get("last_capture"))
                    if not first or not last:
                        raise ValueError("Selected image has no complete capture window.")
                    from .service import EvidenceImages

                    # Recheck the metadata embedded in the frozen bytes as well
                    # as the sidecar used by the resolver; no stale JSON claims.
                    EvidenceImages._validate_capture_context(descriptor, metadata)
                    if metadata.get("collection") != descriptor["collection"] or metadata.get("layer") not in descriptor["layers"].split(","):
                        raise ValueError("Selected image identity does not match its catalog source.")
                    expected_start = descriptor.get("expected_first_date") or descriptor["expected_date"]
                    actual_start = first if descriptor.get("expected_first_date") else last
                    if date_bounds(actual_start)[0] < date_bounds(expected_start)[0] or date_bounds(last)[1] > date_bounds(descriptor["expected_date"])[1]:
                        raise ValueError("Selected image dates are outside its catalog window.")
                    capture.update(first_date=first[:10], last_date=last[:10], date=last[:10],
                                   first_capture=first, last_capture=last, first_publish=normalize_date(metadata.get("first_publish")),
                                   last_publish=normalize_date(metadata.get("last_publish")),
                                   available_at=normalize_date(metadata.get("last_publish")),
                                   layer=metadata.get("layer"), graysky_event=metadata.get("graysky_event"),
                                   min_gsd=metadata.get("min_gsd"), max_gsd=metadata.get("max_gsd"),
                                   image_available=True, unavailable_reason=None)
                except (ValueError, OSError):
                    asset = None
                    capture.update(image_available=False, unavailable_reason="Selected image metadata or frozen bytes could not be verified.")
            first_label = capture.get("first_capture") or capture.get("first_date") or "unknown start"
            last_label = capture.get("last_capture") or capture.get("last_date") or "unknown end"
            row_limits = [pair["limitation"], "Aerial imagery does not establish indoor damage, causation or unit occupancy."]
            if not capture.get("available_at"):
                row_limits.append("Source publication date is unknown.")
            if capture["image_available"]:
                row_limits.append(f"Catalog window {capture['catalog_first_date'] or 'unknown start'} to {capture['catalog_last_date']}; displayed image dates come from its own XMP metadata.")
            else:
                row_limits.append(capture["unavailable_reason"] or "Image unavailable; this is catalog metadata only.")
            row = _evidence(f"vexcel:collection:{capture['collection']}:{property_id}", "vexcel_image",
                            f"Vexcel {role}-incident capture", now,
                            captured_at=capture.get("last_capture") or capture.get("last_date"),
                            available_at=capture.get("available_at"),
                            summary=f"{'Validated image' if capture['image_available'] else 'Catalog candidate'} {role} the incident; capture window {first_label} to {last_label}. No damage determination.",
                            limitations=row_limits)
            capture["evidence_id"] = row["evidence_id"]
            if not add(row, "vexcel", asset):
                pair[role] = None
            elif capture["unavailable_reason"]:
                limitations.append(f"Vexcel {role}-incident image: {capture['unavailable_reason']}")
    else:
        limitations.append("Vexcel comparison cannot be searched without property coordinates or an aerial extent.")
    status["vexcel"]["comparison_images_available"] = sum(bool(pair[role] and pair[role].get("image_available")) for role in ("before", "after"))
    if not all(pair[role] and pair[role].get("image_available") for role in ("before", "after")):
        limitations.append("No eligible complete before/after Vexcel pair is available; do not infer disaster damage from one image.")

    scans = (bundle or {}).get("scans") or []
    if not scans:
        frame = geo.LocalFrame(subject.get("lat"), subject.get("lon"))
        for model_id in subject.get("model_ids") or []:
            model = _read_json(matterport.MP_CACHE / model_id / "model.json")
            if model is None and allow_network:
                try:
                    model = matterport.fetch_model(model_id)
                except matterport.MatterportError:
                    continue
            if model:
                scan = building._scan(model_id, frame, model)
                if scan:
                    scans.append(scan)
    eligible_scans = []
    for scan in scans:
        scan_locs = scan_locations(scan, structures)
        loc_by_sweep = {loc["sweep_id"]: loc for loc in scan_locs}
        row = _evidence(f"matterport:model:{scan['id']}", "matterport_view", scan.get("name") or scan["id"], now,
                        captured_at=scan.get("captured_at"), model_created_at=scan.get("model_created_at"),
                        location=scan_locs[0], summary=f"{len(scan.get('rooms') or [])} rooms; {len(scan.get('sweeps') or [])} viewpoints.",
                        limitations=["Capture date is unknown unless explicitly supplied; model creation is not capture.",
                                     "A sponsor property link does not identify an occupied unit; GPS structure alignment is unverified."])
        if not add(row, "matterport"):
            continue
        eligible_scans.append(scan)
        locations.extend(scan_locs)
        sweeps = scan.get("sweeps") or []
        # Bound agent context while preserving all spatial data in scans/locations.
        for sweep in sweeps[:6]:
            face = 1
            face_paths = [(f, matterport.MP_CACHE / scan["id"] / "faces" / f"{sweep['id']}_{f}.jpg") for f in (1, 2, 3, 4)]
            cached_face = next(((f, p) for f, p in face_paths if p.is_file()), None)
            if cached_face:
                face, path = cached_face
                asset = local_image(path)
            else:
                asset = {"kind": "matterport_face", "model_id": scan["id"], "sweep_id": sweep["id"], "face": face}
            view = _evidence(f"matterport:{scan['id']}:{sweep['id']}:face:{face}", "matterport_view",
                             f"{scan.get('name') or scan['id']} / viewpoint {sweep['id']} / face {face}", now,
                             captured_at=scan.get("captured_at"), model_created_at=scan.get("model_created_at"),
                             location=loc_by_sweep[sweep["id"]], summary="One panorama face at this scan viewpoint.",
                             limitations=row["limitations"])
            add(view, "matterport", asset)
    if not eligible_scans:
        limitations.append("No local Matterport scan is available for this property; resident reports can still use descriptive locations.")
    if mode == "scenario_exercise":
        limitations.append("Scenario exercise: current building records may be combined with a historical incident; this is not a historical prediction or observed loss.")
    return {"subject": subject, "sales": sales, "evidence": evidence, "locations": locations,
            "assets": assets, "limitations": list(dict.fromkeys(limitations)), "source_status": status,
            "captures": captures, "capture_pairs": pair, "scans": eligible_scans, "structures": structures}
