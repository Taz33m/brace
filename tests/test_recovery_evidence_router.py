from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from threading import get_ident

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.recovery.evidence_router import build_evidence_router


@pytest.fixture
def registered(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    image = cache / "aerial.jpg"
    exif = Image.Exif()
    exif[270] = "private original metadata"
    Image.new("RGB", (2000, 1000), (80, 100, 120)).save(image, exif=exif)
    case = {"case_id": "case-a", "property_ref": {"dataset": "commercial_property", "id": "7"},
            "incident_at": "2024-07-08", "assessment_as_of": "2026-11-14", "mode": "scenario_exercise",
            "analysis_revision": 1}
    evidence = [{"evidence_id": "ev-aerial", "kind": "vexcel_image", "source_id": "vexcel:7:2026-01-02",
                 "source_label": "Aerial image", "captured_at": "2026-01-02", "effective_at": None,
                 "available_at": None, "model_created_at": None, "location": None,
                 "summary": "Site image", "limitations": [], "received_at": "2026-11-14T12:00:00Z", "media": None}]
    snapshot = {"case": case, "evidence": deepcopy(evidence), "observations": []}
    inventory = {"_case_context": {k: case[k] for k in ("case_id", "property_ref", "incident_at", "assessment_as_of", "mode")},
                 "subject": {"property_ref": deepcopy(case["property_ref"])}, "evidence": evidence,
                 "assets": {"ev-aerial": {"kind": "local_image", "path": str(image), "sha256": sha256(image.read_bytes()).hexdigest()}},
                 "locations": [], "structures": [], "scans": [], "capture_pairs": {}, "source_status": {"vexcel": "available"}, "limitations": []}
    calls = []

    def resolve(request, case_id):
        calls.append(("resolve", case_id, get_ident()))
        actor = request.headers.get("X-Test-Actor")
        if actor is None:
            raise HTTPException(401, "SECRET internal auth context")
        if actor != "owner":
            raise HTTPException(403, "SECRET resident household")
        if case_id != "case-a":
            raise HTTPException(404, "SECRET assignment details")
        return snapshot

    def provide(value):
        calls.append(("provide", value["case"]["case_id"], get_ident()))
        return inventory

    app = FastAPI()
    app.include_router(build_evidence_router(resolve, provide, cache_root=cache))
    return {"client": TestClient(app), "snapshot": snapshot, "inventory": inventory, "image": image,
            "calls": calls, "resolve": resolve, "provide": provide, "cache": cache}


OWNER = {"X-Test-Actor": "owner"}
SPATIAL = "/api/recovery/cases/case-a/spatial"
IMAGE = "/api/recovery/cases/case-a/evidence/ev-aerial/image"


@pytest.mark.parametrize("path", [SPATIAL, IMAGE])
@pytest.mark.parametrize("headers,status", [({}, 401), ({"X-Test-Actor": "resident"}, 403)])
def test_owner_auth_runs_before_inventory_and_errors_are_private(registered, path, headers, status):
    response = registered["client"].get(path, headers=headers)
    assert response.status_code == status
    assert response.headers["cache-control"] == "private, no-store"
    assert "SECRET" not in response.text
    assert [c[0] for c in registered["calls"]] == ["resolve"]


def test_other_case_cannot_enumerate_images(registered):
    response = registered["client"].get(IMAGE.replace("case-a", "case-b"), headers=OWNER)
    assert response.status_code == 404
    assert [c[0] for c in registered["calls"]] == ["resolve"]


def test_owner_spatial_response_is_allowlisted_and_revision_current(registered):
    registered["snapshot"]["case"]["analysis_revision"] = 2
    registered["snapshot"]["evidence"].append({"evidence_id": "resident-report", "kind": "resident_photo"})
    response = registered["client"].get(SPATIAL, headers=OWNER)
    assert response.status_code == 200
    assert response.json()["analysis_revision"] == 2
    assert set(response.json()) == {"case_id", "analysis_revision", "locations", "structures", "scans", "capture_pairs", "source_status", "limitations", "image_evidence_ids"}
    assert response.json()["image_evidence_ids"] == ["ev-aerial"]
    assert "assets" not in response.json() and "subject" not in response.json()
    assert response.headers["cache-control"] == "private, no-store"


def test_authorized_image_is_sanitized_jpeg(registered):
    response = registered["client"].get(IMAGE, headers=OWNER)
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    with Image.open(BytesIO(response.content)) as result:
        assert result.size == (1536, 768)
        assert not result.getexif()


@pytest.mark.parametrize("change", ["context", "property", "cutoff", "missing_context", "bad_revision", "removed_evidence", "corrected_evidence", "future_capture", "future_model"])
def test_manifest_mismatch_requires_refresh_without_fallback(registered, change):
    inventory, snapshot = registered["inventory"], registered["snapshot"]
    if change == "context":
        inventory["_case_context"]["case_id"] = "case-b"
    elif change == "property":
        inventory["subject"]["property_ref"]["id"] = "other"
    elif change == "cutoff":
        snapshot["case"]["assessment_as_of"] = "2026-11-15"
    elif change == "missing_context":
        inventory.pop("_case_context")
    elif change == "bad_revision":
        snapshot["case"]["analysis_revision"] = 0
    elif change == "removed_evidence":
        snapshot["evidence"].clear()
    elif change == "corrected_evidence":
        snapshot["evidence"][0]["summary"] = "Corrected source interpretation"
    else:
        key = "captured_at" if change == "future_capture" else "model_created_at"
        inventory["evidence"][0][key] = "2026-12-01"
        snapshot["evidence"][0][key] = "2026-12-01"
    response = registered["client"].get(SPATIAL, headers=OWNER)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "source_refresh_required"


def test_unreferenced_spatial_scan_is_not_exposed(registered):
    registered["inventory"]["scans"] = [{"id": "private-unrelated-scan"}]
    response = registered["client"].get(SPATIAL, headers=OWNER)
    assert response.status_code == 503
    assert "private-unrelated-scan" not in response.text


def test_changed_image_bytes_require_explicit_refresh(registered):
    Image.new("RGB", (20, 20), "red").save(registered["image"])
    response = registered["client"].get(IMAGE, headers=OWNER)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "source_changed"
    assert registered["client"].get(SPATIAL, headers=OWNER).json()["image_evidence_ids"] == []


def test_timestamp_equivalence_and_media_decoration_preserve_source_identity(registered):
    original = registered["inventory"]["evidence"][0]
    current = registered["snapshot"]["evidence"][0]
    original["captured_at"] = "2026-01-02T10:00:00Z"
    current["captured_at"] = "2026-01-02T10:00:00+00:00"
    current["media"] = {"url": "/api/private/image"}
    current["received_at"] = "2026-11-14T13:00:00Z"
    assert registered["client"].get(SPATIAL, headers=OWNER).status_code == 200
    # An exact midnight timestamp is still not a date-only source date.
    current["captured_at"] = "2026-01-02"
    assert registered["client"].get(SPATIAL, headers=OWNER).status_code == 503


def test_case_context_normalizes_timestamp_offset_without_changing_precision(registered):
    registered["snapshot"]["case"]["incident_at"] = "2024-07-08T12:00:00+00:00"
    registered["snapshot"]["case"]["assessment_as_of"] = "2026-11-14T12:00:00+00:00"
    registered["inventory"]["_case_context"]["incident_at"] = "2024-07-08T12:00:00Z"
    registered["inventory"]["_case_context"]["assessment_as_of"] = "2026-11-14T12:00:00Z"
    assert registered["client"].get(SPATIAL, headers=OWNER).status_code == 200


def test_async_inventory_provider_supported(registered):
    async def provide(snapshot):
        return registered["inventory"]
    app = FastAPI()
    app.include_router(build_evidence_router(registered["resolve"], provide, cache_root=registered["cache"]))
    assert TestClient(app).get(SPATIAL, headers=OWNER).status_code == 200


@pytest.mark.parametrize("change", ["missing_file", "metadata_only", "path_escape", "symlink_escape", "url", "missing_hash", "unfetched_capture", "unfetched_face", "resident_photo", "unregistered"])
def test_image_endpoint_never_fetches_or_serves_unscoped_assets(registered, tmp_path, monkeypatch, change):
    from backend import matterport, vexcel
    monkeypatch.setattr(matterport, "face_image", lambda *_a, **_k: pytest.fail("network attempted"))
    monkeypatch.setattr(vexcel, "ortho", lambda *_a, **_k: pytest.fail("network attempted"))
    descriptor = registered["inventory"]["assets"]["ev-aerial"]
    path = IMAGE
    if change == "missing_file":
        registered["image"].unlink()
    elif change == "metadata_only":
        registered["inventory"]["assets"].clear()
    elif change in ("path_escape", "symlink_escape"):
        outside = tmp_path / "private.jpg"
        outside.write_bytes(registered["image"].read_bytes())
        if change == "path_escape":
            descriptor["path"] = str(outside)
        else:
            registered["image"].unlink()
            registered["image"].symlink_to(outside)
    elif change == "url":
        descriptor["path"] = "https://example.com/SECRET"
    elif change == "missing_hash":
        descriptor.pop("sha256")
    elif change == "unfetched_capture":
        descriptor.update(kind="vexcel_capture", collection="private", area_wkt="POINT(0 0)")
    elif change == "unfetched_face":
        descriptor.update(kind="matterport_face", model_id="private", sweep_id="p", face=1)
    elif change == "resident_photo":
        registered["inventory"]["evidence"][0]["kind"] = "resident_photo"
        registered["snapshot"]["evidence"][0]["kind"] = "resident_photo"
    else:
        path = IMAGE.replace("ev-aerial", "other")
    response = registered["client"].get(path, headers=OWNER)
    assert response.status_code == 404
    assert "SECRET" not in response.text and "private.jpg" not in response.text


def test_async_callbacks_supported_and_sync_provider_off_event_loop(registered):
    event_threads, provider_threads = [], []
    async def resolve(request, case_id):
        event_threads.append(get_ident())
        return registered["snapshot"]
    def provide(snapshot):
        provider_threads.append(get_ident())
        return registered["inventory"]
    app = FastAPI()
    app.include_router(build_evidence_router(resolve, provide, cache_root=registered["cache"]))
    assert TestClient(app).get(SPATIAL).status_code == 200
    assert event_threads[0] != provider_threads[0]


def test_bad_resolver_case_fails_before_inventory(registered):
    def resolve(request, case_id):
        out = deepcopy(registered["snapshot"])
        out["case"]["case_id"] = "case-b"
        return out
    app = FastAPI()
    app.include_router(build_evidence_router(resolve, lambda *_: pytest.fail("wrong-case inventory requested")))
    assert TestClient(app).get(SPATIAL).status_code == 404
