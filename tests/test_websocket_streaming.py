import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _load_ws_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "webui" / "api" / "routes" / "ws.py"
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    spec = importlib.util.spec_from_file_location("test_ws_stream_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _install_subagent_stub():
    stub = types.ModuleType("webui.patches.subagent")
    stub.register_progress = lambda *args, **kwargs: None
    stub.register_announce = lambda *args, **kwargs: None
    stub.register_save_turn = lambda *args, **kwargs: None
    sys.modules["webui.patches.subagent"] = stub


class _FakeSession:
    def __init__(self):
        self.messages = []
        self.updated_at = None

    def add_message(self, role, content):
        self.messages.append({"role": role, "content": content, "timestamp": "2026-04-14T12:00:00"})


class _FakeSessionManager:
    def __init__(self):
        self._sessions = {}

    def get_or_create(self, key):
        if key not in self._sessions:
            self._sessions[key] = _FakeSession()
        return self._sessions[key]

    def save(self, session):
        return None


class _SpyAgent:
    def __init__(self):
        self.sessions = _FakeSessionManager()
        self.last_on_stream = None
        self.last_on_stream_end = None

    async def process_direct(
        self,
        msg,
        session_key=None,
        channel=None,
        chat_id=None,
        on_progress=None,
        on_stream=None,
        on_stream_end=None,
    ):
        self.last_on_stream = on_stream
        self.last_on_stream_end = on_stream_end
        session = self.sessions.get_or_create(session_key)
        session.add_message("user", msg)
        session.messages.append({
            "role": "assistant",
            "content": "Plain reply",
            "timestamp": "2026-04-14T12:00:01",
        })
        return "Plain reply"


def _build_app(agent):
    ws_module = _load_ws_module()
    ws_module._ensure_message_tool_patched = lambda container: None
    services = SimpleNamespace(
        agent=agent,
        config=SimpleNamespace(
            workspace_path=Path("/tmp"),
            agents=SimpleNamespace(defaults=SimpleNamespace(workspace="/tmp")),
        ),
    )
    app = FastAPI()
    app.state.services = services
    app.state.user_store = None
    app.include_router(ws_module.router)
    return app, ws_module


def test_websocket_route_passes_stream_callbacks_into_agent(monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")
    _install_subagent_stub()
    agent = _SpyAgent()
    app, _ = _build_app(agent)

    with TestClient(app).websocket_connect("/ws/chat") as websocket:
        session_info = websocket.receive_json()
        session_key = session_info["session_key"]
        websocket.send_json({"type": "message", "content": "plain"})
        done_frame = websocket.receive_json()

    assert done_frame == {
        "type": "done",
        "content": "Plain reply",
        "attachments": [],
        "session_key": session_key,
    }
    assert agent.last_on_stream is not None
    assert agent.last_on_stream_end is not None


def test_stream_event_emitter_emits_start_delta_end_frames(monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")
    _install_subagent_stub()
    _, ws_module = _build_app(_SpyAgent())

    sent = []

    async def _send_json(payload):
        sent.append(payload)

    emitter = ws_module._StreamEventEmitter(_send_json, "web:test:abc")

    asyncio.run(emitter.delta("Hello"))
    asyncio.run(emitter.delta(" world"))
    asyncio.run(emitter.end(resuming=False))

    assert sent == [
        {"type": "stream_start", "session_key": "web:test:abc"},
        {"type": "stream_delta", "content": "Hello", "session_key": "web:test:abc"},
        {"type": "stream_delta", "content": " world", "session_key": "web:test:abc"},
        {"type": "stream_end", "session_key": "web:test:abc", "resuming": False},
    ]


def test_stream_event_emitter_skips_empty_deltas(monkeypatch):
    monkeypatch.setenv("WEBUI_AUTH_DISABLED", "true")
    _install_subagent_stub()
    _, ws_module = _build_app(_SpyAgent())

    sent = []

    async def _send_json(payload):
        sent.append(payload)

    emitter = ws_module._StreamEventEmitter(_send_json, "web:test:abc")

    asyncio.run(emitter.delta(""))
    asyncio.run(emitter.end(resuming=True))

    assert sent == []
