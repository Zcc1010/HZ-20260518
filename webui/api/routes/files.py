"""Anonymous workspace file download routes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from webui.api.deps import get_services
from webui.api.files import find_attachment_by_token, resolve_attachment_download_path
from webui.api.gateway import ServiceContainer

router = APIRouter()


def _resolve_agentplayground_attachment(svc: ServiceContainer, token: str) -> dict | None:
    # Try wave record parser first
    wrp_service = getattr(svc, "wave_record_parser_service", None)
    if wrp_service is None:
        try:
            from webui.api.routes.wave_record_parser import get_wave_record_parser_service
            wrp_service = get_wave_record_parser_service(svc)
        except Exception:
            wrp_service = None

    if wrp_service is not None:
        find_result_attachment = getattr(wrp_service, "find_result_attachment", None)
        if find_result_attachment is not None:
            result = find_result_attachment(token)
            if result is not None:
                return result

    # Try setting check
    sc_service = getattr(svc, "setting_check_service", None)
    if sc_service is None:
        try:
            from webui.api.routes.setting_check import get_setting_check_service
            sc_service = get_setting_check_service(svc)
        except Exception:
            sc_service = None

    if sc_service is not None:
        find_result_attachment = getattr(sc_service, "find_result_attachment", None)
        if find_result_attachment is not None:
            result = find_result_attachment(token)
            if result is not None:
                return result

    # Try g-file-compare
    service = getattr(svc, "g_file_compare_service", None)
    if service is None:
        try:
            from webui.api.routes.g_file_compare import get_g_file_compare_service
        except Exception:
            return None
        service = get_g_file_compare_service(svc)

    find_result_attachment = getattr(service, "find_result_attachment", None)
    if find_result_attachment is None:
        return None
    return find_result_attachment(token)


@router.get("/d/{token}")
async def download_file(
    token: str,
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> FileResponse:
    attachment = find_attachment_by_token(svc.session_manager, token)
    if attachment is None:
        attachment = _resolve_agentplayground_attachment(svc, token)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")

    workspace = Path(attachment.get("_download_root") or svc.config.agents.defaults.workspace).expanduser()
    try:
        file_path = resolve_attachment_download_path(workspace, attachment)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    return FileResponse(
        path=file_path,
        filename=attachment.get("name") or file_path.name,
        media_type=attachment.get("mime_type") or None,
    )
