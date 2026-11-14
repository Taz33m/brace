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
        {"collection": "before", "date": "2024-07-07"},
        {"collection": "after", "date": "2024-07-09"}])
    out = sources.load_inventory(7, incident_at="2024-07-08", assessment_as_of="2026-11-14")
    captures = [a for a in out["assets"].values() if a["kind"] == "vexcel_capture"]
    assert {a["collection"]: a["expected_date"] for a in captures} == {
        "before": "2024-07-07", "after": "2024-07-09"}


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
