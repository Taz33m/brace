from __future__ import annotations

import copy
import hashlib
import json
from datetime import timezone
from types import SimpleNamespace

import pytest

from backend import building, matterport, vexcel
from backend.recovery.domain import sources
from backend.recovery.domain.spatial import scan_locations, structure_candidate
from backend.recovery.domain.temporal import date_bounds, normalize_date, relative_to_incident, select_capture_pair, source_eligibility


def test_source_dates_require_availability_in_replay_and_keep_precision():
    assert source_eligibility("2024-07-07", None, "2024-07-08", "historical_replay")[0] is False
    assert source_eligibility("2024-07-07", "2024-07-09", "2024-07-08", "historical_replay")[0] is False
    assert source_eligibility("2024-07-07", "2024-07-08", "2024-07-08", "historical_replay")[0]
    assert source_eligibility("2024-07-08", None, "2024-07-08T12:00:00Z", "observed_recovery")[0] is False
    assert relative_to_incident("2024-07-08", "2024-07-08T12:00:00Z") == "overlapping"
    assert relative_to_incident(None, "2024-07-08") == "unknown"
    assert normalize_date("Fri Jan 02 18:43:55 UTC 2026") == "2026-01-02T18:43:55Z"
    assert date_bounds("2024-07-08")[0].tzinfo == timezone.utc
    with pytest.raises(ValueError, match="timezone"):
        date_bounds("2024-07-08T12:00:00")


def test_pair_never_uses_same_day_or_future_capture():
    captures = [{"collection": str(i), "date": date} for i, date in enumerate(
        ["2024-06-01", "2024-07-07", "2024-07-08", "2024-07-09", "2024-08-01"])]
    pair = select_capture_pair(captures, "2024-07-08", "2024-07-10")
    assert pair["before"]["date"] == "2024-07-07"
    assert pair["after"]["date"] == "2024-07-09"
    assert select_capture_pair(captures, "2024-07-08", "2024-07-10", "historical_replay")["before"] is None


def test_capture_pair_respects_mosaic_windows_and_unknown_start():
    captures = [
        {"collection": "before", "date": "2024-07-01", "first_date": "2024-06-01"},
        {"collection": "overlapping", "date": "2024-07-09", "first_date": "2024-07-01"},
        {"collection": "unknown", "date": "2024-07-10", "first_date": None},
        {"collection": "after", "date": "2024-09-28", "first_date": "2024-08-07"},
        {"collection": "reversed", "date": "2024-07-10", "first_date": "2024-08-01"},
    ]
    pair = select_capture_pair(captures, "2024-07-08", "2024-10-01")
    assert pair["before"]["collection"] == "before"
    assert pair["after"]["collection"] == "after"
    assert select_capture_pair(captures, "2024-07-08", "2024-09-01")["after"] is None


def test_full_capture_inventory_uses_versioned_cache_and_keeps_nearby_flights(tmp_path, monkeypatch):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    old = tmp_path / "captures" / f"{vexcel._key('POINT(0 0)', 0.12)}.json"
    old.parent.mkdir()
    old.write_text('[{"collection":"old-thinned","date":"2024-01-01","gsd":0.1}]')
    calls = []
    payload = {"features": [{"properties": {"collection": name, "last-capture-date": date, "min-gsd": gsd, "layer": "urban"}}
                            for name, date, gsd in [("before", "2024-07-07", .09), ("after", "2024-07-09", .1), ("bad", "2024-07-10", .4)]]}
    def send(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(status_code=200, is_success=True, json=lambda: payload)
    monkeypatch.setattr(vexcel, "_send", send)
    assert vexcel.captures("POINT(0 0)", thin=False, cached_only=True) == []
    assert len(calls) == 0
    assert [c["collection"] for c in vexcel.captures("POINT(0 0)", thin=False)] == ["after", "before"]
    assert [c["collection"] for c in vexcel.captures("POINT(0 0)")] == ["before"]
    assert len(calls) == 1
    assert len(vexcel.captures("POINT(0 0)", max_gsd=.5, thin=False, cached_only=True)) == 3


def test_cached_bundle_upgrade_keeps_rooms_and_does_not_fetch(site, tmp_path, monkeypatch):
    monkeypatch.setattr(matterport, "MP_CACHE", tmp_path / "mp")
    path = matterport.MP_CACHE / "SCAN1" / "model.json"
    path.parent.mkdir(parents=True)
    model = {"id": "SCAN1", "name": "Unit plan", "created": "2026-11-01T00:00:00Z", "geo": {},
             "rooms": [{"id": "room1", "label": "Living room", "polygon": [[0, 0], [1, 0], [0, 1]]}],
             "floors": [{"id": "floor1"}],
             "sweeps": [{"id": "w1", "has_pano": True, "x": 1, "y": 2, "z": 3, "room_id": "room1", "floor_id": "floor1"}]}
    path.write_text(json.dumps(model))
    monkeypatch.setattr(matterport, "fetch_model", lambda *_: pytest.fail("must use local cache"))
    bundle = copy.deepcopy(site.d)
    bundle["version"] = 3
    out = building.upgrade_cached_bundle(bundle)
    scan = out["scans"][0]
    assert scan["scanned"] == "" and scan["captured_at"] is None
    assert scan["model_created_at"] == model["created"]
    assert scan["rooms"][0]["polygon"] == model["rooms"][0]["polygon"]
    assert scan["sweeps"][0]["room_id"] == "room1"
    assert scan["sweeps"][0]["model_position"] == {"x": 1, "y": 2, "z": 3}


def test_gps_never_verifies_structure_or_household(site):
    scan = site.d["scans"][0]
    candidate = structure_candidate(*scan["origin"], site.d["structures"])
    assert candidate["structure_id"] == "S1" and candidate["binding"] == "unverified"
    locations = scan_locations(scan, site.d["structures"])
    assert all(l["binding"] == "unverified" and l["unit_label"] is None for l in locations)
    assert structure_candidate(None, None, site.d["structures"]) is None


def test_normalize_sales_excludes_portfolio_totals_and_preserves_status():
    enums = {"MonetaryUnit": {"1": "UnitedStatesDollar", "2": "CanadianDollar"}, "SalePriceStatus": {"3": "Confirmed", "8": "Allocated"}}
    rows = [dict(id="p", soldForPrice=10000000, soldDate="2024-01-01", monetaryUnit=1,
                 numberOfEntities=2, salePriceStatus=3, entities=[{"propertyId": 1, "allocatedPrice": 4000000, "allocatedPriceStatus": 8}, {"propertyId": 2}]),
            dict(id="c", soldForPrice=5000000, soldDate="2024-01-01", monetaryUnit=2,
                 salePriceStatus=3, entities=[{"propertyId": 3}])]
    normalized = sources.normalize_sales(rows + [rows[0]], {}, enums)
    assert len(normalized) == 3
    assert normalized[0]["price_usd"] == 4000000 and normalized[0]["allocated"]
    assert normalized[1]["price_usd"] is None
    assert normalized[2]["currency"] == "CanadianDollar" and normalized[2]["price_usd"] is None
    assert normalized[0]["source_ids"] == ["costar:commercial-sale-comp:p"]


@pytest.fixture
def inventory_environment(site, monkeypatch, tmp_path):
    kit = tmp_path / "kit"
    (kit / "schemas").mkdir(parents=True)
    (kit / "data").mkdir()
    (kit / "schemas" / "enums.json").write_text('{}')
    (kit / "data" / "commercial-sale-comp.jsonl").write_text('')
    monkeypatch.setattr(sources, "KIT_DIR", kit)
    monkeypatch.setattr(sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(sources.portfolio, "buildings", lambda: [site.d["record"]])
    monkeypatch.setattr(matterport, "MP_CACHE", tmp_path / "mp")
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path / "vx")
    monkeypatch.setattr(vexcel, "_send", lambda *_a, **_k: pytest.fail("network forbidden"))
    monkeypatch.setattr(matterport, "fetch_model", lambda *_a, **_k: pytest.fail("network forbidden"))
    return site


def test_offline_inventory_joins_three_layers_without_claiming_damage(inventory_environment):
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    assert set(e["kind"] for e in out["evidence"]) == {"costar_record", "vexcel_image", "matterport_view"}
    assert len({e["evidence_id"] for e in out["evidence"]}) == len(out["evidence"])
    assert out["capture_pairs"]["before"] is None
    assert all(e["available_at"] is None for e in out["evidence"])
    aerial = next(e for e in out["evidence"] if e["source_label"] == "Vexcel aerial site image")
    assert aerial["captured_at"] == "2026-01-02T18:43:55Z"
    assert out["assets"][aerial["evidence_id"]]["kind"] == "local_image"
    image_path = building.building_dir(7) / "aerial.jpg"
    assert out["assets"][aerial["evidence_id"]]["sha256"] == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert out["structures"][0]["roof_analysis_date"] == "2025-06-01"
    assert out["structures"][0]["roof_analysis_date"] != aerial["captured_at"]


def test_historical_inventory_does_not_leak_current_geometry(inventory_environment):
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2024-07-10", mode="historical_replay")
    assert out["evidence"] == [] and out["locations"] == [] and out["scans"] == []
    assert out["assets"] == {} and out["structures"] == []
    assert out["subject"]["gba_sqft"] is None and out["subject"]["historical_record_unavailable"]
    assert out["source_status"]["vexcel"]["excluded"] == 2


def test_inventory_rejects_symlinked_image_outside_cache(inventory_environment, tmp_path, monkeypatch):
    # Restrict the cache root to the building directory; a sibling target is outside it.
    monkeypatch.setattr(sources, "CACHE_DIR", building.building_dir(7))
    original = building.building_dir(7) / "aerial.jpg"
    outside = tmp_path / "outside.jpg"
    original.rename(outside)
    original.symlink_to(outside)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    aerial = next(e for e in out["evidence"] if e["source_label"] == "Vexcel aerial site image")
    assert aerial["evidence_id"] not in out["assets"]
    assert any("outside the approved cache" in message for message in out["limitations"])


def test_capture_asset_pins_expected_date(inventory_environment, monkeypatch):
    monkeypatch.setattr(vexcel, "captures", lambda *_a, **_k: [
        {"collection": "before", "date": "2024-07-07", "first_date": "2024-07-01", "last_date": "2024-07-07", "layer": "urban"},
        {"collection": "after", "date": "2024-07-09", "first_date": "2024-07-09", "last_date": "2024-07-09", "layer": "graysky"}])
    descriptors = []
    def unavailable(descriptor, allow_network):
        descriptors.append(descriptor)
        assert allow_network is False
        return None, "Capture image has not been fetched"
    monkeypatch.setattr(sources, "_resolve_pair_capture", unavailable)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    assert {a["collection"]: a["expected_date"] for a in descriptors} == {
        "before": "2024-07-07", "after": "2024-07-09"}
    assert descriptors[0]["expected_first_date"] == "2024-07-01"
    assert descriptors[1]["layers"] == "graysky" and descriptors[1]["role"] == "after"
    assert all(item["incident_at"] == "2024-07-08" and item["assessment_as_of"] == "2026-11-14" for item in descriptors)
    assert all(not out["capture_pairs"][role]["image_available"] for role in ("before", "after"))
    assert not any(asset["kind"] == "vexcel_capture" for asset in out["assets"].values()), "Unvalidated images must not become frozen assets"


def _seed_capture_pair(site, *, after_metadata=None, after_buffer=0, request_layers=False):
    from PIL import Image
    from shapely.geometry import box

    area = box(*site.d["aerial"]["bounds"]).wkt
    before = {"collection": "before", "first_date": "2024-06-01", "last_date": "2024-07-07", "date": "2024-07-07",
              "layer": "urban", "gsd": .3, "last_publish": "2024-07-21"}
    after = {"collection": "after", "first_date": "2024-07-09", "last_date": "2024-07-20", "date": "2024-07-20",
             "layer": "graysky", "gsd": .4, "last_publish": "2024-07-21"}
    paths = {}
    for layers, capture, first, last, buffer_m in (
        (vexcel.VEXCEL_LAYERS, before, "2024-07-01", "2024-07-02", 8),
        ("graysky,graysky-g", after, "2024-07-10", "2024-07-11", after_buffer),
    ):
        catalog = vexcel.VX_CACHE / "captures_v2" / f"{vexcel._key(area, layers)}.json"
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(json.dumps([capture]))
        body = {"wkt": area, "srid": 4326, "layer": layers if request_layers else capture["layer"], "buffer-meter": buffer_m,
                "crop": "bounding_box", "image-format": "jpeg", "collection": capture["collection"],
                "destination-dimensions": "1536,1536"}
        path = vexcel.VX_CACHE / "images" / f"{vexcel._key('ortho/extract', body)}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(path, "JPEG")
        fields = {"collection": capture["collection"], "layer": capture["layer"],
                  "first-capture-date": first, "last-capture-date": last,
                  "last-publish-date": "2024-07-21", "geometry": area, "min-gsd": str(capture["gsd"])}
        if capture["collection"] == "after":
            fields.update(after_metadata or {})
        packet = "<x:xmpmeta>" + "".join(f"<Vexcel:{key}>{value}</Vexcel:{key}>" for key, value in fields.items()) + "</x:xmpmeta>"
        with path.open("ab") as stream:
            stream.write(packet.encode())
        paths[capture["collection"]] = path
    return area, paths


@pytest.mark.parametrize("request_layers", [False, True])
def test_cached_pair_freezes_real_bytes_and_uses_narrower_actual_windows(inventory_environment, request_layers):
    from backend.recovery.platform.models import Evidence

    _, paths = _seed_capture_pair(inventory_environment, request_layers=request_layers)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2024-08-01")
    assert out["source_status"]["vexcel"]["comparison_images_available"] == 2
    after = out["capture_pairs"]["after"]
    assert (after["first_date"], after["last_date"]) == ("2024-07-10", "2024-07-11")
    assert (after["catalog_first_date"], after["catalog_last_date"]) == ("2024-07-09", "2024-07-20")
    assert after["image_available"] and after["layer"] == "graysky"
    for role in ("before", "after"):
        pair = out["capture_pairs"][role]
        asset = out["assets"][pair["evidence_id"]]
        assert asset == {"kind": "local_image", "path": str(paths[role].resolve()),
                         "sha256": hashlib.sha256(paths[role].read_bytes()).hexdigest()}
        evidence = next(row for row in out["evidence"] if row["evidence_id"] == pair["evidence_id"])
        Evidence.model_validate(evidence)
        assert evidence["captured_at"] == pair["last_capture"] and evidence["available_at"] == "2024-07-21"
        assert "capture window" in evidence["summary"] and "No damage determination" in evidence["summary"]


def test_network_opt_in_fetches_only_selected_images_after_cache_probes(inventory_environment, monkeypatch):
    _, paths = _seed_capture_pair(inventory_environment, after_buffer=8)
    catalog_calls, image_calls = [], []
    original_captures = vexcel.captures
    def captures(*args, **kwargs):
        catalog_calls.append(kwargs)
        return original_captures(*args, **kwargs)
    monkeypatch.setattr(vexcel, "captures", captures)
    def ortho(area_wkt, **kwargs):
        image_calls.append(kwargs)
        if kwargs["cached_only"]:
            raise FileNotFoundError()
        path = paths[kwargs["collection"]]
        return path, vexcel._image_info(path.read_bytes())
    monkeypatch.setattr(vexcel, "ortho", ortho)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14", allow_network=True)
    assert all(call["max_gsd"] is None and call["thin"] is False for call in catalog_calls)
    assert {call["layers"] for call in catalog_calls} == {vexcel.VEXCEL_LAYERS, "graysky,graysky-g"}
    assert [call["collection"] for call in image_calls if not call["cached_only"]] == ["before", "after"]
    assert out["source_status"]["vexcel"]["comparison_images_available"] == 2


@pytest.mark.parametrize("bad_metadata", [
    {"first-capture-date": "2024-07-07"},
    {"last-capture-date": "2027-01-01"},
    {"geometry": "POLYGON((0 0,1 0,1 1,0 1,0 0))"},
    {"collection": "other-collection"},
    {"layer": "other-layer"},
])
def test_mismatched_pair_images_remain_metadata_only(inventory_environment, bad_metadata):
    _seed_capture_pair(inventory_environment, after_metadata=bad_metadata)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    after = out["capture_pairs"]["after"]
    assert after and not after["image_available"] and after["unavailable_reason"]
    assert after["evidence_id"] not in out["assets"]
    assert out["capture_pairs"]["before"]["image_available"]


def test_actual_future_publication_excludes_pair_evidence(inventory_environment):
    _seed_capture_pair(inventory_environment, after_metadata={"last-publish-date": "2027-01-01"})
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    assert out["capture_pairs"]["after"] is None
    assert not any(row["source_id"] == "vexcel:collection:after:7" for row in out["evidence"])


def test_legacy_catalog_unknown_start_never_becomes_post_incident_pair(inventory_environment, monkeypatch):
    monkeypatch.setattr(vexcel, "captures", lambda *_a, **_k: [{"collection": "legacy", "date": "2024-07-09", "gsd": .1}])
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    assert out["capture_pairs"]["after"] is None and out["captures"][0]["first_date"] is None


def test_duplicate_local_image_is_hashed_once(inventory_environment, monkeypatch):
    aerial = building.building_dir(7) / "aerial.jpg"
    face = matterport.MP_CACHE / "SCAN1" / "faces" / "w1_1.jpg"
    face.parent.mkdir(parents=True)
    face.symlink_to(aerial)
    digests = []
    original = hashlib.file_digest
    def digest(stream, algorithm):
        digests.append(stream.name)
        return original(stream, algorithm)
    monkeypatch.setattr(sources.hashlib, "file_digest", digest)
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    assert len([a for a in out["assets"].values() if a["kind"] == "local_image"]) == 2
    assert len(digests) == 1


@pytest.mark.parametrize("mode", ["observed_recovery", "scenario_exercise"])
def test_future_model_creation_excludes_views_and_spatial_data(inventory_environment, mode):
    path = building.building_dir(7) / "building.json"
    bundle = json.loads(path.read_text())
    bundle["scans"][0].update(captured_at=None, model_created_at="2026-11-15T00:00:00Z")
    path.write_text(json.dumps(bundle))
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14", mode=mode)
    assert not any(e["kind"] == "matterport_view" for e in out["evidence"])
    assert out["scans"] == []
    assert not any(location["scan_id"] for location in out["locations"])
    assert not any(a["kind"] == "matterport_face" for a in out["assets"].values())
    assert out["source_status"]["matterport"]["excluded"] == 1
    assert any("Model was created after the assessment cutoff" in reason for reason in out["limitations"])


def test_model_creation_cutoff_does_not_become_capture_or_availability(inventory_environment):
    path = building.building_dir(7) / "building.json"
    bundle = json.loads(path.read_text())
    bundle["scans"][0].update(captured_at=None, model_created_at="2026-11-13T00:00:00Z")
    path.write_text(json.dumps(bundle))
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    model = next(e for e in out["evidence"] if e["source_id"] == "matterport:model:SCAN1")
    assert model["captured_at"] is None and model["available_at"] is None
    assert model["model_created_at"] == "2026-11-13T00:00:00Z"
