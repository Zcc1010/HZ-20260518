# -*- coding: utf-8 -*-
"""电网故障智能分析 API 路由"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.fault_analysis.service import FaultAnalysisService, APP_ID_FAULT_ANALYSIS

router = APIRouter()


def get_fault_analysis_service(svc: ServiceContainer) -> FaultAnalysisService:
    service = getattr(svc, "fault_analysis_service", None)
    if service is not None:
        service.initialize()
        service._schedule_queue()
        return service

    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    if workspace is None:
        workspace = Path.home() / ".nanobot"
    from webui.services.agentplayground.paths import default_app_root
    app_root = default_app_root(workspace, APP_ID_FAULT_ANALYSIS)
    service = FaultAnalysisService(app_root=app_root)
    service.initialize()
    service._schedule_queue()
    setattr(svc, "fault_analysis_app_root", str(service.app_root))
    setattr(svc, "fault_analysis_service", service)
    return service


class FaultAnalysisJobInfo(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    error_message: str | None = None
    station: str = ""
    device: str = ""
    device_type: str = ""
    voltage_level: str = ""
    folder_path: str = ""
    result_file_name: str | None = None
    download_url: str | None = None
    preview_url: str | None = None
    progress: int = 0
    progress_message: str | None = None
    evaluation: str | None = None


@router.get("/jobs", response_model=list[FaultAnalysisJobInfo])
async def list_fault_analysis_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[FaultAnalysisJobInfo]:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    return [FaultAnalysisJobInfo(**job) for job in service.list_jobs()]


@router.post("/jobs", response_model=FaultAnalysisJobInfo)
async def create_fault_analysis_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    files: list[UploadFile] = File(...),
    station: str = Form(...),
    device: str = Form(...),
    device_type: str = Form("线路"),
    voltage_level: str = Form("110kV"),
) -> FaultAnalysisJobInfo:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)

    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")

    try:
        job = service.create_job(
            files=files,
            station=station,
            device=device,
            device_type=device_type,
            voltage_level=voltage_level,
        )
        return FaultAnalysisJobInfo(**job)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=FaultAnalysisJobInfo)
async def get_fault_analysis_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> FaultAnalysisJobInfo:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return FaultAnalysisJobInfo(**job)


@router.patch("/jobs/{job_id}", response_model=FaultAnalysisJobInfo)
async def update_fault_analysis_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
    body: dict,
) -> FaultAnalysisJobInfo:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    evaluation = body.get("evaluation")
    if evaluation is not None:
        service.update_evaluation(job_id, evaluation)
        job["evaluation"] = evaluation

    return FaultAnalysisJobInfo(**job)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_fault_analysis_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> None:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    if not service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.get("/jobs/{job_id}/preview")
async def preview_fault_analysis_report(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    content = service.get_report_content(job_id)
    if content is None:
        raise HTTPException(status_code=404, detail="报告不存在或尚未生成")
    return {"content": content}


@router.get("/jobs/{job_id}/download")
async def download_fault_analysis_report(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
):
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    file_path = service.get_report_path(job_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")

    def iter_file():
        with open(file_path, "rb") as f:
            yield from f

    return StreamingResponse(
        iter_file(),
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename={file_path.name}"},
    )


@router.post("/jobs/export")
async def export_fault_analysis_reports(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: dict,
):
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    job_ids = body.get("job_ids", [])
    if not job_ids:
        raise HTTPException(status_code=400, detail="请选择要导出的任务")

    zip_buffer = service.export_jobs(job_ids)
    if zip_buffer is None:
        raise HTTPException(status_code=404, detail="没有可导出的报告")

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=fault_analysis_reports.zip"},
    )
