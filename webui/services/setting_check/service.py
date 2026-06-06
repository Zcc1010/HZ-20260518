# -*- coding: utf-8 -*-
"""定值校核服务"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, utcnow_iso

APP_ID_SETTING_CHECK = "setting-check"

INTERRUPTED_RESTART_MESSAGE = "服务重启导致任务中断，请重新提交"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    error_message TEXT,
    station TEXT,
    device TEXT,
    setting_files TEXT,
    calc_file TEXT,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER,
    progress INTEGER DEFAULT 0,
    progress_message TEXT,
    evaluation TEXT
);

CREATE INDEX IF NOT EXISTS idx_setting_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_setting_jobs_status_created_at
    ON jobs (status, created_at);
"""


CHUNK_SIZE = 4 * 1024 * 1024  # 4MB
UPLOAD_SESSION_TTL = 3600  # 1 hour


class ChunkedUploadManager:
    """Manages chunked file upload sessions."""

    def __init__(self, app_root: Path):
        self.app_root = app_root
        self._uploads_dir = app_root / "uploads"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)

    def init_upload(self, file_name: str, total_size: int, total_chunks: int) -> dict[str, Any]:
        upload_id = uuid.uuid4().hex
        upload_dir = self._uploads_dir / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        chunks_dir = upload_dir / "chunks"
        chunks_dir.mkdir(parents=True, exist_ok=True)

        meta = {
            "upload_id": upload_id,
            "file_name": Path(file_name).name,
            "total_size": total_size,
            "total_chunks": total_chunks,
            "received_chunks": [],
            "created_at": __import__("time").time(),
        }
        (upload_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        return {"upload_id": upload_id, "file_name": file_name, "total_chunks": total_chunks}

    def save_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> dict[str, Any]:
        upload_dir = self._uploads_dir / upload_id
        meta_path = upload_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Upload session not found: {upload_id}")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        chunk_path = upload_dir / "chunks" / f"{chunk_index:06d}"
        chunk_path.write_bytes(data)

        received = set(meta.get("received_chunks", []))
        received.add(chunk_index)
        meta["received_chunks"] = sorted(received)
        meta["received_bytes"] = sum(
            (upload_dir / "chunks" / f"{i:06d}").stat().st_size
            for i in received
        )
        (upload_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "received_chunks": len(received),
            "total_chunks": meta["total_chunks"],
            "done": len(received) == meta["total_chunks"],
        }

    def assemble_file(self, upload_id: str) -> Path:
        upload_dir = self._uploads_dir / upload_id
        meta_path = upload_dir / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"Upload session not found: {upload_id}")

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        total_chunks = meta["total_chunks"]
        file_name = meta["file_name"]

        output_path = upload_dir / file_name
        with open(output_path, "wb") as f:
            for i in range(total_chunks):
                chunk_path = upload_dir / "chunks" / f"{i:06d}"
                if not chunk_path.exists():
                    raise FileNotFoundError(f"Missing chunk {i}")
                f.write(chunk_path.read_bytes())

        return output_path

    def cleanup(self, upload_id: str) -> None:
        upload_dir = self._uploads_dir / upload_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    def get_meta(self, upload_id: str) -> dict[str, Any] | None:
        upload_dir = self._uploads_dir / upload_id
        meta_path = upload_dir / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            "upload_id": upload_id,
            "file_name": meta["file_name"],
            "total_size": meta["total_size"],
            "total_chunks": meta["total_chunks"],
            "received_chunks": meta.get("received_chunks", []),
            "done": len(meta.get("received_chunks", [])) == meta["total_chunks"],
        }


def execute_setting_check(
    job_root: Path,
    setting_paths: list[Path],
    calc_paths: list[Path],
    progress_callback: Any = None,
) -> Path:
    """执行定值校核 pipeline"""
    import json
    from webui.services.setting_check.pipeline import run_pipeline
    from webui.trip_briefing.llm.client import LLMClient

    def report_progress(progress: int, message: str) -> None:
        if progress_callback:
            try:
                progress_callback(progress, message)
            except Exception:
                pass

    report_progress(5, "正在读取配置文件...")

    # Get config from webui config
    config_path = Path.home() / ".protection" / "config.json"
    if not config_path.exists():
        config_path = Path.home() / ".nanobot" / "config.json"

    if not config_path.exists():
        raise FileNotFoundError("缺少配置文件 config.json，无法调用 LLM")

    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    default_model = config_data.get("agents", {}).get("defaults", {}).get("model", "glm-4-flash")

    providers = config_data.get("providers", {})
    provider = None
    preferred_providers = ["zhipu", "dashscope", "deepseek", "openai", "openrouter"]
    for name in preferred_providers:
        p = providers.get(name, {})
        if p.get("apiKey") or p.get("api_key"):
            provider = {
                "base_url": p.get("apiBase") or p.get("base_url", ""),
                "api_key": p.get("apiKey") or p.get("api_key", ""),
                "model": p.get("model", default_model),
            }
            break

    if not provider:
        for name, p in providers.items():
            if p.get("apiKey") or p.get("api_key"):
                provider = {
                    "base_url": p.get("apiBase") or p.get("base_url", ""),
                    "api_key": p.get("apiKey") or p.get("api_key", ""),
                    "model": p.get("model", default_model),
                }
                break

    if not provider:
        raise ValueError("配置文件中未找到有效的 provider")

    api_url = provider.get("base_url", "")
    api_key = provider.get("api_key", "")
    model = provider.get("model", default_model)

    if not api_key:
        raise ValueError("配置文件中未找到 API key")

    report_progress(10, "正在创建 LLM 客户端...")

    llm_client = LLMClient(
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=180,
        max_retries=3,
        enable_thinking=True,
    )

    def llm_call(prompt: str) -> str:
        response = llm_client.chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=8192,
        )
        if not response.success:
            raise RuntimeError(f"LLM 调用失败: {response.error_message}")
        return response.content

    report_progress(20, "正在执行定值校核...")

    output_dir = job_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        setting_paths=[str(p) for p in setting_paths],
        calc_paths=[str(p) for p in calc_paths],
        llm_call_func=llm_call,
        output_dir=str(output_dir),
    )

    report_progress(95, "正在保存结果...")

    report_path = Path(result["report_path"])
    return report_path


class SettingCheckService:
    app_id = APP_ID_SETTING_CHECK

    def __init__(
        self,
        app_root: str | Path | None = None,
        *,
        workspace: str | Path | None = None,
        db_path: str | Path | None = None,
    ):
        if app_root is None:
            if db_path is not None:
                app_root = Path(db_path).expanduser().resolve().parent
            elif workspace is not None:
                from webui.services.agentplayground.paths import default_setting_check_app_root
                app_root = default_setting_check_app_root(workspace)
            else:
                app_root = Path.home() / ".nanobot" / "agentplayground" / self.app_id

        self.app_root = Path(app_root).expanduser().resolve()
        self.db_path = self.app_root / "app.db"
        self._initialized = False
        self._queue_lock = asyncio.Lock()
        self._queue_task: asyncio.Task | None = None
        self._chunked_upload: ChunkedUploadManager | None = None

    @property
    def chunked_upload(self) -> ChunkedUploadManager:
        if self._chunked_upload is None:
            self._chunked_upload = ChunkedUploadManager(self.app_root)
        return self._chunked_upload

    def initialize(self) -> None:
        if self._initialized:
            return
        self.app_root.mkdir(parents=True, exist_ok=True)
        (self.app_root / "jobs").mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress_message TEXT")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN evaluation TEXT")
            except Exception:
                pass
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_message = ?
                WHERE status = ?
                """,
                ("failed", utcnow_iso(), INTERRUPTED_RESTART_MESSAGE, "processing"),
            )
        self._initialized = True

    async def create_job_from_uploads(
        self,
        setting_files: list[UploadFile],
        calc_file: UploadFile,
        *,
        station: str | None = None,
        device: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        setting_bytes_list = []
        setting_names = []
        for upload_file in setting_files:
            file_bytes = await upload_file.read()
            setting_bytes_list.append(file_bytes)
            setting_names.append(Path(upload_file.filename or "setting").name)

        calc_bytes = await calc_file.read()
        calc_name = Path(calc_file.filename or "calc").name

        return self._create_job_from_bytes(
            setting_names=setting_names,
            setting_bytes_list=setting_bytes_list,
            calc_name=calc_name,
            calc_bytes=calc_bytes,
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    async def create_job_from_zip_upload(
        self,
        zip_upload_id: str,
        *,
        station: str | None = None,
        device: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        """Create job from a single zip file containing 定值单/ and 计算书/ directories."""
        import zipfile as zf

        zip_path = self.chunked_upload.assemble_file(zip_upload_id)
        setting_names = []
        setting_bytes_list = []
        calc_name = None
        calc_bytes = None

        # Extensions for setting files and calc files
        setting_extensions = {".xls", ".xlsx", ".doc", ".docx", ".pdf"}
        calc_extensions = {".doc", ".docx", ".pdf", ".md", ".txt"}

        with zf.ZipFile(zip_path, "r") as zip_file:
            all_files = [info for info in zip_file.infolist() if not info.is_dir()]

            # First pass: try to find files by directory name
            for info in all_files:
                name = info.filename
                name_lower = name.lower()
                # Check if it's in 定值单 directory
                if "定值单" in name or "setting" in name_lower:
                    data = zip_file.read(info)
                    setting_names.append(Path(name).name)
                    setting_bytes_list.append(data)
                # Check if it's in 计算书 directory
                elif "计算书" in name or "calc" in name_lower:
                    if calc_name is None:  # Only take the first calc file
                        data = zip_file.read(info)
                        calc_name = Path(name).name
                        calc_bytes = data

            # Second pass: if no files found by directory, try by extension
            if not setting_names or calc_name is None:
                for info in all_files:
                    name = info.filename
                    ext = Path(name).suffix.lower()

                    # Skip if already processed
                    if "定值单" in name or "setting" in name.lower() or "计算书" in name or "calc" in name.lower():
                        continue

                    # Try to identify by extension
                    if not setting_names and ext in setting_extensions:
                        data = zip_file.read(info)
                        setting_names.append(Path(name).name)
                        setting_bytes_list.append(data)
                    elif calc_name is None and ext in calc_extensions:
                        # Check if filename contains keywords for calc
                        if any(kw in name for kw in ["计算", "整定", "calc"]):
                            data = zip_file.read(info)
                            calc_name = Path(name).name
                            calc_bytes = data

            # Third pass: if still no calc file, take the largest non-setting file
            if calc_name is None and setting_names:
                remaining = [info for info in all_files
                            if Path(info.filename).name not in setting_names
                            and Path(info.filename).suffix.lower() in calc_extensions]
                if remaining:
                    # Take the largest file as calc
                    largest = max(remaining, key=lambda x: x.file_size)
                    data = zip_file.read(largest)
                    calc_name = Path(largest.filename).name
                    calc_bytes = data

        self.chunked_upload.cleanup(zip_upload_id)

        if not setting_names:
            raise ValueError("ZIP 文件中未找到定值单文件（支持格式：xls/xlsx/doc/docx/pdf）")
        if calc_name is None:
            raise ValueError("ZIP 文件中未找到计算书文件（支持格式：doc/docx/pdf/md/txt）")

        return self._create_job_from_bytes(
            setting_names=setting_names,
            setting_bytes_list=setting_bytes_list,
            calc_name=calc_name,
            calc_bytes=calc_bytes,
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    async def create_job_from_chunked_upload(
        self,
        setting_upload_ids: list[str],
        calc_upload_id: str,
        *,
        station: str | None = None,
        device: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        """Legacy method for single calc file."""
        setting_paths = []
        setting_names = []
        for upload_id in setting_upload_ids:
            file_path = self.chunked_upload.assemble_file(upload_id)
            setting_paths.append(file_path)
            setting_names.append(file_path.name)

        calc_path = self.chunked_upload.assemble_file(calc_upload_id)
        calc_name = calc_path.name

        # Read bytes
        setting_bytes_list = [p.read_bytes() for p in setting_paths]
        calc_bytes = calc_path.read_bytes()

        # Cleanup uploads
        for upload_id in setting_upload_ids:
            self.chunked_upload.cleanup(upload_id)
        self.chunked_upload.cleanup(calc_upload_id)

        return self._create_job_from_bytes(
            setting_names=setting_names,
            setting_bytes_list=setting_bytes_list,
            calc_name=calc_name,
            calc_bytes=calc_bytes,
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    async def create_job_from_chunked_uploads(
        self,
        setting_upload_ids: list[str],
        calc_upload_ids: list[str],
        *,
        station: str | None = None,
        device: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        """Create job from multiple setting files and multiple calc files."""
        setting_paths = []
        setting_names = []
        for upload_id in setting_upload_ids:
            file_path = self.chunked_upload.assemble_file(upload_id)
            setting_paths.append(file_path)
            setting_names.append(file_path.name)

        calc_paths = []
        calc_names = []
        for upload_id in calc_upload_ids:
            file_path = self.chunked_upload.assemble_file(upload_id)
            calc_paths.append(file_path)
            calc_names.append(file_path.name)

        # Read bytes
        setting_bytes_list = [p.read_bytes() for p in setting_paths]
        calc_bytes_list = [p.read_bytes() for p in calc_paths]

        # Cleanup uploads
        for upload_id in setting_upload_ids:
            self.chunked_upload.cleanup(upload_id)
        for upload_id in calc_upload_ids:
            self.chunked_upload.cleanup(upload_id)

        return self._create_job_from_multiple_bytes(
            setting_names=setting_names,
            setting_bytes_list=setting_bytes_list,
            calc_names=calc_names,
            calc_bytes_list=calc_bytes_list,
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _create_job_from_bytes(
        self,
        *,
        setting_names: list[str],
        setting_bytes_list: list[bytes],
        calc_name: str,
        calc_bytes: bytes,
        station: str | None,
        device: str | None,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        """Legacy method for single calc file."""
        return self._create_job_from_multiple_bytes(
            setting_names=setting_names,
            setting_bytes_list=setting_bytes_list,
            calc_names=[calc_name],
            calc_bytes_list=[calc_bytes],
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _create_job_from_multiple_bytes(
        self,
        *,
        setting_names: list[str],
        setting_bytes_list: list[bytes],
        calc_names: list[str],
        calc_bytes_list: list[bytes],
        station: str | None,
        device: str | None,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        """Create job from multiple setting files and multiple calc files."""
        job_id = uuid.uuid4().hex
        job_root = self._job_root(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        inputs_dir = job_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        # Save setting files and track safe names
        safe_setting_names = []
        for name, data in zip(setting_names, setting_bytes_list, strict=True):
            safe_name = self._safe_upload_name(name, "setting")
            (inputs_dir / safe_name).write_bytes(data)
            safe_setting_names.append(safe_name)

        # Save calc files
        safe_calc_names = []
        for name, data in zip(calc_names, calc_bytes_list, strict=True):
            safe_name = self._safe_upload_name(name, "calc")
            (inputs_dir / safe_name).write_bytes(data)
            safe_calc_names.append(safe_name)

        primary_name = station or device or safe_setting_names[0] if safe_setting_names else "setting_check"

        # Use first calc file as primary for manifest
        primary_calc_name = safe_calc_names[0] if safe_calc_names else ""

        self._write_inputs_manifest(
            job_id,
            setting_files=safe_setting_names,
            calc_file=primary_calc_name,
            calc_files=safe_calc_names,
        )

        return self._persist_created_job(
            job_id=job_id,
            file_name=primary_name,
            setting_files=safe_setting_names,
            calc_file=primary_calc_name,
            station=station,
            device=device,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _safe_upload_name(self, name: str, default: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in "._- ")
        return safe[:200] if safe else default

    def _write_inputs_manifest(
        self,
        job_id: str,
        *,
        setting_files: list[str],
        calc_file: str,
        calc_files: list[str] | None = None,
    ) -> None:
        manifest = {
            "job_id": job_id,
            "setting_files": setting_files,
            "calc_file": calc_file,
            "calc_files": calc_files if calc_files else [calc_file] if calc_file else [],
        }
        manifest_path = self._job_root(job_id) / "inputs.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def _persist_created_job(
        self,
        *,
        job_id: str,
        file_name: str,
        setting_files: list[str],
        calc_file: str,
        station: str | None,
        device: str | None,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        self.initialize()
        now = utcnow_iso()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id,
                    status,
                    created_at,
                    updated_at,
                    created_by,
                    error_message,
                    station,
                    device,
                    setting_files,
                    calc_file
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (job_id, "queued", now, now, created_by, station, device, json.dumps(setting_files), calc_file),
            )

        if run_in_background:
            self._schedule_queue()

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Failed to load created setting check job: {job_id}")
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        self.initialize()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    status,
                    created_at,
                    updated_at,
                    error_message,
                    station,
                    device,
                    setting_files,
                    calc_file,
                    result_file_name,
                    result_relative_path,
                    result_download_token,
                    progress,
                    progress_message,
                    evaluation
                FROM jobs
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [self._serialize_job(dict(row)) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        self.initialize()
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    status,
                    created_at,
                    updated_at,
                    error_message,
                    station,
                    device,
                    setting_files,
                    calc_file,
                    result_file_name,
                    result_relative_path,
                    result_download_token,
                    progress,
                    progress_message,
                    evaluation
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return self._serialize_job(dict(row))

    def _serialize_job(self, row: dict[str, Any]) -> dict[str, Any]:
        result_file_name = row.get("result_file_name")
        result_relative_path = row.get("result_relative_path")
        download_token = row.get("result_download_token")

        download_url: str | None = None
        if download_token:
            download_url = f"/api/files/d/{download_token}"

        setting_files = row.get("setting_files")
        if isinstance(setting_files, str):
            try:
                setting_files = json.loads(setting_files)
            except Exception:
                setting_files = []
        elif setting_files is None:
            setting_files = []

        return {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error_message": row.get("error_message") or None,
            "station": row.get("station") or "",
            "device": row.get("device") or "",
            "setting_files": setting_files,
            "calc_file": row.get("calc_file") or "",
            "result_file_name": result_file_name,
            "download_url": download_url,
            "preview_url": f"/api/setting-check/jobs/{row['id']}/preview" if download_token else None,
            "progress": row.get("progress") or 0,
            "progress_message": row.get("progress_message") or "",
            "evaluation": row.get("evaluation") or "",
        }

    def _claim_next_queued_job(self) -> str | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            job_id = row["id"]
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                ("processing", utcnow_iso(), job_id),
            )
            return job_id

    def update_progress(self, job_id: str, progress: int, message: str) -> None:
        self.initialize()
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET progress = ?, progress_message = ?, updated_at = ? WHERE id = ?",
                (progress, message, utcnow_iso(), job_id),
            )

    def mark_processing(self, job_id: str) -> None:
        self.initialize()
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                ("processing", utcnow_iso(), job_id),
            )

    def mark_completed(self, job_id: str, result_file: Path) -> dict[str, Any]:
        self.initialize()
        result_file_name = result_file.name
        relative_path = result_file.relative_to(self.app_root)
        mime_type = mimetypes.guess_type(result_file_name)[0] or "application/octet-stream"
        file_size = result_file.stat().st_size
        token = generate_download_token()

        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    updated_at = ?,
                    result_file_name = ?,
                    result_relative_path = ?,
                    result_download_token = ?,
                    result_mime_type = ?,
                    result_file_size = ?,
                    progress = 100,
                    progress_message = '完成'
                WHERE id = ?
                """,
                ("completed", utcnow_iso(), result_file_name, str(relative_path), token, mime_type, file_size, job_id),
            )

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found after completion: {job_id}")
        return job

    def find_result_attachment(self, token: str) -> dict[str, Any] | None:
        """Find a completed job's result attachment by download token."""
        self.initialize()
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    result_file_name,
                    result_relative_path,
                    result_mime_type,
                    result_file_size
                FROM jobs
                WHERE result_download_token = ? AND status = ?
                """,
                (token, "completed"),
            ).fetchone()
        if row is None:
            return None
        raw = {
            "result_file_name": row[0],
            "result_relative_path": row[1],
            "result_mime_type": row[2],
            "result_file_size": row[3],
        }
        if not raw.get("result_relative_path"):
            return None

        file_path = self.app_root / raw["result_relative_path"]
        if not file_path.exists() or not file_path.is_file():
            return None

        return {
            "id": f"sc_{token}",
            "name": raw["result_file_name"],
            "mime_type": raw["result_mime_type"] or "application/octet-stream",
            "size": raw["result_file_size"] or 0,
            "token": token,
            "download_url": f"/api/files/d/{token}",
            "relative_path": raw["result_relative_path"],
            "_download_root": str(self.app_root),
        }

    def get_input_file_content(self, job_id: str, file_name: str) -> str | None:
        """获取任务的输入文件内容"""
        self.initialize()
        job_root = self._job_root(job_id)
        inputs_dir = job_root / "inputs"
        file_path = inputs_dir / file_name
        if not file_path.exists() or not file_path.is_file():
            return None
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def mark_failed(self, job_id: str, error_message: str) -> dict[str, Any]:
        self.initialize()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_message = ?, progress = 0, progress_message = '失败'
                WHERE id = ?
                """,
                ("failed", utcnow_iso(), error_message, job_id),
            )

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found after failure: {job_id}")
        return job

    def delete_job(self, job_id: str) -> bool:
        self.initialize()
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        job_dir = self._job_root(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        return True

    def update_job_evaluation(self, job_id: str, evaluation: str) -> dict[str, Any] | None:
        self.initialize()
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET evaluation = ?, updated_at = ? WHERE id = ?",
                (evaluation, utcnow_iso(), job_id),
            )
        return self.get_job(job_id)

    def get_export_files(self, job_ids: list[str]) -> list[tuple[Path, str]]:
        self.initialize()
        results: list[tuple[Path, str]] = []
        with connect(self.db_path) as conn:
            for job_id in job_ids:
                row = conn.execute(
                    "SELECT status, result_relative_path, result_file_name FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    continue
                row = dict(row)
                if row["status"] != "completed" or not row.get("result_relative_path"):
                    continue
                file_path = self.app_root / row["result_relative_path"]
                if file_path.is_file():
                    display_name = row.get("result_file_name") or file_path.name
                    results.append((file_path, display_name))
        return results

    def _job_root(self, job_id: str) -> Path:
        return self.app_root / "jobs" / job_id

    def _schedule_queue(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._queue_task is not None and not self._queue_task.done():
            return

        self._queue_task = loop.create_task(self.process_queue())

    async def process_queue(self) -> None:
        self.initialize()
        async with self._queue_lock:
            while True:
                job_id = self._claim_next_queued_job()
                if job_id is None:
                    return
                try:
                    def progress_callback(progress: int, message: str) -> None:
                        self.update_progress(job_id, progress, message)

                    result_path = await asyncio.to_thread(
                        self._execute_job_sync, job_id, progress_callback
                    )
                except Exception as exc:
                    self.mark_failed(job_id, str(exc))
                    continue

                # Convert .md to .docx for user download
                result_path = self._convert_to_docx(result_path)

                self.mark_completed(job_id, result_path)

    def _convert_to_docx(self, md_path: Path) -> Path:
        """将 .md 报告转换为 .docx，保留 .md 用于预览。"""
        if md_path.suffix.lower() != ".md" or not md_path.is_file():
            return md_path
        docx_path = md_path.with_suffix(".docx")
        try:
            from webui.utils.md_to_docx import MdToDocxConverter
            converter = MdToDocxConverter()
            md_content = md_path.read_text(encoding="utf-8")
            converter.convert(md_content, docx_path)
            return docx_path
        except Exception:
            return md_path  # 转换失败时回退到 .md

    def _execute_job_sync(self, job_id: str, progress_callback: Any) -> Path:
        job_root = self._job_root(job_id)
        inputs_dir = job_root / "inputs"

        # Load manifest
        manifest_path = job_root / "inputs.json"
        if not manifest_path.exists():
            raise FileNotFoundError("inputs.json not found")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        setting_names = manifest.get("setting_files", [])
        calc_names = manifest.get("calc_files", [])

        # Legacy support: if calc_files not present, use calc_file
        if not calc_names and manifest.get("calc_file"):
            calc_names = [manifest.get("calc_file")]

        if not setting_names or not calc_names:
            raise ValueError("Missing setting files or calc files in manifest")

        setting_paths = [inputs_dir / name for name in setting_names]
        calc_paths = [inputs_dir / name for name in calc_names]

        # Verify files exist
        for p in setting_paths:
            if not p.exists():
                raise FileNotFoundError(f"Setting file not found: {p}")
        for p in calc_paths:
            if not p.exists():
                raise FileNotFoundError(f"Calc file not found: {p}")

        return execute_setting_check(
            job_root=job_root,
            setting_paths=setting_paths,
            calc_paths=calc_paths,
            progress_callback=progress_callback,
        )
