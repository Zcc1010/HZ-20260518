import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def _write_fake_dist(root: Path) -> Path:
    dist = root / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>agentplayground-ok</div></body></html>",
        encoding="utf-8",
    )
    (assets / "main.js").write_text('console.log("agentplayground-ok");', encoding="utf-8")
    return dist


def test_agentplayground_serves_spa_in_authless_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")

    import webui.api.server as server_module

    server_module = importlib.reload(server_module)
    monkeypatch.setattr(server_module, "_resolve_web_dist", lambda: _write_fake_dist(tmp_path))

    client = TestClient(server_module.create_app())

    root_response = client.get("/agentplayground", follow_redirects=False)
    assert root_response.status_code in {302, 307}
    assert root_response.headers["location"] == "/agentplayground/"

    response = client.get("/agentplayground/", follow_redirects=False)

    assert response.status_code == 200
    assert "agentplayground-ok" in response.text

    selected_app_response = client.get("/agentplayground/g-file-compare", follow_redirects=False)
    assert selected_app_response.status_code == 200
    assert "agentplayground-ok" in selected_app_response.text

    unknown_app_response = client.get("/agentplayground/unknown-app", follow_redirects=False)
    assert unknown_app_response.status_code == 200
    assert "agentplayground-ok" in unknown_app_response.text

    api_response = client.get("/agentplayground/api/auth/bootstrap")
    assert api_response.status_code == 200
    assert api_response.json()["auth_disabled"] is True

    asset_response = client.get("/agentplayground/assets/main.js")
    assert asset_response.status_code == 200
    assert 'console.log("agentplayground-ok");' in asset_response.text


def test_agentplayground_redirects_to_assistant_when_auth_is_enabled(monkeypatch, tmp_path):
    monkeypatch.delenv("WEBUI_AUTH_DISABLED", raising=False)

    import webui.api.server as server_module

    server_module = importlib.reload(server_module)
    monkeypatch.setattr(server_module, "_resolve_web_dist", lambda: _write_fake_dist(tmp_path))

    client = TestClient(server_module.create_app())

    response = client.get("/agentplayground/g-file-compare", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"] == "/assistant/"
