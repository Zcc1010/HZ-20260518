from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Callable

from starlette.responses import RedirectResponse


DEFAULT_WEBUI_BASE_PATH = "/protection/"


def normalize_base_path(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw or raw == "/":
        return "/"
    trimmed = raw.strip("/")
    if not trimmed:
        return "/"
    return f"/{trimmed}/"


def get_webui_base_path() -> str:
    return normalize_base_path(os.getenv("WEBUI_BASE_PATH", DEFAULT_WEBUI_BASE_PATH))


class BasePathMiddleware:
    def __init__(
        self,
        app,
        base_path: str | Iterable[str] | None = None,
        authless_only_base_paths: dict[str, str] | None = None,
    ):
        self.app = app
        raw_paths = [base_path] if isinstance(base_path, str) or base_path is None else list(base_path)
        self.base_paths = []
        for raw_path in raw_paths:
            normalized = normalize_base_path(raw_path)
            if normalized != "/" and normalized not in self.base_paths:
                self.base_paths.append(normalized)
        self.base_paths.sort(key=len, reverse=True)
        self.base_path = self.base_paths[0] if self.base_paths else "/"
        self.base_prefix = self.base_path.rstrip("/")
        self.authless_only_prefixes = {
            normalize_base_path(path).rstrip("/"): redirect_to
            for path, redirect_to in (authless_only_base_paths or {}).items()
        }

    async def __call__(self, scope, receive: Callable, send: Callable):
        if not self.base_paths or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        for base_path in self.base_paths:
            base_prefix = base_path.rstrip("/")
            if path != base_prefix and not path.startswith(f"{base_prefix}/"):
                continue

            if scope["type"] == "http" and base_prefix in self.authless_only_prefixes:
                from webui.api.auth import is_authless_mode

                if not is_authless_mode():
                    response = RedirectResponse(
                        url=self.authless_only_prefixes[base_prefix],
                        status_code=307,
                    )
                    await response(scope, receive, send)
                    return

            if scope["type"] == "http" and path == base_prefix:
                response = RedirectResponse(url=f"{base_prefix}/", status_code=307)
                await response(scope, receive, send)
                return

            updated_scope = dict(scope)
            stripped = path[len(base_prefix) :]
            updated_scope["path"] = stripped or "/"
            raw_path = scope.get("raw_path")
            if isinstance(raw_path, (bytes, bytearray)):
                raw_prefix = base_prefix.encode()
                if raw_path == raw_prefix or raw_path.startswith(raw_prefix + b"/"):
                    updated_scope["raw_path"] = raw_path[len(raw_prefix) :] or b"/"
            await self.app(updated_scope, receive, send)
            return

        await self.app(scope, receive, send)
