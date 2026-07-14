# -*- coding: utf-8 -*-
"""电网故障智能分析服务"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import uuid
import zipfile
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, utcnow_iso

APP_ID_FAULT_ANALYSIS = "fault-analysis"

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
    device_type TEXT,
    voltage_level TEXT,
    folder_path TEXT,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER,
    progress INTEGER DEFAULT 0,
    progress_message TEXT,
    evaluation TEXT
);

CREATE INDEX IF NOT EXISTS idx_fault_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fault_jobs_status_created_at
    ON jobs (status, created_at);
"""


class FaultAnalysisService:
    """电网故障智能分析服务"""

    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.jobs_dir = app_root / "jobs"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = app_root / "fault_analysis.db"
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

    def create_job(
        self,
        files: list[UploadFile],
        station: str,
        device: str,
        device_type: str = "线路",
        voltage_level: str = "110kV",
    ) -> dict:
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        # 保存上传的文件
        input_dir = job_dir / "input"
        input_dir.mkdir(exist_ok=True)
        saved_files = []
        for file in files:
            file_path = input_dir / file.filename
            with open(file_path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            saved_files.append(file.filename)

        now = utcnow_iso()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jobs (id, status, created_at, updated_at, station, device, device_type, voltage_level, folder_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job_id, "processing", now, now, station, device, device_type, voltage_level, str(input_dir)),
            )

        # 启动后台分析任务
        asyncio.create_task(self._run_analysis(job_id, input_dir, device_type, voltage_level))

        return self.get_job(job_id)

    async def _run_analysis(self, job_id: str, input_dir: Path, device_type: str, voltage_level: str):
        """后台运行故障分析: extract → parse → rms → LLM 生成报告"""
        import subprocess

        skill_dir = Path(__file__).parent.parent.parent.parent / "skills" / "fault-analysis"
        scripts_dir = skill_dir / "scripts"
        job_dir = input_dir.parent
        output_dir = job_dir / "output"
        output_dir.mkdir(exist_ok=True)

        def _run_script(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(skill_dir))

        try:
            # ── Step 1: 解压压缩包（支持嵌套：zip→zwav→cfg/dat/hdr）──
            self._update_progress(job_id, 5, "正在解压录波文件...")
            self._extract_all_archives(input_dir, output_dir)

            # ── Step 2: 查找 CFG 文件 ──
            self._update_progress(job_id, 20, "正在查找录波配置文件...")
            cfg_files = list(output_dir.rglob("*.cfg")) + list(output_dir.rglob("*.CFG"))
            if not cfg_files:
                # 也搜索 input 目录（可能没压缩包，直接上传的 cfg/dat）
                cfg_files = list(input_dir.rglob("*.cfg")) + list(input_dir.rglob("*.CFG"))
            if not cfg_files:
                raise RuntimeError("未找到 .cfg 配置文件，请确认上传了 COMTRADE 格式的录波文件（.cfg + .dat + .hdr）")

            # ── Step 3: DAT → CSV ──
            self._update_progress(job_id, 30, f"正在解析 {len(cfg_files)} 个录波文件...")
            parse_script = scripts_dir / "parse_dat_to_csv.py"
            csv_dir = output_dir / "csv"
            csv_dir.mkdir(exist_ok=True)

            r = _run_script(["python", str(parse_script)] + [str(f) for f in cfg_files] + ["--output", str(csv_dir)])
            if r.returncode != 0:
                raise RuntimeError(f"DAT 解析失败: {r.stderr or r.stdout}")

            csv_files = list(csv_dir.rglob("*.csv"))
            if not csv_files:
                raise RuntimeError("DAT 解析后未生成 CSV 文件")

            # ── Step 4: 计算 RMS 统计 ──
            self._update_progress(job_id, 50, "正在计算 RMS 统计和事件...")
            rms_script = scripts_dir / "calculate_rms.py"
            rms_dir = output_dir / "rms"
            rms_dir.mkdir(exist_ok=True)

            r = _run_script(["python", str(rms_script)] + [str(f) for f in csv_files] + ["--output", str(rms_dir)])
            if r.returncode != 0:
                print(f"[fault-analysis] RMS 计算警告: {r.stderr}", flush=True)

            # ── Step 5: 收集分析数据 ──
            self._update_progress(job_id, 65, "正在收集分析数据...")
            analysis_data = self._collect_analysis_data(input_dir, output_dir, cfg_files, device_type, voltage_level)

            # ── Step 6: LLM 生成报告 ──
            self._update_progress(job_id, 75, "正在调用 AI 生成分析报告...")
            report_md = await self._generate_report_with_llm(analysis_data)

            # 保存报告
            report_path = job_dir / "故障分析报告.md"
            report_path.write_text(report_md, encoding="utf-8")

            # 更新数据库
            file_size = report_path.stat().st_size
            mime_type = "text/markdown"
            download_token = generate_download_token()

            with self._conn() as conn:
                conn.execute(
                    """UPDATE jobs SET status = 'completed', updated_at = ?,
                       result_file_name = ?, result_relative_path = ?,
                       result_download_token = ?, result_mime_type = ?,
                       result_file_size = ?, progress = 100, progress_message = '分析完成'
                       WHERE id = ?""",
                    (utcnow_iso(), report_path.name, str(report_path),
                     download_token, mime_type, file_size, job_id),
                )

        except Exception as e:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', error_message = ?, updated_at = ? WHERE id = ?",
                    (str(e), utcnow_iso(), job_id),
                )

    def _collect_analysis_data(
        self, input_dir: Path, output_dir: Path, cfg_files: list[Path],
        device_type: str, voltage_level: str,
    ) -> dict:
        """收集所有分析数据，用于构造 LLM prompt。"""
        data: dict[str, Any] = {
            "device_type": device_type,
            "voltage_level": voltage_level,
            "devices": [],
        }

        # 解析每个 CFG 对应的 HDR 和 RMS 数据
        for cfg_path in cfg_files:
            device_data: dict[str, Any] = {"cfg_path": str(cfg_path)}

            # 读取 CFG 基本信息
            try:
                lines = cfg_path.read_text(encoding="gb18030", errors="replace").splitlines()
                if lines:
                    parts = lines[0].strip().split(",")
                    device_data["station_name"] = parts[0].strip() if len(parts) > 0 else ""
                    device_data["device_name"] = parts[1].strip() if len(parts) > 1 else ""
                if len(lines) > 1:
                    second = lines[1].strip().split(",")
                    if len(second) >= 2:
                        device_data["analog_channels"] = second[1].strip().rstrip("Aa")
            except Exception:
                pass

            # 查找对应的 HDR 文件
            hdr_candidates = list(cfg_path.parent.glob("*.hdr")) + list(cfg_path.parent.glob("*.HDR"))
            if hdr_candidates:
                device_data["hdr_path"] = str(hdr_candidates[0])
                try:
                    import xml.etree.ElementTree as ET
                    tree = ET.parse(str(hdr_candidates[0]))
                    root = tree.getroot()
                    hdr_info: dict[str, str] = {}
                    for elem in root.findall("DeviceInfo"):
                        name_e = elem.find("name")
                        val_e = elem.find("value")
                        if name_e is not None and val_e is not None and name_e.text and val_e.text:
                            hdr_info[name_e.text] = val_e.text
                    for elem in root.findall("FaultInfo"):
                        name_e = elem.find("name")
                        val_e = elem.find("value")
                        if name_e is not None and val_e is not None and name_e.text and val_e.text:
                            hdr_info[name_e.text] = val_e.text
                    device_data["hdr_info"] = hdr_info
                except Exception:
                    pass

            # 查找对应的 RMS 结果
            device_stem = cfg_path.stem
            rms_csv = output_dir / "rms" / f"{device_stem}_rms.csv"
            if rms_csv.exists():
                try:
                    rms_text = rms_csv.read_text(encoding="utf-8", errors="replace")
                    # 只取前 200 行避免 prompt 过长
                    rms_lines = rms_text.splitlines()[:200]
                    device_data["rms_csv"] = "\n".join(rms_lines)
                except Exception:
                    pass

            # 查找 events 文件
            events_csv = output_dir / "rms" / f"{device_stem}_events.csv"
            if events_csv.exists():
                try:
                    events_text = events_csv.read_text(encoding="utf-8", errors="replace")
                    events_lines = events_text.splitlines()[:100]
                    device_data["events_csv"] = "\n".join(events_lines)
                except Exception:
                    pass

            data["devices"].append(device_data)

        # 读取模板和规则（如果有）
        refs_dir = skill_dir = Path(__file__).parent.parent.parent.parent / "skills" / "fault-analysis" / "references"
        template_map = {
            "线路": "线路跳闸简报模板.md",
            "主变": "主变跳闸简报模板.md",
            "母差": "母差跳闸简报模板.md",
            "开关保护": "开关保护跳闸简报模板.md",
            "配电设备": "配电设备跳闸简报模板.md",
        }
        template_file = refs_dir / template_map.get(device_type, "线路跳闸简报模板.md")
        if template_file.exists():
            try:
                data["template"] = template_file.read_text(encoding="utf-8")[:8000]
            except Exception:
                pass

        return data

    async def _generate_report_with_llm(self, analysis_data: dict) -> str:
        """调用 LLM 生成故障分析报告。"""
        import json as _json

        # 读取配置
        config_path = Path.home() / ".protection" / "config.json"
        if not config_path.exists():
            config_path = Path.home() / ".nanobot" / "config.json"
        if not config_path.exists():
            raise FileNotFoundError("缺少配置文件 config.json，无法调用 LLM")

        config_data = _json.loads(config_path.read_text(encoding="utf-8"))
        default_model = config_data.get("agents", {}).get("defaults", {}).get("model", "glm-4-flash")

        providers = config_data.get("providers", {})
        provider = None
        for name in ["zhipu", "dashscope", "deepseek", "openai", "openrouter"]:
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
        if not provider or not provider.get("api_key"):
            raise ValueError("配置文件中未找到有效的 LLM provider")

        from webui.trip_briefing.llm.client import LLMClient

        llm_client = LLMClient(
            api_url=provider["base_url"],
            api_key=provider["api_key"],
            model=provider["model"],
            timeout=180,
            max_retries=3,
        )

        # 构造 prompt
        prompt_parts = [
            "你是一位电力系统继电保护专家，请根据以下录波分析数据生成故障分析报告。",
            f"\n设备类型: {analysis_data['device_type']}",
            f"电压等级: {analysis_data['voltage_level']}",
        ]

        template = analysis_data.get("template")
        if template:
            prompt_parts.append(f"\n## 报告模板（请严格按此格式生成）:\n{template}")

        for i, device in enumerate(analysis_data.get("devices", []), 1):
            prompt_parts.append(f"\n---\n## 装置 {i}: {device.get('device_name', '未知')}")
            prompt_parts.append(f"厂站: {device.get('station_name', '未知')}")

            hdr = device.get("hdr_info", {})
            if hdr:
                prompt_parts.append("\n### HDR 设备信息:")
                for k, v in hdr.items():
                    prompt_parts.append(f"- {k}: {v}")

            rms = device.get("rms_csv")
            if rms:
                prompt_parts.append(f"\n### RMS 统计数据:\n```csv\n{rms}\n```")

            events = device.get("events_csv")
            if events:
                prompt_parts.append(f"\n### 事件记录:\n```csv\n{events}\n```")

        prompt_parts.append(
            "\n\n请根据以上数据，按照模板格式生成完整的故障分析报告。"
            "报告必须包含：故障概况、保护动作分析、故障测距、录波波形分析等章节。"
            "对于无法确定的数据，请标注'[待核实]'。"
        )

        prompt = "\n".join(prompt_parts)

        # 调用 LLM（在线程池中执行避免阻塞）
        response = await asyncio.to_thread(
            llm_client.chat_completion,
            messages=[{"role": "user", "content": prompt}],
            model=provider["model"],
            max_tokens=8192,
        )

        if not response.success:
            raise RuntimeError(f"LLM 调用失败: {response.error_message}")

        report = response.content
        # 清理 code fence
        if report.startswith("```"):
            lines = report.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            report = "\n".join(lines)

        return report

    def _update_progress(self, job_id: str, progress: int, message: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET progress = ?, progress_message = ?, updated_at = ? WHERE id = ?",
                (progress, message, utcnow_iso(), job_id),
            )

    def _extract_all_archives(self, input_dir: Path, output_dir: Path):
        """递归解压所有压缩包（支持 zip/zwav/rar/7z），处理嵌套结构。"""
        import zipfile

        archive_exts = {'.zip', '.zwav', '.rar', '.7z', '.tar', '.gz', '.tgz'}
        processed: set[Path] = set()

        def _extract_zip(src: Path, dest: Path):
            """解压 ZIP/ZWAV 文件，自动处理 GBK 编码文件名。"""
            with zipfile.ZipFile(src, 'r') as zf:
                for name in zf.namelist():
                    try:
                        raw_bytes = name.encode('cp437')
                        real_name = raw_bytes.decode('gbk')
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        real_name = name
                    dest_path = dest / real_name
                    if name.endswith('/'):
                        dest_path.mkdir(parents=True, exist_ok=True)
                    else:
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as s, open(dest_path, 'wb') as d:
                            d.write(s.read())

        def _extract_once():
            """扫描 output_dir 中未处理的压缩包并解压，返回是否有新解压。"""
            found_new = False
            for arc in list(output_dir.rglob("*")):
                if not arc.is_file() or arc.suffix.lower() not in archive_exts:
                    continue
                if arc in processed:
                    continue
                processed.add(arc)
                suffix = arc.suffix.lower()
                try:
                    if suffix in {'.zip', '.zwav'}:
                        _extract_zip(arc, output_dir)
                    elif suffix == '.rar':
                        import subprocess
                        try:
                            subprocess.run(['unrar', 'x', '-o+', str(arc), str(output_dir)],
                                           check=True, capture_output=True)
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            try:
                                subprocess.run(['rar', 'x', '-o+', str(arc), str(output_dir)],
                                               check=True, capture_output=True)
                            except (subprocess.CalledProcessError, FileNotFoundError):
                                pass
                    elif suffix == '.7z':
                        import subprocess
                        try:
                            subprocess.run(['7z', 'x', f'-o{output_dir}', '-y', str(arc)],
                                           check=True, capture_output=True)
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            pass
                    print(f"  [解压] {arc.name}")
                    found_new = True
                except Exception as e:
                    print(f"  [解压失败] {arc.name}: {e}")
            return found_new

        # 复制 input_dir 中的压缩包到 output_dir
        import shutil as _shutil
        for f in input_dir.iterdir():
            if f.is_file() and f.suffix.lower() in archive_exts:
                _shutil.copy2(f, output_dir / f.name)

        # 循环解压直到没有新的压缩包（处理嵌套：zip→zwav→cfg/dat/hdr）
        for _ in range(10):  # 最多 10 层，防止意外
            if not _extract_once():
                break

        # 如果 input_dir 中直接有 cfg/dat/hdr（非压缩包上传），复制到 output_dir
        for ext in ['*.cfg', '*.CFG', '*.dat', '*.DAT', '*.hdr', '*.HDR']:
            for f in input_dir.glob(ext):
                dest = output_dir / f.name
                if not dest.exists():
                    _shutil.copy2(f, dest)

    def update_evaluation(self, job_id: str, evaluation: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE jobs SET evaluation = ?, updated_at = ? WHERE id = ?",
                (evaluation, utcnow_iso(), job_id),
            )

    def delete_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False

        # 删除文件
        job_dir = self.jobs_dir / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)

        # 删除数据库记录
        with self._conn() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

        return True

    def get_report_content(self, job_id: str) -> str | None:
        job = self.get_job(job_id)
        if not job or not job.get("result_relative_path"):
            return None

        report_path = Path(job["result_relative_path"])
        if not report_path.exists():
            return None

        return report_path.read_text(encoding="utf-8")

    def get_report_path(self, job_id: str) -> Path | None:
        job = self.get_job(job_id)
        if not job or not job.get("result_relative_path"):
            return None

        report_path = Path(job["result_relative_path"])
        return report_path if report_path.exists() else None

    def export_jobs(self, job_ids: list[str]) -> io.BytesIO | None:
        zip_buffer = io.BytesIO()
        has_files = False

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for job_id in job_ids:
                job = self.get_job(job_id)
                if not job or not job.get("result_relative_path"):
                    continue

                report_path = Path(job["result_relative_path"])
                if report_path.exists():
                    arcname = f"{job.get('station', 'unknown')}_{job.get('device', '')}_{job_id}.md"
                    zf.write(report_path, arcname)
                    has_files = True

        if not has_files:
            return None

        zip_buffer.seek(0)
        return zip_buffer

    def _row_to_dict(self, row) -> dict:
        if row is None:
            return {}

        _str_fields = [
            "station", "device", "device_type", "voltage_level", "folder_path",
        ]

        if hasattr(row, "keys"):
            d = dict(row)
        else:
            d = {
                "id": row[0], "status": row[1], "created_at": row[2],
                "updated_at": row[3], "created_by": row[4], "error_message": row[5],
                "station": row[6], "device": row[7], "device_type": row[8],
                "voltage_level": row[9], "folder_path": row[10],
                "result_file_name": row[11], "result_relative_path": row[12],
                "result_download_token": row[13], "result_mime_type": row[14],
                "result_file_size": row[15], "progress": row[16],
                "progress_message": row[17], "evaluation": row[18],
            }

        for k in _str_fields:
            if d.get(k) is None:
                d[k] = ""

        # 添加下载和预览 URL
        if d.get("result_download_token"):
            d["download_url"] = f"/api/fault-analysis/jobs/{d['id']}/download"
            d["preview_url"] = f"/api/fault-analysis/jobs/{d['id']}/preview"

        return d
