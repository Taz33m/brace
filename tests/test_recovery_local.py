from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.recovery.domain.service import make_case_seed
from backend.recovery.local import (LocalRecoveryLock, MutationOriginGate, configured_origins,
                                    import_fresh_case, install_local_recovery)


def test_local_database_lock_prevents_importer_from_interrupting_live_runs(tmp_path):
    with LocalRecoveryLock(tmp_path):
        with pytest.raises(RuntimeError, match="in use"):
            LocalRecoveryLock(tmp_path)
    with LocalRecoveryLock(tmp_path):
        assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_local_runtime_releases_lock_at_shutdown_and_has_no_default_login(tmp_path, monkeypatch):
    monkeypatch.delenv("BRACE_OWNER_SECRET", raising=False)
    monkeypatch.delenv("BRACE_ALLOWED_ORIGINS", raising=False)
    app = FastAPI()
    install_local_recovery(app, root=tmp_path)
    with TestClient(app) as client:
        with pytest.raises(RuntimeError, match="in use"):
            LocalRecoveryLock(tmp_path / "platform")
        assert client.post("/api/recovery/session", json={"secret": "not-configured"}).status_code == 503
        with pytest.raises(RuntimeError, match="once"):
            install_local_recovery(app, root=tmp_path)
    with LocalRecoveryLock(tmp_path / "platform"):
        pass


def test_origin_gate_covers_legacy_and_recovery_writes(monkeypatch):
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", "https://brace.test")
    app = FastAPI()

    @app.post("/api/legacy")
    @app.post("/api/recovery/session")
    async def changed():
        return {"ok": True}

    app.add_middleware(MutationOriginGate, origins=configured_origins())
    with TestClient(app) as client:
        for path in ("/api/legacy", "/api/recovery/session"):
            assert client.post(path, headers={"Origin": "https://brace.test"}).status_code == 200
            assert client.post(path, headers={"Origin": "https://sibling.brace.test", "Sec-Fetch-Site": "same-site"}).status_code == 403
            assert client.post(path, headers={"Origin": "null"}).status_code == 403
            assert client.post(path, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 403
            assert client.post(path).status_code == 200  # explicit non-browser client


def test_local_owner_console_opens_without_login_and_keeps_phone_sessions_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("BRACE_LOCAL_OWNER", "1")
    app = FastAPI()

    @app.get("/api/config")
    def config():
        return {"ok": True}

    install_local_recovery(app, root=tmp_path)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as owner:
        assert owner.get("/api/config").status_code == 200
        assert owner.get("/api/recovery/cases").status_code == 200
        assert owner.get("/api/resident/home").status_code == 401
        for headers in ({"Host": "10.1.2.3:5185"}, {"X-Forwarded-For": "10.1.2.4, 127.0.0.1"},
                        {"Sec-Fetch-Site": "cross-site"}):
            assert owner.get("/api/recovery/cases", headers=headers).status_code == 401


@pytest.mark.parametrize("value", ["", "*", "https://brace.test/path", "https://user:pass@brace.test", "null"])
def test_origins_require_explicit_http_origins(monkeypatch, value):
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", value)
    with pytest.raises(ValueError):
        configured_origins()


def test_fresh_import_is_idempotent_and_preserves_current_case(tmp_path):
    from backend.recovery.platform.auth import Actor, LOCAL_OWNER_ID
    from backend.recovery.platform.store import CaseStore
    from backend.recovery.registry import CaseInputRegistry

    inventory = {"subject": {"id": 7, "property_ref": {"dataset": "commercial_property", "id": "7"}},
                 "evidence": [], "locations": []}
    seed = make_case_seed(inventory, incident_name="Synthetic incident", incident_at="2026-11-01",
                          assessment_as_of="2026-11-14")
    store, registry = CaseStore(tmp_path / "db.sqlite3"), CaseInputRegistry(tmp_path / "inputs")
    first = import_fresh_case(store, registry, seed, inventory)
    store.add_household(Actor("owner", LOCAL_OWNER_ID), first["case"]["case_id"], "Synthetic household")
    second = import_fresh_case(store, registry, seed, inventory)
    assert second["case"]["case_revision"] == 2
    assert len(second["household_labels"]) == 1
    with pytest.raises(ValueError, match="fresh"):
        import_fresh_case(store, registry, second, inventory)
