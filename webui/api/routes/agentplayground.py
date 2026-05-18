from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from webui.api.auth import is_authless_mode
from webui.api.models import AgentPlaygroundAppInfo
from webui.services.agentplayground.registry import list_registered_apps

router = APIRouter()


def ensure_agentplayground_enabled() -> None:
    # if not is_authless_mode():
    #     raise HTTPException(
    #         status.HTTP_404_NOT_FOUND,
    #         "Agent playground is available only when WEBUI_AUTH_DISABLED is enabled",
    #     )
    pass


@router.get("/apps", response_model=list[AgentPlaygroundAppInfo])
async def list_apps() -> list[AgentPlaygroundAppInfo]:
    ensure_agentplayground_enabled()
    return [AgentPlaygroundAppInfo(**app.to_dict()) for app in list_registered_apps()]
