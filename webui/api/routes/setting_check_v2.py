# -*- coding: utf-8 -*-
"""定值校核 V2 API — 工作区/文件管理（纯 Python 实现，不依赖外部服务）"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse

router = APIRouter()

# ── 工作区根目录 ──

def _workspace_root() -> Path:
    """~/.nanobot/agentplayground/setting-check/workspace/"""
    home = Path.home()
    root = home / ".nanobot" / "agentplayground" / "setting-check" / "workspace"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ws_path(ws: str) -> Path:
    """获取工作区绝对路径"""
    return _workspace_root() / ws


def _safe_join(base: Path, target: str) -> Path:
    """防止路径穿越"""
    result = (base / target).resolve()
    if not str(result).startswith(str(base.resolve())):
        raise ValueError("path traversal detected")
    return result


# ── 文件树构建 ──

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
BINARY_EXTS = {"xls", "xlsx", "docx"}
PDF_EXTS = {"pdf"}
EXCLUDED_DIRS = {"node_modules", "temp", "__pycache__", ".git"}


def _build_tree(dir_path: Path, base_path: Path) -> list[dict[str, Any]]:
    """递归构建文件树"""
    items = []
    if not dir_path.exists() or not dir_path.is_dir():
        return items

    for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        if entry.name.startswith(".") or entry.name in EXCLUDED_DIRS:
            continue
        stat = entry.stat()
        rel_path = str(entry.relative_to(base_path)).replace("\\", "/")
        node: dict[str, Any] = {
            "name": entry.name,
            "path": rel_path,
            "type": "directory" if entry.is_dir() else "file",
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
        if entry.is_dir():
            node["children"] = _build_tree(entry, base_path)
            # 报告目录只保留 .md 文件
            if entry.name == "报告":
                node["children"] = [c for c in node["children"] if c["type"] == "directory" or c["name"].endswith(".md")]
        items.append(node)

    # 报告目录排到最后
    items.sort(key=lambda e: (e["name"] == "报告", not e["type"] == "directory", e["name"].lower()))
    return items


# ── 工作区 CRUD ──

@router.get("/workspaces")
async def list_workspaces():
    root = _workspace_root()
    items = []
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.is_dir() and not entry.name.startswith(".") and entry.name not in EXCLUDED_DIRS:
            items.append({"name": entry.name, "type": "directory"})
    return {"items": items}


@router.post("/workspaces")
async def create_workspace(request: Request):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name or "/" in name or "\\" in name:
        return Response(content=json.dumps({"error": "invalid name"}), status_code=400, media_type="application/json")
    target = _ws_path(name)
    if target.exists():
        return Response(content=json.dumps({"error": "already exists"}), status_code=409, media_type="application/json")
    target.mkdir(parents=True, exist_ok=True)
    return {"name": name}


@router.patch("/workspaces/{ws}")
async def rename_workspace(ws: str, request: Request):
    body = await request.json()
    new_name = body.get("name", "").strip()
    if not new_name or "/" in new_name or "\\" in new_name:
        return Response(content=json.dumps({"error": "invalid name"}), status_code=400, media_type="application/json")
    old_path = _ws_path(ws)
    new_path = _ws_path(new_name)
    if not old_path.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    if new_path.exists():
        return Response(content=json.dumps({"error": "name exists"}), status_code=409, media_type="application/json")
    old_path.rename(new_path)
    return {"name": new_name}


@router.delete("/workspaces/{ws}")
async def delete_workspace(ws: str):
    target = _ws_path(ws)
    if not target.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    shutil.rmtree(target)
    return {"ok": True}


# ── 文件操作 ──

@router.get("/workspaces/{ws}/tree")
async def get_file_tree(ws: str):
    dir_path = _ws_path(ws)
    if not dir_path.exists() or not dir_path.is_dir():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    return _build_tree(dir_path, dir_path)


@router.get("/workspaces/{ws}/search")
async def search_files(ws: str, q: str = ""):
    dir_path = _ws_path(ws)
    if not dir_path.exists():
        return {"items": []}
    q_lower = q.lower()
    results = []
    for root, _, files in os.walk(dir_path):
        for f in files:
            if f.startswith("."):
                continue
            if q_lower in f.lower():
                full = Path(root) / f
                results.append({"name": f, "path": str(full.relative_to(dir_path)).replace("\\", "/")})
    return {"items": results}


@router.get("/workspaces/{ws}/read")
async def read_file(ws: str, path: str = ""):
    if not path:
        return Response(content=json.dumps({"error": "missing path"}), status_code=400, media_type="application/json")
    try:
        full = _safe_join(_ws_path(ws), path)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not full.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    if full.is_dir():
        return Response(content=json.dumps({"error": "is directory"}), status_code=400, media_type="application/json")

    ext = full.suffix.lower().lstrip(".")

    # 图片：直接返回二进制
    if ext in IMAGE_EXTS:
        mime = f"image/{'svg+xml' if ext == 'svg' else ext}"
        return FileResponse(str(full), media_type=mime)

    # PDF：返回二进制
    if ext in PDF_EXTS:
        return FileResponse(str(full), media_type="application/pdf", headers={"Content-Disposition": "inline"})

    # doc：转 HTML
    if ext == "doc":
        try:
            import subprocess
            result = subprocess.run(
                ["antiword", str(full)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                text = result.stdout
                html = "".join(f"<p>{line}</p>" for line in text.split("\n") if line.strip())
                return Response(content=html, media_type="text/html")
        except Exception:
            pass
        return Response(content=json.dumps({"error": "doc 转换失败"}), status_code=500, media_type="application/json")

    # 二进制格式（xlsx/docx）：返回 base64
    if ext in BINARY_EXTS:
        data = full.read_bytes()
        return {"base64": base64.b64encode(data).decode(), "name": full.name, "ext": ext}

    # 文本：直接返回
    try:
        text = full.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = full.read_text(encoding="gbk", errors="replace")
    return Response(content=text, media_type="text/plain; charset=utf-8")


@router.put("/workspaces/{ws}/write")
async def write_file(ws: str, request: Request):
    body = await request.json()
    path = body.get("path", "")
    content = body.get("content", "")
    if not path:
        return Response(content=json.dumps({"error": "missing path"}), status_code=400, media_type="application/json")
    try:
        full = _safe_join(_ws_path(ws), path)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return {"ok": True}


@router.post("/workspaces/{ws}/rename")
async def rename_file(ws: str, request: Request):
    body = await request.json()
    path = body.get("path", "")
    new_name = body.get("newName", "")
    if not path or not new_name or "/" in new_name:
        return Response(content=json.dumps({"error": "invalid params"}), status_code=400, media_type="application/json")
    try:
        full = _safe_join(_ws_path(ws), path)
        dest = full.parent / new_name
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not full.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    full.rename(dest)
    return {"ok": True}


@router.post("/workspaces/{ws}/copy")
async def copy_file(ws: str, request: Request):
    body = await request.json()
    src = body.get("src", "")
    dest = body.get("dest", "")
    if not src or not dest:
        return Response(content=json.dumps({"error": "missing src or dest"}), status_code=400, media_type="application/json")
    try:
        src_full = _safe_join(_ws_path(ws), src)
        dest_full = _safe_join(_ws_path(ws), dest)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not src_full.exists():
        return Response(content=json.dumps({"error": "src not found"}), status_code=404, media_type="application/json")
    dest_full.parent.mkdir(parents=True, exist_ok=True)
    if src_full.is_dir():
        shutil.copytree(src_full, dest_full)
    else:
        shutil.copy2(src_full, dest_full)
    return {"ok": True}


@router.post("/workspaces/{ws}/duplicate")
async def duplicate_file(ws: str, request: Request):
    body = await request.json()
    path = body.get("path", "")
    if not path:
        return Response(content=json.dumps({"error": "missing path"}), status_code=400, media_type="application/json")
    try:
        src_full = _safe_join(_ws_path(ws), path)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not src_full.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")

    parent = src_full.parent
    ext = src_full.suffix
    base = src_full.stem

    dest_full = None
    for i in range(1, 100):
        candidate = parent / f"{base} 副本{i}{ext}"
        if not candidate.exists():
            dest_full = candidate
            break
    if not dest_full:
        return Response(content=json.dumps({"error": "too many copies"}), status_code=400, media_type="application/json")

    if src_full.is_dir():
        shutil.copytree(src_full, dest_full)
    else:
        shutil.copy2(src_full, dest_full)
    return {"ok": True}


@router.post("/workspaces/{ws}/move")
async def move_file(ws: str, request: Request):
    body = await request.json()
    src = body.get("src", "")
    dest = body.get("dest", "")
    if not src or not dest:
        return Response(content=json.dumps({"error": "missing src or dest"}), status_code=400, media_type="application/json")
    try:
        src_full = _safe_join(_ws_path(ws), src)
        dest_full = _safe_join(_ws_path(ws), dest)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not src_full.exists():
        return Response(content=json.dumps({"error": "src not found"}), status_code=404, media_type="application/json")
    dest_full.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_full), str(dest_full))
    return {"ok": True}


@router.delete("/workspaces/{ws}/file")
async def delete_file(ws: str, path: str = ""):
    if not path:
        return Response(content=json.dumps({"error": "missing path"}), status_code=400, media_type="application/json")
    try:
        full = _safe_join(_ws_path(ws), path)
    except ValueError:
        return Response(content=json.dumps({"error": "path traversal"}), status_code=400, media_type="application/json")
    if not full.exists():
        return Response(content=json.dumps({"error": "not found"}), status_code=404, media_type="application/json")
    if full.is_dir():
        shutil.rmtree(full)
    else:
        full.unlink()
    return {"ok": True}


@router.post("/workspaces/{ws}/upload")
async def upload_files(ws: str, request: Request):
    dir_path = _ws_path(ws)
    if not dir_path.exists():
        return Response(content=json.dumps({"error": "workspace not found"}), status_code=404, media_type="application/json")

    form = await request.form()
    uploaded = []

    for key, value in form.multi_items():
        if hasattr(value, "read"):  # UploadFile
            file_name = value.filename or "unnamed"
            content = await value.read()
            # 支持 category/filename 格式（前端上传时带分类前缀）
            try:
                dest = _safe_join(dir_path, file_name)
            except ValueError:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            uploaded.append(file_name)

    return {"files": uploaded}


# ── SSE 文件变更事件 ──

def _get_dir_mtime(dir_path: Path) -> float:
    """获取目录下所有文件的最新修改时间"""
    max_mtime = 0.0
    if not dir_path.exists():
        return max_mtime
    for root, _, files in os.walk(dir_path):
        for f in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, f))
                if mtime > max_mtime:
                    max_mtime = mtime
            except OSError:
                pass
    return max_mtime


@router.get("/workspaces/{ws}/events")
async def workspace_events(ws: str):
    """SSE endpoint for workspace file change events"""
    dir_path = _ws_path(ws)
    if not dir_path.exists():
        return Response(content=json.dumps({"error": "workspace not found"}), status_code=404, media_type="application/json")

    async def event_generator():
        last_mtime = _get_dir_mtime(dir_path)
        while True:
            await asyncio.sleep(2)
            current_mtime = _get_dir_mtime(dir_path)
            if current_mtime > last_mtime:
                last_mtime = current_mtime
                yield f"data: {json.dumps({'type': 'change', 'path': '', 'mtime': current_mtime})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
