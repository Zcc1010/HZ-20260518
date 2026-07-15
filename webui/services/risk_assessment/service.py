# -*- coding: utf-8 -*-
"""运行风险评估服务"""
from __future__ import annotations

import asyncio
import io
import json
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, utcnow_iso

APP_ID_RISK_ASSESSMENT = "risk-assessment"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    error_message TEXT,
    station TEXT,
    folder_path TEXT,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER,
    progress INTEGER DEFAULT 0,
    progress_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_ra_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ra_jobs_status_created_at
    ON jobs (status, created_at);
"""


class RiskAssessmentService:
    """运行风险评估服务"""

    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.jobs_dir = app_root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = app_root / "risk_assessment.db"
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return
        with connect(self._db_path) as conn:
            conn.executescript(_SCHEMA)
        self._initialized = True

    def _schedule_queue(self):
        pass

    def _conn(self):
        return connect(self._db_path)

    def _resolve_skill_dir(self, skill_name: str) -> Path:
        """查找 skills 目录，兼容开发环境和 pip 安装部署。"""
        import os
        candidates = [
            Path(os.environ.get("NANOBOT_SKILLS_DIR", "")) / skill_name if os.environ.get("NANOBOT_SKILLS_DIR") else None,
            Path(__file__).parent.parent.parent.parent / "skills" / skill_name,
            self.app_root.parent.parent / "skills" / skill_name,
            Path.cwd() / "skills" / skill_name,
        ]
        for d in candidates:
            if d and d.is_dir():
                return d
        raise FileNotFoundError(
            f"找不到 skills/{skill_name} 目录。"
            f"请设置环境变量 NANOBOT_SKILLS_DIR 指向 skills 目录的父目录，"
            f"或确认 skills/{skill_name} 已部署到以下位置之一: "
            + ", ".join(str(c) for c in candidates if c)
        )

    def list_jobs(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def create_job(self, files: list[UploadFile], station: str = "") -> dict:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        input_dir = job_dir / "input"
        input_dir.mkdir(exist_ok=True)
        for file in files:
            file_path = input_dir / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

        now = utcnow_iso()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (id, status, created_at, updated_at, station, folder_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (job_id, "processing", now, now, station, str(input_dir)),
            )

        asyncio.create_task(self._run_assessment(job_id, input_dir, station))
        return self.get_job(job_id)

    async def _run_assessment(self, job_id: str, input_dir: Path, station: str):
        job_dir = input_dir.parent
        output_dir = job_dir / "output"
        output_dir.mkdir(exist_ok=True)

        try:
            self._update_progress(job_id, 10, "正在加载数据包...")

            skill_dir = self._resolve_skill_dir("protection-risk-assessment")
            scripts_dir = skill_dir / "scripts"

            cmd = [
                "python", str(scripts_dir / "run_risk_assessment.py"),
                "--data-dir", str(input_dir),
                "--out", str(output_dir),
            ]
            if station:
                cmd.extend(["--station", station])

            self._update_progress(job_id, 30, "正在执行风险评估...")

            proc = await asyncio.to_thread(
                subprocess_run, cmd, 600, str(scripts_dir)
            )

            if proc.returncode != 0:
                raise RuntimeError(f"风险评估失败: {proc.stderr or proc.stdout}")

            self._update_progress(job_id, 80, "正在整理评估结果...")

            # Find briefing.md
            briefing = output_dir / "briefing.md"
            if not briefing.exists():
                # Try to find any .md file
                md_files = list(output_dir.rglob("*.md"))
                if md_files:
                    briefing = md_files[0]
                else:
                    raise RuntimeError("评估未生成结果报告")

            result_name = f"风险评估报告_{job_id}.md"
            result_path = output_dir / result_name
            shutil.copy2(briefing, result_path)

            token = generate_download_token()
            file_size = result_path.stat().st_size

            with self._conn() as conn:
                conn.execute(
                    """UPDATE jobs SET status='completed', updated_at=?,
                       result_file_name=?, result_relative_path=?,
                       result_download_token=?, result_mime_type='text/markdown',
                       result_file_size=?, progress=100, progress_message='评估完成'
                       WHERE id=?""",
                    (utcnow_iso(), result_name, str(result_path.relative_to(job_dir)),
                     token, file_size, job_id),
                )
        except Exception as exc:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE jobs SET status='failed', updated_at=?, error_message=? WHERE id=?",
                    (utcnow_iso(), str(exc), job_id),
                )

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        with self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        job_dir = self.jobs_dir / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        return True

    def get_report_content(self, job_id: str) -> str | None:
        job = self.get_job(job_id)
        if not job or job["status"] != "completed":
            return None
        result_path = self.jobs_dir / job_id / job.get("result_relative_path", "")
        if not result_path.exists():
            return None
        return result_path.read_text(encoding="utf-8")

    def get_report_path(self, job_id: str) -> Path | None:
        job = self.get_job(job_id)
        if not job or job["status"] != "completed":
            return None
        path = self.jobs_dir / job_id / job.get("result_relative_path", "")
        return path if path.exists() else None

    def export_jobs(self, job_ids: list[str]) -> io.BytesIO | None:
        buf = io.BytesIO()
        has_files = False
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for jid in job_ids:
                path = self.get_report_path(jid)
                if path and path.exists():
                    zf.write(path, path.name)
                    has_files = True
        if not has_files:
            return None
        buf.seek(0)
        return buf

    def _update_progress(self, job_id: str, progress: int, message: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET progress=?, progress_message=?, updated_at=? WHERE id=?",
                (progress, message, utcnow_iso(), job_id),
            )

    @staticmethod
    def _row_to_dict(row) -> dict:
        if row is None:
            return {}
        return {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "error_message": row["error_message"],
            "station": row["station"] or "",
            "folder_path": row["folder_path"] or "",
            "result_file_name": row["result_file_name"],
            "download_url": f"/api/risk-assessment/jobs/{row['id']}/download" if row["result_download_token"] else None,
            "preview_url": f"/api/risk-assessment/jobs/{row['id']}/preview" if row["result_file_name"] else None,
            "progress": row["progress"] or 0,
            "progress_message": row["progress_message"],
        }


def subprocess_run(cmd: list[str], timeout: int = 600, cwd: str | None = None):
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
