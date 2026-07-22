# -*- coding: utf-8 -*-
"""电网故障智能分析 API 路由"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.fault_analysis.service import FaultAnalysisService, APP_ID_FAULT_ANALYSIS

router = APIRouter()


class InitUploadRequest(BaseModel):
    file_name: str
    total_size: int
    total_chunks: int


class CompleteUploadRequest(BaseModel):
    station: str = ""
    device: str = ""
    device_type: str = "线路"
    voltage_level: str = "110kV"
    external_id: str = ""


class DownloadByIdRequest(BaseModel):
    cookie: str = ""
    equipmentName: str = ""


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
    external_id: str = ""


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
    station: str = Form(""),
    device: str = Form(""),
    device_type: str = Form(""),
    voltage_level: str = Form(""),
    external_id: str = Form(""),
) -> FaultAnalysisJobInfo:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)

    if not files:
        raise HTTPException(status_code=400, detail="请上传至少一个文件")

    try:
        job = await service.create_job(
            files=files,
            station=station,
            device=device,
            device_type=device_type,
            voltage_level=voltage_level,
            external_id=external_id,
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


@router.post("/jobs/{job_id}/rerun", response_model=FaultAnalysisJobInfo)
async def rerun_fault_analysis_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> FaultAnalysisJobInfo:
    """重新运行已有任务的分析流水线（使用已上传的文件）。"""
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    try:
        job = await service.rerun_job(job_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return FaultAnalysisJobInfo(**job)


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

    encoded_name = quote(file_path.name)
    return StreamingResponse(
        iter_file(),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
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


# ── 分块上传端点 ──


@router.post("/uploads/init")
async def init_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: InitUploadRequest,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    return service.chunked_upload.init_upload(
        file_name=body.file_name,
        total_size=body.total_size,
        total_chunks=body.total_chunks,
    )


@router.post("/uploads/{upload_id}/chunks/{chunk_index}")
async def upload_chunk(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    upload_id: str,
    chunk_index: int,
    chunk: Annotated[UploadFile, File()],
) -> dict:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    data = await chunk.read()
    return service.chunked_upload.save_chunk(upload_id, chunk_index, data)


@router.post("/uploads/{upload_id}/complete", response_model=FaultAnalysisJobInfo)
async def complete_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    upload_id: str,
    body: CompleteUploadRequest,
) -> FaultAnalysisJobInfo:
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    try:
        job = await service.create_job_from_chunked_upload(
            upload_id=upload_id,
            station=body.station,
            device=body.device,
            device_type=body.device_type,
            voltage_level=body.voltage_level,
            external_id=body.external_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return FaultAnalysisJobInfo(**job)


# ── 外部ID查询 ──


@router.get("/jobs/by-external-id/{external_id}", response_model=FaultAnalysisJobInfo)
async def get_job_by_external_id(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    external_id: str,
) -> FaultAnalysisJobInfo:
    """通过外部系统 ID 查询任务。"""
    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)
    job = service.get_job_by_external_id(external_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return FaultAnalysisJobInfo(**job)


# ── 数据平台下载录波文件 ──


@router.post("/jobs/download-by-id/{event_id}", response_model=FaultAnalysisJobInfo)
async def download_and_create_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    event_id: str,
    body: DownloadByIdRequest,
) -> FaultAnalysisJobInfo:
    """通过故障事件ID下载录波文件并创建任务。"""
    from webui.services.wave_record_parser.downloader import EventDownloader
    from webui.services.wave_record_parser.service import parse_fault_event_md

    ensure_agentplayground_enabled()
    service = get_fault_analysis_service(svc)

    # 先检查是否已存在该 event_id 的任务
    existing = service.get_job_by_external_id(event_id)
    if existing is not None:
        return FaultAnalysisJobInfo(**existing)

    cookie = body.cookie if body else ""
    equipment_name_param = body.equipmentName if body else ""

    def _download_and_create():
        downloader = EventDownloader(cookie=cookie)
        with tempfile.TemporaryDirectory(prefix="fault_download_") as tmp_dir:
            save_dir = downloader.download_event(event_id, tmp_dir)
            # 从 _故障事件信息.md 提取装置名称
            equipment_name = ""
            for f in Path(save_dir).rglob("*.md"):
                if "故障事件" in f.name:
                    meta = parse_fault_event_md(f)
                    equipment_name = (
                        meta.get("equipmentName", "")
                        or meta.get("设备名称", "")
                        or meta.get("装置名称", "")
                    )
                    break
            # 如果 md 文件中没有提取到，使用前端传入的 equipmentName
            if not equipment_name and equipment_name_param:
                equipment_name = equipment_name_param
            # 检查下载目录是否有文件
            if not any(Path(save_dir).iterdir()):
                raise FileNotFoundError("下载目录中没有找到文件")

            # 创建 job 目录结构
            import uuid as _uuid
            job_id = _uuid.uuid4().hex[:12]
            job_dir = service.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            input_dir = job_dir / "input"
            input_dir.mkdir(exist_ok=True)

            # 保留目录结构复制到 input 目录（不拍平，保持 保护录波/故障录波 等子目录）
            for item in Path(save_dir).iterdir():
                if item.is_dir():
                    shutil.copytree(str(item), str(input_dir / item.name))
                else:
                    shutil.copy2(str(item), str(input_dir / item.name))

            # 写入 DB（device_type/voltage_level 留空，由 parse_folder_name 自动推断）
            from webui.services.agentplayground.db import utcnow_iso
            now = utcnow_iso()
            with service._conn() as conn:
                conn.execute(
                    """INSERT INTO jobs (id, status, created_at, updated_at, station, device, device_type, voltage_level, folder_path, external_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (job_id, "processing", now, now,
                     equipment_name, equipment_name, "", "",
                     str(input_dir), event_id),
                )

            return service.get_job(job_id), job_id, input_dir

    try:
        job, job_id, input_dir = await asyncio.to_thread(_download_and_create)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {e}")

    # 启动后台分析任务（device_type/voltage_level 留空，由 pipeline 自动推断）
    asyncio.create_task(service._run_analysis(job_id, input_dir, "", ""))

    return FaultAnalysisJobInfo(**job)
