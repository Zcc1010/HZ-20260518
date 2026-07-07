# -*- coding: utf-8 -*-
"""定值校核 API 路由"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.setting_check.service import SettingCheckService, APP_ID_SETTING_CHECK

router = APIRouter()


def get_setting_check_service(svc: ServiceContainer) -> SettingCheckService:
    service = getattr(svc, "setting_check_service", None)
    if service is not None:
        service.initialize()
        service._schedule_queue()
        return service

    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    if workspace is None:
        # Use default home directory if workspace not configured
        workspace = Path.home() / ".nanobot"
    from webui.services.agentplayground.paths import default_setting_check_app_root
    app_root = default_setting_check_app_root(workspace)
    service = SettingCheckService(app_root=app_root)
    service.initialize()
    service._schedule_queue()
    setattr(svc, "setting_check_app_root", str(service.app_root))
    setattr(svc, "setting_check_service", service)
    return service


class SettingCheckJobInfo(BaseModel):
    id: str
    status: str
    created_at: str
    updated_at: str
    error_message: str | None = None
    station: str = ""
    device: str = ""
    setting_files: list[str] = []
    calc_file: str = ""
    result_file_name: str | None = None
    download_url: str | None = None
    preview_url: str | None = None
    progress: int = 0
    progress_message: str = ""
    evaluation: str = ""


@router.get("/jobs", response_model=list[SettingCheckJobInfo])
async def list_setting_check_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[SettingCheckJobInfo]:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    return [SettingCheckJobInfo(**job) for job in service.list_jobs()]


class InitUploadRequest(BaseModel):
    file_name: str
    total_size: int
    total_chunks: int


@router.post("/uploads/init")
async def init_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: InitUploadRequest,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
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
    service = get_setting_check_service(svc)
    data = await chunk.read()
    return service.chunked_upload.save_chunk(upload_id, chunk_index, data)


class CompleteUploadRequest(BaseModel):
    station: str = ""
    device: str = ""
    setting_upload_ids: list[str] = []
    calc_upload_ids: list[str] = []
    manual_upload_ids: list[str] = []


class CompleteZipUploadRequest(BaseModel):
    station: str = ""
    device: str = ""
    zip_upload_id: str = ""


@router.post("/uploads/complete-zip", response_model=SettingCheckJobInfo)
async def complete_zip_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: CompleteZipUploadRequest,
) -> SettingCheckJobInfo:
    """Complete upload from a single zip file containing 定值单/ and 计算书/ directories."""
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = await service.create_job_from_zip_upload(
        zip_upload_id=body.zip_upload_id,
        station=body.station,
        device=body.device,
        created_by="authless-public",
        run_in_background=True,
    )
    return SettingCheckJobInfo(**job)


@router.post("/uploads/complete", response_model=SettingCheckJobInfo)
async def complete_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: CompleteUploadRequest,
) -> SettingCheckJobInfo:
    """Complete upload from multiple setting files, calc files, and manual files."""
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = await service.create_job_from_chunked_uploads(
        setting_upload_ids=body.setting_upload_ids,
        calc_upload_ids=body.calc_upload_ids,
        manual_upload_ids=body.manual_upload_ids,
        station=body.station,
        device=body.device,
        created_by="authless-public",
        run_in_background=True,
    )
    return SettingCheckJobInfo(**job)


class UpdateJobRequest(BaseModel):
    evaluation: str = ""


@router.patch("/jobs/{job_id}", response_model=SettingCheckJobInfo)
async def update_setting_check_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
    body: UpdateJobRequest,
) -> SettingCheckJobInfo:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = service.update_job_evaluation(job_id, body.evaluation)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return SettingCheckJobInfo(**job)


@router.delete("/jobs/{job_id}")
async def delete_setting_check_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    ok = service.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


@router.get("/jobs/{job_id}", response_model=SettingCheckJobInfo)
async def get_setting_check_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> SettingCheckJobInfo:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return SettingCheckJobInfo(**job)


class CopyToWorkspaceRequest(BaseModel):
    workspace: str


@router.post("/jobs/{job_id}/copy-to-workspace")
async def copy_job_to_workspace(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
    body: CopyToWorkspaceRequest,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    job_root = service.app_root / "jobs" / job_id
    if not job_root.exists():
        raise HTTPException(status_code=404, detail="Job directory not found")

    # Workspace root: ~/.nanobot/agentplayground/setting-check/workspace/
    workspace_root = Path.home() / ".nanobot" / "agentplayground" / "setting-check" / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    # Create workspace directory directly
    ws_dir = workspace_root / body.workspace
    ws_dir.mkdir(parents=True, exist_ok=True)

    # Read manifest to classify files
    manifest_path = job_root / "inputs.json"
    setting_names: set[str] = set()
    calc_names: set[str] = set()
    manual_names: set[str] = set()
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        setting_names = set(manifest.get("setting_files", []))
        calc_names = set(manifest.get("calc_files", []))
        if not calc_names and manifest.get("calc_file"):
            calc_names = {manifest["calc_file"]}
        manual_names = set(manifest.get("manual_files", []))

    # Create category directories in workspace
    for category in ["定值单", "计算书", "说明书", "报告"]:
        (ws_dir / category).mkdir(parents=True, exist_ok=True)

    # Copy input files to categorized subdirectories
    inputs_dir = job_root / "inputs"
    if inputs_dir.exists():
        for item in inputs_dir.iterdir():
            if not item.is_file():
                continue
            name = item.name
            if name in setting_names:
                dest = ws_dir / "定值单" / name
            elif name in calc_names:
                dest = ws_dir / "计算书" / name
            elif name in manual_names:
                dest = ws_dir / "说明书" / name
            else:
                # Fallback: classify by extension/content
                name_lower = name.lower()
                if any(kw in name_lower for kw in ["定值单", "setting"]):
                    dest = ws_dir / "定值单" / name
                elif any(kw in name_lower for kw in ["计算书", "计算", "整定", "calc"]):
                    dest = ws_dir / "计算书" / name
                elif any(kw in name_lower for kw in ["说明书", "说明", "manual"]):
                    dest = ws_dir / "说明书" / name
                else:
                    dest = ws_dir / "定值单" / name
            shutil.copy2(str(item), str(dest))

    # Copy report files from output directory
    output_dir = job_root / "output"
    if output_dir.exists():
        for item in output_dir.rglob("*"):
            if item.is_file() and item.suffix.lower() in ('.md', '.docx', '.pdf'):
                dest = ws_dir / "报告" / item.name
                shutil.copy2(str(item), str(dest))

    return {"ok": True, "workspace": body.workspace}


@router.get("/jobs/{job_id}/files/{file_name}")
async def get_setting_check_file(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
    file_name: str,
) -> dict:
    """获取定值校核任务的定值单文件内容"""
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    content = service.get_input_file_content(job_id, file_name)
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"name": file_name, "content": content}


class ExportJobsRequest(BaseModel):
    job_ids: list[str]


@router.post("/jobs/export")
async def export_setting_check_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: ExportJobsRequest,
) -> StreamingResponse:
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    files = service.get_export_files(body.job_ids)
    if not files:
        raise HTTPException(status_code=404, detail="No exportable files found")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for file_path, display_name in files:
            name = display_name
            counter = 1
            while name in used_names:
                stem = Path(display_name).stem
                suffix = Path(display_name).suffix
                name = f"{stem}_{counter}{suffix}"
                counter += 1
            used_names.add(name)
            zf.write(file_path, name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="setting_check_reports.zip"'},
    )


@router.get("/jobs/{job_id}/preview")
async def preview_setting_check_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    """返回已完成任务的 Markdown 报告内容，用于浏览器内预览。"""
    ensure_agentplayground_enabled()
    service = get_setting_check_service(svc)
    job = service.get_job(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Job not found or not completed")

    # 在 job output 目录中查找 .md 文件
    job_root = service.app_root / "jobs" / job_id / "output"
    md_files = list(job_root.rglob("*定值校核报告.md")) + list(job_root.rglob("*.md"))
    if not md_files:
        raise HTTPException(status_code=404, detail="Preview not available")

    content = md_files[0].read_text(encoding="utf-8")
    return {"content": content}