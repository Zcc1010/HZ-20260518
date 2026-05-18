from __future__ import annotations

from webui.services.agentplayground.models import APP_ID_G_FILE_COMPARE, AgentPlaygroundApp


_REGISTERED_APPS = (
    AgentPlaygroundApp(
        id=APP_ID_G_FILE_COMPARE,
        name="G 文件对比",
        description="上传 D5000 与新一代文件，生成可下载的对比报告。",
    ),
)


def list_registered_apps() -> list[AgentPlaygroundApp]:
    return list(_REGISTERED_APPS)


def get_registered_app(app_id: str) -> AgentPlaygroundApp | None:
    for app in _REGISTERED_APPS:
        if app.id == app_id:
            return app
    return None
