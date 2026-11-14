"""Isolated API gate tests: no real server startup, credentials, or Platform store."""
import asyncio
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware
import pytest

from backend.recovery.integration import install_legacy_owner_gate


def make_app(authorize_owner=None, *, cors=False):
    app = FastAPI()
    app.state.owner_auth_calls = 0
    if cors:
        app.add_middleware(CORSMiddleware, allow_origins=["https://brace.test"], allow_methods=["GET", "POST"])

    async def owner(request):
        app.state.owner_auth_calls += 1
        token = request.cookies.get("session")
        if token == "resident":
            raise HTTPException(403, "private identity must not leak")
        if token != "owner":
            raise HTTPException(401, "secret token must not leak")
        return {"role": "owner"}

    @app.get("/api/config")
    @app.get("/api/scenarios")
    @app.get("/api/portfolio")
    @app.get("/api/vr/session")
    @app.get("/api/lan")
    @app.get("/api/future-owner-feature")
    @app.get("/api/resident-looking-legacy")
    async def private_record():
        return {"owner_data": True}

    @app.get("/api/buildings/7/image")
    async def image():
        return Response(b"private image", media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/buildings/7/plan")
    async def mutation():
        return {"started": True}

    @app.get("/api/buildings/7/events")
    async def stream():
        async def events():
            yield b"data: one\n\n"
            await asyncio.sleep(0)
            yield b"data: two\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/recovery/session")
    @app.post("/api/resident/session")
    async def bootstrap():
        return {"bootstrap": True}

    @app.get("/api/resident/home")
    @app.get("/api/recovery/cases")
    async def delegated(request: Request):
        role = "resident" if request.url.path.startswith("/api/resident/") else "owner"
        if request.cookies.get("session") != role:
            raise HTTPException(403, "Platform permission denied")
        return {"role": role}

    install_legacy_owner_gate(app, authorize_owner or owner)
    return app


@pytest.mark.parametrize("path", ["/api/config", "/api/scenarios", "/api/portfolio", "/api/vr/session", "/api/lan",
                                 "/api/buildings/7/image", "/api/future-owner-feature", "/api/resident-looking-legacy"])
def test_every_legacy_route_denies_resident_and_forged_role_header(path):
    with TestClient(make_app()) as client:
        response = client.get(path, headers={"X-Role": "owner"})
        assert response.status_code == 401
        assert set(response.json()["error"]) == {"code", "message", "retryable"}
        client.cookies.set("session", "resident")
        response = client.get(path, headers={"X-Role": "owner"})
        assert response.status_code == 403
        assert "private" not in response.text and "secret" not in response.text
        client.cookies.set("session", "owner")
        assert client.get(path).status_code == 200


def test_mutation_requires_owner_and_images_cannot_be_shared_cached():
    with TestClient(make_app()) as client:
        client.cookies.set("session", "resident")
        assert client.post("/api/buildings/7/plan").status_code == 403
        client.cookies.set("session", "owner")
        assert client.post("/api/buildings/7/plan").json() == {"started": True}
        image = client.get("/api/buildings/7/image")
        assert image.content == b"private image"
        assert image.headers["cache-control"] == "private, no-store"
        assert image.headers["cdn-cache-control"] == "no-store"


def test_bootstrap_and_platform_routes_keep_their_own_permissions():
    app = make_app()
    with TestClient(app) as client:
        for path in ("/api/recovery/session", "/api/resident/session"):
            assert client.post(path).status_code == 200
        assert client.get("/api/resident/home").status_code == 403
        client.cookies.set("session", "resident")
        assert client.get("/api/resident/home").json() == {"role": "resident"}
        assert client.get("/api/resident/home").headers["cache-control"] == "private, no-store"
        assert client.get("/api/recovery/cases").status_code == 403
    assert app.state.owner_auth_calls == 0


def test_unmounted_namespace_routes_stay_404_even_with_legacy_catchall():
    app = make_app()

    @app.get("/{path:path}")
    async def catchall(path):
        return {"legacy_secret": True}

    with TestClient(app) as client:
        assert client.get("/api/resident/missing").status_code == 404
        assert client.get("/api/recovery/missing").status_code == 404
        assert client.get("/api/unknown-legacy").status_code == 401


def test_legacy_catchall_cannot_shadow_platform_route_and_receive_bypass():
    app = FastAPI()

    @app.get("/{path:path}")
    async def legacy_catchall(path):
        return {"owner_secret": True}

    @app.get("/api/resident/home")
    async def later_platform_route():
        raise HTTPException(403)

    install_legacy_owner_gate(app, lambda request: False)
    with TestClient(app) as client:
        response = client.get("/api/resident/home")
        assert response.status_code == 404 and "owner_secret" not in response.text


def test_sync_authorization_runs_off_event_loop_and_installation_is_idempotent():
    threads = []

    def owner(request):
        threads.append(threading.current_thread().ident)
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        return True

    app = make_app(owner)
    install_legacy_owner_gate(app, lambda _: pytest.fail("second authorizer replaced the first"))
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 200
    assert len(threads) == 1


@pytest.mark.parametrize("result", [None, False, {"role": "resident"}])
def test_authorization_result_fails_closed(result):
    with TestClient(make_app(lambda request: result)) as client:
        assert client.get("/api/config").status_code in {401, 403}


def test_authorizer_exceptions_never_expose_secrets():
    async def broken(request):
        raise RuntimeError("secret credential with resident private text")

    with TestClient(make_app(broken)) as client:
        response = client.get("/api/config")
        assert response.status_code == 401
        assert response.json()["error"]["retryable"] is True
        assert "credential" not in response.text and "private text" not in response.text


def test_owner_stream_preserves_chunks_and_no_store_policy():
    with TestClient(make_app()) as client:
        client.cookies.set("session", "owner")
        with client.stream("GET", "/api/buildings/7/events") as response:
            assert response.headers["cache-control"] == "private, no-store"
            assert b"".join(response.iter_bytes()) == b"data: one\n\ndata: two\n\n"


def test_cors_preflight_does_not_grant_actual_request_access():
    with TestClient(make_app(cors=True)) as client:
        preflight = client.options("/api/config", headers={"Origin": "https://brace.test", "Access-Control-Request-Method": "GET"})
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "https://brace.test"
        assert client.get("/api/config", headers={"Origin": "https://brace.test"}).status_code == 401
