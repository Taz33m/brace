"""Private input registration with synthetic fixtures and no network access."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

from backend.recovery.registry import CaseInputRegistry, CaseInputRegistryError, UnknownCaseInputs, evidence_identity
from tests.test_recovery_integration import fixture_case
from tests.test_recovery_valuation import financial


def registered(tmp_path):
    registry = CaseInputRegistry(tmp_path / "private-inputs")
    inventory, snapshot = fixture_case()
    digest = registry.register(snapshot, inventory, financial())
    return registry, inventory, snapshot, digest


def test_registration_is_idempotent_and_loads_context_pinned_sources(tmp_path):
    registry, inventory, snapshot, digest = registered(tmp_path)
    assert registry.register(snapshot, inventory, financial()) == digest
    assert len(list(registry.root.glob("*.json"))) == 1
    loaded = registry.load_inventory(snapshot)
    assert set(loaded["_case_context"]) == {"case_id", "property_ref", "incident_at", "assessment_as_of", "mode"}
    loaded["subject"]["id"] = "tampered-return"
    assert registry.load_inventory(snapshot)["subject"]["id"] == "subject"
    assert not list(registry.root.glob("*.tmp"))


def test_receipt_media_and_equivalent_timestamp_changes_do_not_change_identity(tmp_path):
    registry, inventory, snapshot, digest = registered(tmp_path)
    first_bytes = next(registry.root.glob("*.json")).read_bytes()
    for rows in (inventory["evidence"], snapshot["evidence"]):
        rows[0]["received_at"] = "2026-11-14T15:00:00+00:00"
        rows[0]["media"] = {"url": "/api/recovery/media/protected"}
    assert registry.register(snapshot, inventory, financial()) == digest
    assert next(registry.root.glob("*.json")).read_bytes() == first_bytes
    a = {"evidence_id": "x", "captured_at": "2026-01-01T12:00:00Z"}
    b = {"evidence_id": "x", "captured_at": "2026-01-01T07:00:00-05:00"}
    assert evidence_identity(a) == evidence_identity(b)
    assert evidence_identity({**a, "captured_at": "2026-01-01"}) != evidence_identity(a)


@pytest.mark.parametrize("change", ["subject", "finance", "context"])
def test_changed_facts_finance_or_context_cannot_overwrite(tmp_path, change):
    registry, inventory, snapshot, _ = registered(tmp_path)
    supplied = financial()
    if change == "subject":
        inventory["subject"]["units"] = 999
    elif change == "finance":
        supplied["downtime"]["low_usd"] = 0
    else:
        snapshot["case"]["assessment_as_of"] = "2026-11-15"
    with pytest.raises(CaseInputRegistryError, match="reviewed input version"):
        registry.register(snapshot, inventory, supplied)


def test_case_identifier_is_hashed_and_cannot_traverse(tmp_path):
    registry = CaseInputRegistry(tmp_path / "private")
    inventory, snapshot = fixture_case()
    snapshot["case"]["case_id"] = "../../escape/secret"
    registry.register(snapshot, inventory)
    paths = list(registry.root.iterdir())
    assert len(paths) == 1 and paths[0].suffix == ".json" and len(paths[0].stem) == 64
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("where", ["inventory", "financial"])
def test_nan_is_rejected_before_file_creation(tmp_path, where):
    registry = CaseInputRegistry(tmp_path)
    inventory, snapshot = fixture_case()
    supplied = financial()
    if where == "inventory":
        inventory["subject"]["units"] = float("nan")
    else:
        supplied["downtime"]["low_usd"] = float("nan")
    with pytest.raises(CaseInputRegistryError, match="finite JSON"):
        registry.register(snapshot, inventory, supplied)
    assert not list(tmp_path.iterdir())


def test_unknown_or_foreign_case_has_no_fallback(tmp_path):
    registry = CaseInputRegistry(tmp_path)
    inventory, snapshot = fixture_case()
    with pytest.raises(UnknownCaseInputs):
        registry.load_inventory(snapshot)
    inventory["subject"]["id"] = "another-property"
    with pytest.raises(CaseInputRegistryError, match="different property"):
        registry.register(snapshot, inventory)
    snapshot["case"]["property_ref"]["dataset"] = "residential_property"
    with pytest.raises(CaseInputRegistryError, match="commercial"):
        registry.register(snapshot, inventory)


def test_manifest_corruption_is_detected_even_for_ignored_bookkeeping(tmp_path):
    registry, _, snapshot, _ = registered(tmp_path)
    path = next(registry.root.glob("*.json"))
    document = json.loads(path.read_text())
    document["payload"]["inventory"]["evidence"][0]["received_at"] = "2027-01-01T00:00:00Z"
    path.write_text(json.dumps(document))
    with pytest.raises(CaseInputRegistryError, match="integrity"):
        registry.load_inventory(snapshot)


@pytest.mark.parametrize("change", ["remove", "date", "location", "duplicate"])
def test_changed_source_provenance_cannot_reuse_old_geometry(tmp_path, change):
    registry, _, snapshot, _ = registered(tmp_path)
    if change == "remove":
        snapshot["evidence"].pop(0)
    elif change == "date":
        snapshot["evidence"][0]["effective_at"] = "2026-11-12"
    elif change == "location":
        snapshot["evidence"][0]["location"] = {"location_id": "another-room"}
    else:
        snapshot["evidence"].append(deepcopy(snapshot["evidence"][0]))
    with pytest.raises(CaseInputRegistryError):
        registry.input_provider(snapshot)


def test_added_reports_use_snapshot_evidence_without_network(tmp_path):
    registry, inventory, snapshot, _ = registered(tmp_path)
    snapshot["case"]["analysis_revision"] += 1
    snapshot["case"]["case_revision"] += 2
    snapshot["evidence"].append({**snapshot["evidence"][0], "evidence_id": "resident-new", "source_id": "resident-new", "kind": "resident_photo"})
    provided, images = registry.input_provider(snapshot)
    assert any(e["evidence_id"] == "resident-new" for e in provided["evidence"])
    assert not any(e["evidence_id"] == "resident-new" for e in inventory["evidence"])
    assert images.allow_network is False
    assert registry.load_inventory(snapshot)["_case_context"]["case_id"] == snapshot["case"]["case_id"]
    with pytest.raises(ValueError, match="authorized image"):
        images("resident-new")


def test_concurrent_identical_registration_has_one_complete_manifest(tmp_path):
    registry = CaseInputRegistry(tmp_path)
    inventory, snapshot = fixture_case()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: registry.register(snapshot, inventory), range(8)))
    assert len(set(results)) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1 and not list(tmp_path.glob("*.tmp"))
    assert registry.load_inventory(snapshot)["subject"] == inventory["subject"]


def test_concurrent_conflicting_registration_cannot_overwrite_winner(tmp_path):
    registry = CaseInputRegistry(tmp_path)
    inventory, snapshot = fixture_case()
    changed = deepcopy(inventory)
    changed["subject"]["units"] = 30

    def register(item):
        try:
            return registry.register(snapshot, item)
        except CaseInputRegistryError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, [inventory, changed]))
    assert sum(value is not None for value in results) == 1
    assert registry.load_inventory(snapshot)["subject"]["units"] in {20, 30}
    assert len(list(tmp_path.glob("*.json"))) == 1 and not list(tmp_path.glob("*.tmp"))


def test_symlink_manifest_is_not_followed(tmp_path):
    registry, _, snapshot, _ = registered(tmp_path)
    path = next(registry.root.glob("*.json"))
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(CaseInputRegistryError, match="safely"):
        registry.load_inventory(snapshot)
