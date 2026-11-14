"""Assembly checks using an explicitly synthetic Platform stand-in, not production auth."""
from copy import deepcopy

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from backend.recovery.domain.service import failed_result, make_case_seed
from backend.recovery.registry import CaseInputRegistry
from backend.recovery.runtime import install_recovery


@pytest.fixture
def registered(tmp_path):
    inventory = {"subject": {"id": 7, "property_ref": {"dataset": "commercial_property", "id": "7"},
                              "name": "Synthetic assembly test", "address": "1 Test Way", "city": "Houston"},
                 "evidence": [], "sales": [], "assets": {}, "locations": [], "structures": [], "scans": [],
                 "source_status": {}, "limitations": [], "capture_pairs": {}}
    snapshot = make_case_seed(inventory, case_id="case-test", incident_name="Synthetic test incident",
                              incident_at="2026-11-01", assessment_as_of="2026-11-14")
    registry = CaseInputRegistry(tmp_path / "registry")
    registry.register(snapshot, inventory)
    return registry, snapshot


class Store:
    def __init__(self, snapshot):
        self.snapshot = deepcopy(snapshot)
        self.results = []

    def snapshot_for_analysis(self, case_id):
        assert case_id == self.snapshot["case"]["case_id"]
        return deepcopy(self.snapshot)

    def complete_assessment(self, run_id, revision, result):
        result = deepcopy(result)
        if revision != self.snapshot["case"]["analysis_revision"]:
            result["assessment"]["status"] = "stale"
        self.results.append(result)
        return result


async def owner(request: Request):
    # Test-only dependency. Production identity comes exclusively from Platform.
    if request.headers.get("x-test-actor") != "owner":
        raise HTTPException(401)
    return {"role": "owner"}


def platform_factory(store, launch):
    router = APIRouter()

    @router.post("/api/resident/session")
    async def bootstrap():
        return {"ok": True}

    @router.post("/api/recovery/cases/{case_id}/commands")
    async def command(case_id: str, request: Request):
        await owner(request)
        launch({"run_id": "run-test", "case_id": case_id, "base_analysis_revision": 1})
        return {"run_id": "run-test"}

    return router


def test_mounts_worker_and_scoped_viewer_without_legacy_auth_bypass(registered):
    registry, snapshot = registered
    store = Store(snapshot)
    app = FastAPI()

    @app.get("/api/config")
    async def legacy():
        return {"owner_only": True}

    async def case_owner(request, case_id):
        await owner(request)
        if case_id != "case-test":
            raise HTTPException(404)
        return deepcopy(store.snapshot)

    class TestAgent:
        def __init__(self, snapshot, inputs, **kwargs):
            self.snapshot = snapshot

        def run(self):
            return failed_result(self.snapshot, "run-test", "Synthetic test draft", status="draft")

    service = install_recovery(app, store=store, registry=registry, platform_router_factory=platform_factory,
                               resolve_owner=owner, resolve_owner_case=case_owner, agent_factory=TestAgent)
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 401
        assert client.get("/api/config", headers={"x-test-actor": "resident"}).status_code == 401
        response = client.get("/api/config", headers={"x-test-actor": "owner"})
        assert response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
        assert client.post("/api/resident/session").status_code == 200
        assert client.get("/api/recovery/cases/case-test/spatial").status_code == 401
        spatial = client.get("/api/recovery/cases/case-test/spatial", headers={"x-test-actor": "owner"})
        assert spatial.status_code == 200 and spatial.json()["case_id"] == "case-test"
        assert client.get("/api/recovery/cases/other/spatial", headers={"x-test-actor": "owner"}).status_code == 404
        assert client.post("/api/recovery/cases/case-test/commands").status_code == 401
        assert client.post("/api/recovery/cases/case-test/commands", headers={"x-test-actor": "owner"}).status_code == 200
        assert service.futures["run-test"].result(timeout=3)["assessment"]["status"] == "draft"
        assert len(store.results) == 1
    # The application lifespan owns worker shutdown.
    with pytest.raises(RuntimeError, match="shutdown"):
        service.pool.submit(lambda: None)


def test_mount_requires_explicit_dependencies_and_before_startup(registered):
    registry, snapshot = registered
    store = Store(snapshot)
    app = FastAPI()
    with pytest.raises(TypeError, match="authorizers"):
        install_recovery(app, store=store, registry=registry, platform_router_factory=platform_factory,
                          resolve_owner=None, resolve_owner_case=None)
    with pytest.raises(TypeError, match="worker handshake"):
        install_recovery(app, store=object(), registry=registry, platform_router_factory=platform_factory,
                          resolve_owner=owner, resolve_owner_case=lambda *args: snapshot)
    with TestClient(app):
        original = list(app.routes)
        with pytest.raises(RuntimeError, match="before"):
            install_recovery(app, store=store, registry=registry, platform_router_factory=platform_factory,
                              resolve_owner=owner, resolve_owner_case=lambda *args: snapshot)
        assert app.routes == original


def test_factory_failure_does_not_publish_partial_routes(registered):
    registry, snapshot = registered
    app = FastAPI()

    def broken(*args):
        raise RuntimeError("Test factory failed")

    before = list(app.routes)
    with pytest.raises(RuntimeError, match="factory failed"):
        install_recovery(app, store=Store(snapshot), registry=registry, platform_router_factory=broken,
                          resolve_owner=owner, resolve_owner_case=lambda *args: snapshot)
    assert app.routes == before
