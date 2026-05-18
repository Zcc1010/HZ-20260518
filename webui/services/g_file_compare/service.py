from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, row_to_dict, utcnow_iso
from webui.services.agentplayground.models import APP_ID_G_FILE_COMPARE

INTERRUPTED_RESTART_MESSAGE = "服务重启导致任务中断，请重新提交"
G_FILE_CONTRAST_RUNNER_RELATIVE = Path("skills") / "g-file-contrast" / "scripts" / "run_job.py"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    error_message TEXT,
    d5000_file_name TEXT NOT NULL,
    new_gen_file_name TEXT NOT NULL,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created_at
    ON jobs (status, created_at);
"""


def execute_job(app_root: Path, job_id: str) -> Path:
    runner = _resolve_g_file_contrast_runner(app_root)
    completed = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--app-root",
            str(app_root),
            "--job-id",
            job_id,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "g-file-contrast runner failed").strip()
        raise RuntimeError(detail)

    stdout_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise FileNotFoundError("g-file-contrast runner did not print a report path")

    job_root = (app_root / "jobs" / job_id).resolve()
    report_path = Path(stdout_lines[-1]).expanduser().resolve()
    try:
        report_path.relative_to(job_root)
    except ValueError as exc:
        raise PermissionError(f"generated report is outside job root: {report_path}") from exc

    if not report_path.is_file():
        raise FileNotFoundError(f"missing generated report: {report_path}")
    return report_path


def _resolve_g_file_contrast_runner(app_root: Path) -> Path:
    root = app_root.expanduser().resolve()
    runner = (root / G_FILE_CONTRAST_RUNNER_RELATIVE).resolve()
    try:
        runner.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"g-file-contrast runner is outside app root: {runner}") from exc
    if runner.is_file():
        return runner
    raise FileNotFoundError(f"g-file-contrast runner not found: {runner}")


class GFileCompareService:
    app_id = APP_ID_G_FILE_COMPARE

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
                from webui.services.agentplayground.paths import default_g_file_compare_app_root

                app_root = default_g_file_compare_app_root(workspace)
            else:
                app_root = Path.home() / ".nanobot" / "agentplayground" / self.app_id

        self.app_root = Path(app_root).expanduser().resolve()
        self.db_path = self.app_root / "app.db"
        self._initialized = False
        self._queue_lock = asyncio.Lock()
        self._queue_task: asyncio.Task | None = None

    def initialize(self) -> None:
        if self._initialized:
            return
        self.app_root.mkdir(parents=True, exist_ok=True)
        (self.app_root / "jobs").mkdir(parents=True, exist_ok=True)
        with connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)
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
        d5000_file: UploadFile,
        new_gen_file: UploadFile,
        *,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        d5000_name = Path(d5000_file.filename or "d5000-upload").name
        new_gen_name = Path(new_gen_file.filename or "new-gen-upload").name
        d5000_bytes = await d5000_file.read()
        new_gen_bytes = await new_gen_file.read()
        return self._create_job_from_bytes(
            d5000_name=d5000_name,
            d5000_bytes=d5000_bytes,
            new_gen_name=new_gen_name,
            new_gen_bytes=new_gen_bytes,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def create_job(
        self,
        d5000_source: str | Path,
        new_gen_source: str | Path,
        *,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        d5000_path = Path(d5000_source).expanduser().resolve()
        new_gen_path = Path(new_gen_source).expanduser().resolve()
        return self._create_job_from_paths(
            d5000_path=d5000_path,
            new_gen_path=new_gen_path,
            created_by=created_by,
            run_in_background=run_in_background,
        )

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
                    d5000_file_name,
                    new_gen_file_name,
                    result_file_name,
                    result_relative_path,
                    result_download_token
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
                    d5000_file_name,
                    new_gen_file_name,
                    result_file_name,
                    result_relative_path,
                    result_download_token
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None

    def mark_processing(self, job_id: str) -> None:
        self._update_job_status(job_id, "processing", None)

    def mark_completed(self, job_id: str, result_path: str | Path) -> dict[str, Any] | None:
        self.initialize()
        result_file = Path(result_path).expanduser().resolve()
        self._ensure_inside_app_root(result_file)
        if not result_file.exists() or not result_file.is_file():
            raise FileNotFoundError(result_file)

        relative_path = result_file.relative_to(self.app_root)
        mime_type, _ = mimetypes.guess_type(result_file.name)
        now = utcnow_iso()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET
                    status = ?,
                    updated_at = ?,
                    error_message = NULL,
                    result_file_name = ?,
                    result_relative_path = ?,
                    result_download_token = ?,
                    result_mime_type = ?,
                    result_file_size = ?
                WHERE id = ?
                """,
                (
                    "completed",
                    now,
                    result_file.name,
                    str(relative_path),
                    generate_download_token(),
                    mime_type or "text/markdown",
                    result_file.stat().st_size,
                    job_id,
                ),
            )
        return self.get_job(job_id)

    def mark_failed(self, job_id: str, error_message: str) -> dict[str, Any] | None:
        self._update_job_status(job_id, "failed", error_message)
        return self.get_job(job_id)

    def find_result_attachment(self, token: str) -> dict[str, Any] | None:
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
        raw = row_to_dict(row)
        if raw is None or not raw.get("result_relative_path"):
            return None

        file_path = self.app_root / raw["result_relative_path"]
        if not file_path.exists() or not file_path.is_file():
            return None

        return {
            "id": f"gfc_{token}",
            "name": raw["result_file_name"],
            "mime_type": raw["result_mime_type"] or "application/octet-stream",
            "size": raw["result_file_size"] or 0,
            "token": token,
            "download_url": f"/api/files/d/{token}",
            "relative_path": raw["result_relative_path"],
            "_download_root": str(self.app_root),
        }

    async def execute_job(self, job_id: str) -> dict[str, Any] | None:
        self.mark_processing(job_id)
        try:
            result_path = await asyncio.to_thread(execute_job, self.app_root, job_id)
        except Exception as exc:
            return self.mark_failed(job_id, str(exc))
        return self.mark_completed(job_id, result_path)

    async def process_queue(self) -> None:
        self.initialize()
        async with self._queue_lock:
            while True:
                job_id = self._claim_next_queued_job()
                if job_id is None:
                    return
                try:
                    result_path = await asyncio.to_thread(execute_job, self.app_root, job_id)
                except Exception as exc:
                    self.mark_failed(job_id, str(exc))
                    continue
                self.mark_completed(job_id, result_path)

    def start_queue(self) -> None:
        self._schedule_queue()

    def _create_job_from_paths(
        self,
        *,
        d5000_path: Path,
        new_gen_path: Path,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job_root = self._job_root(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        d5000_name = self._safe_upload_name(d5000_path.name, "d5000.g")
        new_gen_name = self._safe_upload_name(new_gen_path.name, "new-gen.g")
        d5000_dest = self._job_input_path(job_id, "d5000", d5000_name)
        new_gen_dest = self._job_input_path(job_id, "new-gen", new_gen_name)
        d5000_dest.parent.mkdir(parents=True, exist_ok=True)
        new_gen_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d5000_path, d5000_dest)
        shutil.copy2(new_gen_path, new_gen_dest)
        self._write_inputs_manifest(job_id, d5000_name=d5000_name, new_gen_name=new_gen_name)
        return self._persist_created_job(
            job_id=job_id,
            d5000_name=d5000_name,
            new_gen_name=new_gen_name,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _create_job_from_bytes(
        self,
        *,
        d5000_name: str,
        d5000_bytes: bytes,
        new_gen_name: str,
        new_gen_bytes: bytes,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job_root = self._job_root(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        d5000_name = self._safe_upload_name(d5000_name, "d5000.g")
        new_gen_name = self._safe_upload_name(new_gen_name, "new-gen.g")
        d5000_dest = self._job_input_path(job_id, "d5000", d5000_name)
        new_gen_dest = self._job_input_path(job_id, "new-gen", new_gen_name)
        d5000_dest.parent.mkdir(parents=True, exist_ok=True)
        new_gen_dest.parent.mkdir(parents=True, exist_ok=True)
        d5000_dest.write_bytes(d5000_bytes)
        new_gen_dest.write_bytes(new_gen_bytes)
        self._write_inputs_manifest(job_id, d5000_name=d5000_name, new_gen_name=new_gen_name)
        return self._persist_created_job(
            job_id=job_id,
            d5000_name=d5000_name,
            new_gen_name=new_gen_name,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _persist_created_job(
        self,
        *,
        job_id: str,
        d5000_name: str,
        new_gen_name: str,
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
                    d5000_file_name,
                    new_gen_file_name
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (job_id, "queued", now, now, created_by, d5000_name, new_gen_name),
            )

        if run_in_background:
            self._schedule_queue()

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Failed to load created compare job: {job_id}")
        return job

    def _schedule_queue(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if self._queue_task is None or self._queue_task.done():
            self._queue_task = loop.create_task(self.process_queue())

    def _claim_next_queued_job(self) -> str | None:
        now = utcnow_iso()
        with connect(self.db_path) as conn:
            active = conn.execute("SELECT id FROM jobs WHERE status = ? LIMIT 1", ("processing",)).fetchone()
            if active is not None:
                return None

            row = conn.execute(
                """
                SELECT id
                FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                ("queued",),
            ).fetchone()
            raw = row_to_dict(row)
            if raw is None:
                return None

            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_message = NULL
                WHERE id = ? AND status = ?
                """,
                ("processing", now, raw["id"], "queued"),
            )
        return raw["id"]

    def _update_job_status(self, job_id: str, status: str, error_message: str | None) -> None:
        self.initialize()
        now = utcnow_iso()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error_message = ?
                WHERE id = ?
                """,
                (status, now, error_message, job_id),
            )

    def _job_root(self, job_id: str) -> Path:
        return self.app_root / "jobs" / job_id

    def _job_input_path(self, job_id: str, source: str, file_name: str) -> Path:
        return self._job_root(job_id) / "inputs" / source / file_name

    def _write_inputs_manifest(self, job_id: str, *, d5000_name: str, new_gen_name: str) -> None:
        manifest = {
            "d5000": {
                "file_name": d5000_name,
                "relative_path": f"inputs/d5000/{d5000_name}",
            },
            "new_gen": {
                "file_name": new_gen_name,
                "relative_path": f"inputs/new-gen/{new_gen_name}",
            },
        }
        (self._job_root(job_id) / "inputs.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _safe_upload_name(file_name: str, fallback: str) -> str:
        cleaned = Path(file_name or fallback).name.strip()
        return cleaned or fallback

    def _ensure_inside_app_root(self, path: Path) -> None:
        try:
            path.relative_to(self.app_root)
        except ValueError as exc:
            raise PermissionError(f"File is outside app root: {path}") from exc

    def _report_exists(self, row: dict[str, Any]) -> bool:
        relative_path = row.get("result_relative_path")
        return bool(relative_path and (self.app_root / relative_path).is_file())

    def _serialize_job(self, row: dict[str, Any]) -> dict[str, Any]:
        token = row.get("result_download_token")
        downloadable = row["status"] == "completed" and token and self._report_exists(row)
        return {
            "id": row["id"],
            "app_id": self.app_id,
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error_message": row.get("error_message"),
            "d5000_file_name": row["d5000_file_name"],
            "new_gen_file_name": row["new_gen_file_name"],
            "result_file_name": row.get("result_file_name") if downloadable else None,
            "download_url": f"/api/files/d/{token}" if downloadable else None,
        }
