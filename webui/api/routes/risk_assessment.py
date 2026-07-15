# -*- coding: utf-8 -*-
"""运行风险评估 API 路由"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.risk_assessment.service import RiskAssessmentService, APP_ID_RISK_ASSESSMENT

router = APIRouter()


def get_risk_assessment_service(svc: ServiceContainer) -> RiskAssessmentService:
    service = getattr(svc, "risk_assessment_ui_service", None)
    if service is not None:
        service.initialize()
        service._schedule_queue()
        return service

    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    if workspace is None:
        workspace = Path.home() / ".nanobot"
    from webui.services.agentplayground.paths import default_app_root
    app_root = default_app_root(workspace, APP_ID_RISK_ASSESSMENT)
    service = RiskAssessmentService(app_root=app_root)
    service.initialize()
    service._schedule_queue()
    setattr(svc, "risk_assessment_app_root", str(service.app_root))
    setattr(svc, "risk_assessment_ui_service", service)
    return service


class RiskAssessmentJobInfo(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    error_message: str | None = None
    station: str = ""
    folder_path: str = ""
    result_file_name: str | None = None
    download_url: str | None = None
    preview_url: str | None = None
    progress: int = 0
    progress_message: str | None = None


@router.get("/jobs", response_model=list[RiskAssessmentJobInfo])
async def list_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[RiskAssessmentJobInfo]:
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    return [RiskAssessmentJobInfo(**job) for job in service.list_jobs()]


@router.post("/jobs", response_model=RiskAssessmentJobInfo)
async def create_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    files: list[UploadFile] = File(...),
    station: str = Form(""),
) -> RiskAssessmentJobInfo:
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")
    try:
        job = service.create_job(files=files, station=station)
        return RiskAssessmentJobInfo(**job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=RiskAssessmentJobInfo)
async def get_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> RiskAssessmentJobInfo:
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return RiskAssessmentJobInfo(**job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> None:
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/jobs/{job_id}/preview")
async def preview_result(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    content = service.get_report_content(job_id)
    if content is None:
        raise HTTPException(status_code=404, detail="报告不存在或尚未生成")
    return {"content": content}


@router.get("/jobs/{job_id}/download")
async def download_result(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
):
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    file_path = service.get_report_path(job_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")

    def iter_file():
        with open(file_path, "rb") as f:
            yield from f

    encoded_name = quote(file_path.name)
    return StreamingResponse(
        iter_file(),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


@router.post("/jobs/export")
async def export_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: dict,
):
    ensure_agentplayground_enabled()
    service = get_risk_assessment_service(svc)
    job_ids = body.get("job_ids", [])
    if not job_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的任务")
    zip_buffer = service.export_jobs(job_ids)
    if zip_buffer is None:
        raise HTTPException(status_code=404, detail="没有可导出的报告")
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=risk_assessment_reports.zip"},
    )
