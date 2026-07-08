from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.models import WaveRecordJobInfo
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.agentplayground.db import connect
from webui.services.agentplayground.paths import default_wave_record_parser_app_root
from webui.services.wave_record_parser.service import WaveRecordParserService

router = APIRouter()


def _workspace_from_services(svc: ServiceContainer) -> Path:
    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    return Path(workspace).expanduser().resolve()


def get_wave_record_parser_service(svc: ServiceContainer) -> WaveRecordParserService:
    service = getattr(svc, "wave_record_parser_service", None)
    if service is not None:
        service.initialize()
        service.start_queue()
        return service

    workspace = _workspace_from_services(svc)
    app_root = getattr(svc, "wave_record_parser_app_root", None) or default_wave_record_parser_app_root(workspace)
    service = WaveRecordParserService(app_root=app_root)
    service.initialize()
    service.start_queue()
    setattr(svc, "wave_record_parser_app_root", str(service.app_root))
    setattr(svc, "wave_record_parser_service", service)
    return service


@router.get("/jobs", response_model=list[WaveRecordJobInfo])
async def list_wave_record_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[WaveRecordJobInfo]:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    return [WaveRecordJobInfo(**job) for job in service.list_jobs()]


@router.post("/jobs", response_model=WaveRecordJobInfo)
async def create_wave_record_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    files: Annotated[list[UploadFile], File()],
    station: Annotated[str, Form()] = "",
    device: Annotated[str, Form()] = "",
    device_type: Annotated[str, Form()] = "line",
) -> WaveRecordJobInfo:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    created_by = "authless-public"
    job = await service.create_job_from_uploads(
        files=files,
        station=station,
        device=device,
        device_type=device_type,
        created_by=created_by,
        run_in_background=True,
    )
    return WaveRecordJobInfo(**job)


class InitUploadRequest(BaseModel):
    file_name: str
    total_size: int
    total_chunks: int


class CompleteUploadRequest(BaseModel):
    station: str = ""
    device: str = ""
    device_type: str = "line"
    external_id: str = ""


class DownloadByIdRequest(BaseModel):
    cookie: str = ""


class UpdateWaveRecordJobRequest(BaseModel):
    evaluation: str = ""
    station: str = ""
    device: str = ""


class ExportJobsRequest(BaseModel):
    job_ids: list[str]


@router.post("/uploads/init")
async def init_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: InitUploadRequest,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
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
    service = get_wave_record_parser_service(svc)
    data = await chunk.read()
    return service.chunked_upload.save_chunk(upload_id, chunk_index, data)


@router.post("/uploads/{upload_id}/complete", response_model=WaveRecordJobInfo)
async def complete_chunked_upload(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    upload_id: str,
    body: CompleteUploadRequest,
) -> WaveRecordJobInfo:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    job = await service.create_job_from_chunked_upload(
        upload_id=upload_id,
        station=body.station,
        device=body.device,
        device_type=body.device_type,
        created_by="authless-public",
        run_in_background=True,
    )
    # 如果请求中带有 external_id，更新任务
    if body.external_id:
        with connect(service.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET external_id = ? WHERE id = ?",
                (body.external_id, job["id"]),
            )
        job["external_id"] = body.external_id
    return WaveRecordJobInfo(**job)


@router.post("/jobs/export")
async def export_wave_record_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: ExportJobsRequest,
) -> StreamingResponse:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
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
        headers={"Content-Disposition": 'attachment; filename="trip_briefings.zip"'},
    )


@router.get("/jobs/search")
async def search_wave_record_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    station: str = "",
) -> list[dict]:
    """按 station 关键词搜索跳闸简报任务。"""
    ensure_agentplayground_enabled()
    if not station.strip():
        return []
    service = get_wave_record_parser_service(svc)
    return service.search_jobs(station.strip())


@router.get("/jobs/by-external-id/{external_id}", response_model=WaveRecordJobInfo)
async def get_job_by_external_id(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    external_id: str,
) -> WaveRecordJobInfo:
    """通过外部系统 ID 查询任务。"""
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    job = service.get_job_by_external_id(external_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return WaveRecordJobInfo(**job)


class CreateFromDirectoryRequest(BaseModel):
    dir_path: str
    station: str = ""
    device: str = ""
    device_type: str = "line"


@router.post("/jobs/from-directory", response_model=WaveRecordJobInfo)
async def create_job_from_directory(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: CreateFromDirectoryRequest,
) -> WaveRecordJobInfo:
    """从本地目录创建任务，自动读取 _故障事件信息.md 提取元数据。"""
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    try:
        job = service.create_job_from_directory(
            dir_path=body.dir_path,
            station=body.station,
            device=body.device,
            device_type=body.device_type,
            created_by="authless-public",
            run_in_background=True,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return WaveRecordJobInfo(**job)


@router.post("/jobs/download-by-id/{event_id}", response_model=WaveRecordJobInfo)
async def download_and_create_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    event_id: str,
    body: DownloadByIdRequest,
) -> WaveRecordJobInfo:
    """通过故障事件ID下载录波文件并创建任务。"""
    import asyncio
    import tempfile
    from webui.services.wave_record_parser.downloader import EventDownloader

    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)

    # 先检查是否已存在该 event_id 的任务
    existing = service.get_job_by_external_id(event_id)
    if existing is not None:
        return WaveRecordJobInfo(**existing)

    cookie = body.cookie if body else ""

    # 在线程中执行下载（避免阻塞事件循环）
    def _download_and_create():
        from pathlib import Path
        from webui.services.wave_record_parser.service import parse_fault_event_md

        downloader = EventDownloader(cookie=cookie)
        with tempfile.TemporaryDirectory(prefix="wave_download_") as tmp_dir:
            # 下载文件
            save_dir = downloader.download_event(event_id, tmp_dir)
            # 从 _故障事件信息.md 提取装置名称（兼容多种字段名）
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
            # 从下载目录创建任务
            return service.create_job_from_directory(
                dir_path=save_dir,
                station=equipment_name or None,
                device=equipment_name or None,
                created_by="authless-public",
                run_in_background=True,
                external_id=event_id,
            )

    try:
        job = await asyncio.to_thread(_download_and_create)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {e}")

    return WaveRecordJobInfo(**job)


@router.patch("/jobs/{job_id}", response_model=WaveRecordJobInfo)
async def update_wave_record_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
    body: UpdateWaveRecordJobRequest,
) -> WaveRecordJobInfo:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    job = service.update_job_fields(
        job_id,
        evaluation=body.evaluation,
        station=body.station,
        device=body.device,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return WaveRecordJobInfo(**job)


@router.delete("/jobs/{job_id}")
async def delete_wave_record_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    ok = service.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


@router.get("/jobs/{job_id}/preview")
async def preview_wave_record_job(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    """返回已完成任务的 Markdown 报告内容，用于浏览器内预览。"""
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    job = service.get_job(job_id)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Job not found or not completed")

    # 优先从工作区 报告/ 目录读取（AI 可能已更新）
    workspace_dir = service.app_root.parent.parent / "workspace"
    ws_report = workspace_dir / "报告" / "跳闸简报.md"
    if ws_report.exists():
        content = ws_report.read_text(encoding="utf-8")
        return {"content": content}

    # 回退到 job output 目录
    job_root = service.app_root / "jobs" / job_id / "output"
    md_files = list(job_root.glob("跳闸简报.md")) + list(job_root.glob("*.md"))
    if not md_files:
        raise HTTPException(status_code=404, detail="Preview not available")

    content = md_files[0].read_text(encoding="utf-8")
    return {"content": content}


@router.post("/jobs/{job_id}/sync-report")
async def sync_report_to_job_output(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    job_id: str,
) -> dict:
    """将工作区中 AI 更新的报告同步到 job output 目录，确保下载拿到最新版本。"""
    ensure_agentplayground_enabled()
    service = get_wave_record_parser_service(svc)
    job = service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    workspace_dir = service.app_root.parent.parent / "workspace"
    ws_report = workspace_dir / "报告" / "跳闸简报.md"
    if not ws_report.exists():
        return {"ok": False, "reason": "workspace report not found"}

    job_output = service.app_root / "jobs" / job_id / "output"
    job_output.mkdir(parents=True, exist_ok=True)
    dest = job_output / "跳闸简报.md"

    # 比较内容，仅在有变化时同步
    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        new_content = ws_report.read_text(encoding="utf-8")
        if existing == new_content:
            return {"ok": False, "reason": "no change"}

    shutil.copy2(str(ws_report), str(dest))

    # 更新 DB 中的文件大小和时间
    from webui.services.agentplayground.db import connect, utcnow_iso
    now = utcnow_iso()
    with connect(service.db_path) as conn:
        conn.execute(
            "UPDATE jobs SET result_file_size = ?, updated_at = ? WHERE id = ?",
            (dest.stat().st_size, now, job_id),
        )

    return {"ok": True}
