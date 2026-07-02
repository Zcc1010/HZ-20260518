from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from webui.api.deps import get_services
from webui.api.gateway import ServiceContainer

router = APIRouter()


def _feedback_path(svc: ServiceContainer) -> Path:
    workspace = getattr(svc.config, "workspace_path", None) or getattr(svc.config.agents.defaults, "workspace", None)
    return Path(workspace).expanduser().resolve() / "chat_feedback.json"


def _load_feedback(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_feedback(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


class FeedbackRequest(BaseModel):
    message_id: str
    message_content: str = ""
    issue_type: str
    description: str = ""
    session_key: str = ""
    role: str = ""


@router.post("/feedback")
async def submit_feedback(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    body: FeedbackRequest,
) -> dict:
    from webui.services.agentplayground.db import utcnow_iso

    path = _feedback_path(svc)
    items = _load_feedback(path)
    items.append({
        "session_key": body.session_key,
        "message_id": body.message_id,
        "role": body.role,
        "message_content": body.message_content,
        "issue_type": body.issue_type,
        "description": body.description,
        "created_at": utcnow_iso(),
    })
    _save_feedback(path, items)
    return {"ok": True}


@router.delete("/feedback/{index}")
async def delete_feedback(
    svc: Annotated[ServiceContainer, Depends(get_services)],
    index: int,
) -> dict:
    path = _feedback_path(svc)
    items = _load_feedback(path)
    if index < 0 or index >= len(items):
        return {"ok": False, "error": "Index out of range"}
    items.pop(index)
    _save_feedback(path, items)
    return {"ok": True}


@router.get("/feedback")
async def list_feedback(
    svc: Annotated[ServiceContainer, Depends(get_services)],
) -> list[dict]:
    path = _feedback_path(svc)
    return _load_feedback(path)
