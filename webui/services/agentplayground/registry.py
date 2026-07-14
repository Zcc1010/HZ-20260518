from __future__ import annotations

from webui.services.agentplayground.models import AgentPlaygroundApp


_REGISTERED_APPS: tuple[AgentPlaygroundApp, ...] = ()


def list_registered_apps() -> list[AgentPlaygroundApp]:
    return list(_REGISTERED_APPS)


def get_registered_app(app_id: str) -> AgentPlaygroundApp | None:
    for app in _REGISTERED_APPS:
        if app.id == app_id:
            return app
    return None
