# -*- coding: utf-8 -*-
"""定值单解析 API 路由"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.setting_parser.service import SettingParserService, APP_ID_SETTING_PARSER

router = APIRouter()


def get_setting_parser_service(svc: ServiceContainer) -> SettingParserService:
    service = getattr(svc, "setting_parser_service", None)
    if service is not None:
        service.initialize()
        service._schedule_queue()
        return service

    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    if workspace is None:
        workspace = Path.home() / ".nanobot"
    from webui.services.agentplayground.paths import default_app_root
    app_root = default_app_root(workspace, APP_ID_SETTING_PARSER)
    service = SettingParserService(app_root=app_root)
    service.initialize()
    service._schedule_queue()
    setattr(svc, "setting_parser_app_root", str(service.app_root))
    setattr(svc, "setting_parser_service", service)
    return service


class SettingParserJobInfo(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    error_message: str | None = None
    folder_path: str = ""
    result_file_name: str | None = None
    download_url: str | None = None
    preview_url: str | None = None
    progress: int = 0
    progress_message: str | None = None


@router.get("/jobs", response_model=list[SettingParserJobInfo])
async def list_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[SettingParserJobInfo]:
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    return [SettingParserJobInfo(**job) for job in service.list_jobs()]


@router.post("/jobs", response_model=SettingParserJobInfo)
async def create_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    files: list[UploadFile] = File(...),
) -> SettingParserJobInfo:
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")
    try:
        job = service.create_job(files=files)
        return SettingParserJobInfo(**job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=SettingParserJobInfo)
async def get_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> SettingParserJobInfo:
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return SettingParserJobInfo(**job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> None:
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/jobs/{job_id}/preview")
async def preview_result(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    content = service.get_report_content(job_id)
    if content is None:
        raise HTTPException(status_code=404, detail="结果不存在或尚未生成")
    return {"content": content}


@router.get("/jobs/{job_id}/download")
async def download_result(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
):
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    file_path = service.get_report_path(job_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")

    def iter_file():
        with open(file_path, "rb") as f:
            yield from f

    encoded_name = quote(file_path.name)
    media = "application/json" if file_path.suffix == ".json" else "text/markdown"
    return StreamingResponse(
        iter_file(),
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.post("/jobs/export")
async def export_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: dict,
):
    ensure_agentplayground_enabled()
    service = get_setting_parser_service(svc)
    job_ids = body.get("job_ids", [])
    if not job_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的任务")
    zip_buffer = service.export_jobs(job_ids)
    if zip_buffer is None:
        raise HTTPException(status_code=404, detail="没有可导出的结果")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=setting_parser_results.zip"},
    )
