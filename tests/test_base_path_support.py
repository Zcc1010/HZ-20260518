import importlib
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient


def _write_fake_dist(root: Path) -> Path:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>base-path-ok</div></body></html>",
        encoding="utf-8",
    )
    (assets / "main.js").write_text('console.log("base-path-ok");', encoding="utf-8")
    return dist


def test_create_app_serves_prefixed_spa_and_assets_when_base_path_is_configured(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("WEBUI_BASE_PATH", "/assistant/")

    import webui.api.server as server_module

    server_module = importlib.reload(server_module)
    fake_dist = _write_fake_dist(tmp_path)
    monkeypatch.setattr(server_module, "_resolve_web_dist", lambda: fake_dist)

    client = TestClient(server_module.create_app())

    page = client.get("/assistant/")
    assert page.status_code == 200
    assert "base-path-ok" in page.text

    prefixed_asset = client.get("/assistant/assets/main.js")
    assert prefixed_asset.status_code == 200
    assert 'console.log("base-path-ok");' in prefixed_asset.text

    root_asset = client.get("/assets/main.js")
    assert root_asset.status_code == 200
    assert 'console.log("base-path-ok");' in root_asset.text


def test_base_path_middleware_rewrites_prefixed_websocket_requests():
    from webui.api.base_path import BasePathMiddleware

    app = FastAPI()

    @app.websocket("/ws/ping")
    async def ping_socket(websocket: WebSocket):
        await websocket.accept()
        payload = await websocket.receive_text()
        await websocket.send_text(f"echo:{payload}")
        await websocket.close()

    client = TestClient(BasePathMiddleware(app, "/assistant/"))

    with client.websocket_connect("/assistant/ws/ping") as websocket:
        websocket.send_text("hello")
        assert websocket.receive_text() == "echo:hello"


def test_base_path_middleware_rewrites_multiple_prefixed_http_requests():
    from webui.api.base_path import BasePathMiddleware

    app = FastAPI()

    @app.get("/api/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(BasePathMiddleware(app, ["/assistant/", "/agentplayground/"]))

    assert client.get("/assistant/api/ping").json() == {"ok": True}
    assert client.get("/agentplayground/api/ping").json() == {"ok": True}
