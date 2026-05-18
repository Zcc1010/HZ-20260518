from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.models import WaveRecordJobInfo
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
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
    return WaveRecordJobInfo(**job)
