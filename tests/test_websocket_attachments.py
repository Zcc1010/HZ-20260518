import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


def _load_ws_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "webui" / "api" / "routes" / "ws.py"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    spec = importlib.util.spec_from_file_location("test_ws_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeSession:
    def __init__(self):
        self.messages = []
        self.updated_at = None

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content, "timestamp": "2026-04-14T10:00:00"})


class _FakeSessionManager:
    def __init__(self):
        self._sessions = {}

    def get_or_create(self, key):
        if key not in self._sessions:
            self._sessions[key] = _FakeSession()
        return self._sessions[key]

    def save(self, session):
        return None

    def list_sessions(self):
        return [{"key": key} for key in self._sessions]


class _FakeAgent:
    def __init__(self, ws_module, session_manager, outbound_payload):
        self.sessions = session_manager
        self._ws_module = ws_module
        self._outbound_payload = outbound_payload

    async def process_direct(self, msg, session_key=None, channel=None, chat_id=None, on_progress=None):
        session = self.sessions.get_or_create(session_key)
        session.add_message("user", msg)
        session.messages.append({
            "role": "assistant",
            "content": self._outbound_payload["content"],
            "timestamp": "2026-04-14T10:00:01",
        })
        for queue in self._ws_module._web_captures.get(str(chat_id), []):
            await queue.put(dict(self._outbound_payload))
        return ""


def _install_subagent_stub():
    stub = types.ModuleType("webui.patches.subagent")
    stub.register_progress = lambda *args, **kwargs: None
    stub.register_announce = lambda *args, **kwargs: None
    stub.register_save_turn = lambda *args, **kwargs: None
    sys.modules["webui.patches.subagent"] = stub


def _load_sessions_route_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "webui" / "api" / "routes" / "sessions.py"

    gateway_stub = types.ModuleType("webui.api.gateway")
    gateway_stub.ServiceContainer = object

    deps_stub = types.ModuleType("webui.api.deps")

    async def get_services(request: Request):
        return request.app.state.services

    async def get_current_user():
        return {"id": "local-admin", "role": "admin"}

    deps_stub.get_services = get_services
    deps_stub.get_current_user = get_current_user

    previous_gateway = sys.modules.get("webui.api.gateway")
    previous_deps = sys.modules.get("webui.api.deps")
    sys.modules["webui.api.gateway"] = gateway_stub
    sys.modules["webui.api.deps"] = deps_stub
    try:
        spec = importlib.util.spec_from_file_location("test_sessions_module", module_path)
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


def test_websocket_done_frame_preserves_text_and_media(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")
    _install_subagent_stub()
    ws_module = _load_ws_module()
    ws_module._ensure_message_tool_patched = lambda container: None

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("file from workspace\n", encoding="utf-8")

    session_manager = _FakeSessionManager()
    services = SimpleNamespace(
        agent=_FakeAgent(
            ws_module,
            session_manager,
            {
                "content": "Here is the generated file",
                "media": [str(report)],
            },
        ),
        config=SimpleNamespace(
            workspace_path=workspace,
            agents=SimpleNamespace(defaults=SimpleNamespace(workspace=str(workspace))),
        ),
        session_manager=session_manager,
    )

    app = FastAPI()
    app.state.services = services
    app.state.user_store = None
    app.include_router(ws_module.router)

    with TestClient(app).websocket_connect("/ws/chat") as websocket:
        session_info = websocket.receive_json()
        assert session_info["type"] == "session_info"

        websocket.send_json({"type": "message", "content": "make report"})
        done_frame = websocket.receive_json()

    assert done_frame["type"] == "done"
    assert done_frame["content"] == "Here is the generated file"
    assert done_frame["attachments"] == [
        {
            "id": done_frame["attachments"][0]["id"],
            "name": "report.txt",
            "mime_type": "text/plain",
            "size": report.stat().st_size,
            "download_url": done_frame["attachments"][0]["download_url"],
        }
    ]


def test_assistant_session_messages_persist_attachments_for_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")
    _install_subagent_stub()
    ws_module = _load_ws_module()
    ws_module._ensure_message_tool_patched = lambda container: None

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.txt"
    report.write_text("file from workspace\n", encoding="utf-8")

    session_manager = _FakeSessionManager()
    services = SimpleNamespace(
        agent=_FakeAgent(
            ws_module,
            session_manager,
            {
                "content": "Here is the generated file",
                "media": [str(report)],
            },
        ),
        config=SimpleNamespace(
            workspace_path=workspace,
            agents=SimpleNamespace(defaults=SimpleNamespace(workspace=str(workspace))),
        ),
        session_manager=session_manager,
    )

    ws_app = FastAPI()
    ws_app.state.services = services
    ws_app.state.user_store = None
    ws_app.include_router(ws_module.router)

    with TestClient(ws_app).websocket_connect("/ws/chat") as websocket:
        session_info = websocket.receive_json()
        session_key = session_info["session_key"]
        websocket.send_json({"type": "message", "content": "make report"})
        done_frame = websocket.receive_json()

    assert done_frame["attachments"][0]["name"] == "report.txt"

    sessions_module = _load_sessions_route_module()
    sessions_app = FastAPI()
    sessions_app.state.services = services
    sessions_app.include_router(sessions_module.router, prefix="/api/sessions")

    history = TestClient(sessions_app).get(f"/api/sessions/{session_key}/messages")

    assert history.status_code == 200
    messages = history.json()
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["attachments"] == [
        {
            "id": done_frame["attachments"][0]["id"],
            "name": "report.txt",
            "mime_type": "text/plain",
            "size": report.stat().st_size,
            "download_url": done_frame["attachments"][0]["download_url"],
        }
    ]
