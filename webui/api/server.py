"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from webui.api.base_path import BasePathMiddleware, get_webui_base_path
from webui.api.gateway import ServiceContainer
from webui.api.middleware import setup_cors
from webui.api.users import UserStore


def _resolve_web_dist() -> Path:
    """Resolve the bundled frontend dist directory when available."""
    # Resolution order:
    #   1. Editable install: <repo>/webui/web/dist/
    #   2. Installed wheel:  importlib.resources traversal (works with zipimport too)
    _here = Path(__file__).parent  # webui/api/
    web_dist = _here.parent / "web" / "dist"  # editable: webui/web/dist
    if web_dist.exists():
        return web_dist

    try:
        import importlib.resources as _ir

        _traversable = _ir.files("webui").joinpath("web/dist")
        _candidate = Path(str(_traversable))
        if _candidate.exists():
            return _candidate

        import tempfile

        _tmp = Path(tempfile.mkdtemp(prefix="nanobot_webui_dist_"))
        for _item in _traversable.iterdir():  # type: ignore[union-attr]
            _dest = _tmp / _item.name
            if hasattr(_item, "read_bytes"):
                _dest.write_bytes(_item.read_bytes())
        return _tmp
    except Exception:
        return Path("")


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="nanobot WebUI",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        BasePathMiddleware,
        base_path=[get_webui_base_path(), "/agentplayground/"],
    )

    # Attach shared state
    app.state.services = container
    app.state.user_store = UserStore()

    # Middleware
    setup_cors(app)

    # Routes
    from webui.api.routes import (
        agentplayground,
        auth,
        channels,
        chat_feedback,
        config,
        cron,
        files,
        g_file_compare,
        mcp,
        openai_proxy,
        providers,
        sessions,
        setting_check,
        setting_check_v2,
        skills,
        users,
        wave_record_parser,
        workspace,
        ws,
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(config.router, prefix="/api/config", tags=["config"])
    app.include_router(agentplayground.router, prefix="/api/agentplayground", tags=["agentplayground"])
    app.include_router(channels.router, prefix="/api/channels", tags=["channels"])
    app.include_router(providers.router, prefix="/api/providers", tags=["providers"])
    app.include_router(mcp.router, prefix="/api/mcp", tags=["mcp"])
    app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
    app.include_router(files.router, prefix="/api/files", tags=["files"])
    app.include_router(g_file_compare.router, prefix="/api/g-file-compare", tags=["g-file-compare"])
    app.include_router(wave_record_parser.router, prefix="/api/wave-record-parser", tags=["wave-record-parser"])
    app.include_router(setting_check.router, prefix="/api/setting-check", tags=["setting-check"])
    app.include_router(setting_check_v2.router, prefix="/api/setting-check-v2", tags=["setting-check-v2"])
    app.include_router(cron.router, prefix="/api/cron", tags=["cron"])
    app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(workspace.router, prefix="/api/workspace", tags=["workspace"])
    app.include_router(chat_feedback.router, prefix="/api/chat", tags=["chat-feedback"])
    app.include_router(ws.router, tags=["ws"])
    app.include_router(openai_proxy.router)

    # Serve built React frontend (optional — only when `npm run build` has been run)
    web_dist = _resolve_web_dist()

    if web_dist.exists():
        app.mount("/dist", StaticFiles(directory=str(web_dist)), name="dist-root")

        for _static_dir in web_dist.iterdir():
            if _static_dir.is_dir():
                app.mount(
                    f"/{_static_dir.name}",
                    StaticFiles(directory=str(_static_dir)),
                    name=f"static-{_static_dir.name}",
                )

        for _static_file in web_dist.iterdir():
            if _static_file.is_file() and _static_file.name != "index.html":
                _name = _static_file.name
                _path = str(_static_file)

                @app.get(f"/{_name}", include_in_schema=False)
                async def _serve_public(  # noqa: B023
                    _f: str = _path,
                ) -> FileResponse:
                    return FileResponse(_f)

        index_html = web_dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):  # noqa: ARG001
            if index_html.exists():
                return FileResponse(str(index_html))
            return {"message": "Frontend not built. Run 'bun run build' in webui/web/"}

    return app
