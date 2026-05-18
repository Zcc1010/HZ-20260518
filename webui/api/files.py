"""Helpers for exposing workspace files as downloadable attachments."""

from __future__ import annotations

import mimetypes
import secrets
from pathlib import Path
from typing import Any

DOWNLOAD_ROUTE_PREFIX = "/api/files/d"


def generate_download_token() -> str:
    """Return a long-lived opaque token for anonymous file downloads."""
    return secrets.token_urlsafe(24)


def _resolve_workspace_file(workspace: str | Path, file_path: str | Path) -> tuple[Path, Path]:
    workspace_root = Path(workspace).expanduser().resolve()
    candidate = Path(file_path).expanduser().resolve()

    if not candidate.exists():
        raise FileNotFoundError(candidate)
    if not candidate.is_file():
        raise FileNotFoundError(candidate)

    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise PermissionError(f"File is outside workspace: {candidate}") from exc

    return workspace_root, candidate


def build_attachment_metadata(workspace: str | Path, file_path: str | Path) -> dict[str, Any]:
    """Validate a workspace file and return metadata used by the WebUI."""
    workspace_root, candidate = _resolve_workspace_file(workspace, file_path)
    token = generate_download_token()
    mime_type, _ = mimetypes.guess_type(candidate.name)

    return {
        "id": f"att_{secrets.token_hex(8)}",
        "name": candidate.name,
        "mime_type": mime_type or "application/octet-stream",
        "size": candidate.stat().st_size,
        "token": token,
        "download_url": f"{DOWNLOAD_ROUTE_PREFIX}/{token}",
        "relative_path": str(candidate.relative_to(workspace_root)),
    }


def to_public_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    """Return the fields the frontend should receive for an attachment."""
    return {
        "id": attachment.get("id"),
        "name": attachment.get("name"),
        "mime_type": attachment.get("mime_type"),
        "size": attachment.get("size"),
        "download_url": attachment.get("download_url"),
    }


def find_attachment_by_token(session_manager: Any, token: str) -> dict[str, Any] | None:
    """Scan persisted session messages for an attachment token."""
    for session_info in session_manager.list_sessions():
        key = session_info.get("key")
        if not key:
            continue
        session = session_manager.get_or_create(key)
        for message in getattr(session, "messages", []):
            for attachment in message.get("attachments") or []:
                if attachment.get("token") == token:
                    return attachment
    return None


def resolve_attachment_download_path(workspace: str | Path, attachment: dict[str, Any]) -> Path:
    """Resolve a persisted attachment back to a safe workspace file path."""
    relative_path = attachment.get("relative_path")
    if not relative_path:
        raise FileNotFoundError("Attachment does not include relative_path")
    _, candidate = _resolve_workspace_file(Path(workspace), Path(workspace) / relative_path)
    return candidate
