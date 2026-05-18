import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _load_files_module():
    module_path = Path(__file__).resolve().parents[1] / "webui" / "api" / "files.py"
    assert module_path.exists(), "webui/api/files.py should exist"
    spec = importlib.util.spec_from_file_location("test_files_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_files_route_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = Path(__file__).resolve().parents[1] / "webui" / "api" / "routes" / "files.py"
    assert module_path.exists(), "webui/api/routes/files.py should exist"

    gateway_stub = types.ModuleType("webui.api.gateway")
    gateway_stub.ServiceContainer = object

    deps_stub = types.ModuleType("webui.api.deps")

    async def get_services(request: Request):
        return request.app.state.services

    deps_stub.get_services = get_services

    previous_gateway = sys.modules.get("webui.api.gateway")
    previous_deps = sys.modules.get("webui.api.deps")
    sys.path.insert(0, str(repo_root))
    sys.modules["webui.api.gateway"] = gateway_stub
    sys.modules["webui.api.deps"] = deps_stub
    try:
        spec = importlib.util.spec_from_file_location("test_files_route_module", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_gateway is not None:
            sys.modules["webui.api.gateway"] = previous_gateway
        else:
            sys.modules.pop("webui.api.gateway", None)
        if previous_deps is not None:
            sys.modules["webui.api.deps"] = previous_deps
        else:
            sys.modules.pop("webui.api.deps", None)
        try:
            sys.path.remove(str(repo_root))
        except ValueError:
            pass


class _FakeSession:
    def __init__(self, messages):
        self.messages = messages


class _FakeSessionManager:
    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self):
        return [{"key": key} for key in self._sessions]

    def get_or_create(self, key):
        return self._sessions[key]


def _make_services(workspace: Path, session_manager: _FakeSessionManager):
    return SimpleNamespace(
        config=SimpleNamespace(
            workspace_path=workspace,
            agents=SimpleNamespace(defaults=SimpleNamespace(workspace=str(workspace))),
        ),
        session_manager=session_manager,
    )


def _make_file_client(services):
    route_module = _load_files_route_module()
    app = FastAPI()
    app.state.services = services
    app.include_router(route_module.router, prefix="/api/files")
    return TestClient(app)


def test_build_attachment_metadata_for_workspace_file(tmp_path):
    files_module = _load_files_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("hello download\n", encoding="utf-8")

    attachment = files_module.build_attachment_metadata(workspace, report)

    assert attachment["id"].startswith("att_")
    assert attachment["name"] == "report.txt"
    assert attachment["mime_type"] == "text/plain"
    assert attachment["size"] == report.stat().st_size
    assert len(attachment["token"]) >= 16
    assert attachment["download_url"] == f"/api/files/d/{attachment['token']}"


def test_build_attachment_metadata_rejects_missing_file(tmp_path):
    files_module = _load_files_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(FileNotFoundError):
        files_module.build_attachment_metadata(workspace, workspace / "missing.txt")


def test_build_attachment_metadata_rejects_file_outside_workspace(tmp_path):
    files_module = _load_files_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    with pytest.raises(PermissionError):
        files_module.build_attachment_metadata(workspace, outside)


def test_download_route_returns_workspace_file_by_token(tmp_path):
    files_module = _load_files_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("download me\n", encoding="utf-8")
    attachment = files_module.build_attachment_metadata(workspace, report)

    services = _make_services(
        workspace,
        _FakeSessionManager(
            {
                "web:test:abc": _FakeSession([{"role": "assistant", "attachments": [attachment]}]),
            }
        ),
    )
    client = _make_file_client(services)

    response = client.get(f"/api/files/d/{attachment['token']}")

    assert response.status_code == 200
    assert response.content == report.read_bytes()
    assert "attachment;" in response.headers["content-disposition"]
    assert "report.txt" in response.headers["content-disposition"]


def test_download_route_returns_404_for_unknown_token(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    services = _make_services(workspace, _FakeSessionManager({"web:test:abc": _FakeSession([])}))
    client = _make_file_client(services)

    response = client.get("/api/files/d/unknown-token")

    assert response.status_code == 404


def test_download_route_returns_agentplayground_report_by_token(tmp_path):
    from webui.services.g_file_compare.service import GFileCompareService

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app_root = tmp_path / "agentplayground" / "g-file-compare"
    d5000_file = tmp_path / "d5000.txt"
    d5000_file.write_text("alpha\n", encoding="utf-8")
    new_gen_file = tmp_path / "new-gen.txt"
    new_gen_file.write_text("beta\n", encoding="utf-8")

    service = GFileCompareService(app_root=app_root)
    service.initialize()
    job = service.create_job(d5000_file, new_gen_file, run_in_background=False)
    report = app_root / "jobs" / job["id"] / "report.txt"
    report.write_text("# report\n", encoding="utf-8")
    completed = service.mark_completed(job["id"], report)
    assert completed is not None

    services = _make_services(workspace, _FakeSessionManager({"web:test:abc": _FakeSession([])}))
    services.g_file_compare_service = service
    client = _make_file_client(services)

    response = client.get(completed["download_url"])

    assert response.status_code == 200
    assert response.content == report.read_bytes()
    assert "report.txt" in response.headers["content-disposition"]


def test_download_route_rejects_token_path_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    attachment = {
        "id": "att_test",
        "name": "outside.txt",
        "mime_type": "text/plain",
        "size": outside.stat().st_size,
        "token": "outside-token",
        "download_url": "/api/files/d/outside-token",
        "relative_path": "../outside.txt",
    }

    services = _make_services(
        workspace,
        _FakeSessionManager(
            {
                "web:test:abc": _FakeSession([{"role": "assistant", "attachments": [attachment]}]),
            }
        ),
    )
    client = _make_file_client(services)

    response = client.get("/api/files/d/outside-token")

    assert response.status_code == 403
