from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer
from webui.api.models import GFileCompareJobInfo
from webui.api.routes.agentplayground import ensure_agentplayground_enabled
from webui.services.agentplayground.paths import default_g_file_compare_app_root
from webui.services.g_file_compare.service import GFileCompareService

router = APIRouter()


def _workspace_from_services(svc: ServiceContainer) -> Path:
    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    return Path(workspace).expanduser().resolve()


def get_g_file_compare_service(svc: ServiceContainer) -> GFileCompareService:
    service = getattr(svc, "g_file_compare_service", None)
    if service is not None:
        service.initialize()
        service.start_queue()
        return service

    workspace = _workspace_from_services(svc)
    app_root = getattr(svc, "g_file_compare_app_root", None) or default_g_file_compare_app_root(workspace)
    service = GFileCompareService(app_root=app_root)
    service.initialize()
    service.start_queue()
    setattr(svc, "g_file_compare_app_root", str(service.app_root))
    setattr(svc, "g_file_compare_service", service)
    return service


@router.get("/jobs", response_model=list[GFileCompareJobInfo])
async def list_compare_jobs(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[GFileCompareJobInfo]:
    ensure_agentplayground_enabled()
    service = get_g_file_compare_service(svc)
    return [GFileCompareJobInfo(**job) for job in service.list_jobs()]


@router.post("/jobs", response_model=GFileCompareJobInfo)
async def create_compare_job(
    d5000_file: Annotated[UploadFile, File()],
    new_gen_file: Annotated[UploadFile, File()],
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> GFileCompareJobInfo:
    ensure_agentplayground_enabled()
    service = get_g_file_compare_service(svc)
    created_by = "authless-public"
    job = await service.create_job_from_uploads(
        d5000_file=d5000_file,
        new_gen_file=new_gen_file,
        created_by=created_by,
        run_in_background=True,
    )
    return GFileCompareJobInfo(**job)
