from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import time

from fastapi import UploadFile

from webui.api.files import generate_download_token
from webui.services.agentplayground.db import connect, row_to_dict, utcnow_iso
from webui.services.agentplayground.models import APP_ID_WAVE_RECORD_PARSER

INTERRUPTED_RESTART_MESSAGE = "服务重启导致任务中断，请重新提交"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    created_by TEXT,
    error_message TEXT,
    file_name TEXT NOT NULL,
    cfg_file_name TEXT,
    dat_file_name TEXT,
    hdr_file_name TEXT,
    result_file_name TEXT,
    result_relative_path TEXT,
    result_download_token TEXT UNIQUE,
    result_mime_type TEXT,
    result_file_size INTEGER,
    station TEXT,
    device TEXT,
    device_type TEXT,
    progress INTEGER DEFAULT 0,
    progress_message TEXT,
    evaluation TEXT
);

CREATE INDEX IF NOT EXISTS idx_wave_jobs_created_at
    ON jobs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_wave_jobs_status_created_at
    ON jobs (status, created_at);
"""


def parse_cfg_file(cfg_path: Path) -> dict[str, Any]:
    """Parse COMTRADE .CFG configuration file."""
    result = {
        "station_name": "",
        "device_name": "",
        "version": "1999",
        "total_channels": 0,
        "analog_channels": 0,
        "digital_channels": 0,
        "channels": [],
        "sample_rate": 0,
        "total_samples": 0,
        "start_time": "",
        "trigger_time": "",
        "data_type": "BINARY",
    }

    try:
        with open(cfg_path, encoding="gbk", errors="ignore") as f:
            lines = f.readlines()

        if len(lines) < 2:
            return result

        # First line: station_name, device_name, version
        first_line = lines[0].strip().split(",")
        result["station_name"] = first_line[0].strip() if len(first_line) > 0 else ""
        result["device_name"] = first_line[1].strip() if len(first_line) > 1 else ""
        result["version"] = first_line[2].strip() if len(first_line) > 2 else "1999"

        # Second line: total_channels, analog_channels, digital_channels
        # Format can be: "191,65A,126D" or "191,65,126"
        second_line = lines[1].strip().split(",")
        if len(second_line) >= 1:
            total_str = second_line[0].strip()
            result["total_channels"] = int(total_str) if total_str.isdigit() else 0

        if len(second_line) >= 2:
            analog_str = second_line[1].strip().rstrip("Aa")
            result["analog_channels"] = int(analog_str) if analog_str.isdigit() else 0

        if len(second_line) >= 3:
            digital_str = second_line[2].strip().rstrip("Dd")
            result["digital_channels"] = int(digital_str) if digital_str.isdigit() else 0

        # Parse analog channels (lines 3 to 3+analog_channels-1)
        channels = []
        for i in range(result["analog_channels"]):
            line_idx = 2 + i
            if line_idx < len(lines):
                parts = lines[line_idx].strip().split(",")
                if len(parts) >= 6:
                    channels.append({
                        "index": int(parts[0].strip()) if parts[0].strip().isdigit() else i + 1,
                        "name": parts[1].strip() if len(parts) > 1 else f"AN{i+1}",
                        "phase": parts[2].strip() if len(parts) > 2 else "",
                        "component": parts[3].strip() if len(parts) > 3 else "",
                        "units": parts[4].strip() if len(parts) > 4 else "",
                        "a": float(parts[5].strip()) if len(parts) > 5 and parts[5].strip() else 1.0,
                        "b": float(parts[6].strip()) if len(parts) > 6 and parts[6].strip() else 0.0,
                    })
        result["channels"] = channels

        # Parse sample rate and total samples
        line_idx = 2 + result["analog_channels"] + result["digital_channels"]
        if line_idx < len(lines):
            parts = lines[line_idx].strip().split(",")
            result["sample_rate"] = int(float(parts[0].strip())) if len(parts) > 0 and parts[0].strip() else 0
            result["total_samples"] = int(float(parts[1].strip())) if len(parts) > 1 and parts[1].strip() else 0

        # Parse start time and trigger time
        line_idx += 1
        if line_idx < len(lines):
            result["start_time"] = lines[line_idx].strip().replace(",", " ")
        line_idx += 1
        if line_idx < len(lines):
            result["trigger_time"] = lines[line_idx].strip().replace(",", " ")

    except Exception:
        pass

    return result


def parse_hdr_file(hdr_path: Path) -> dict[str, Any]:
    """Parse HDR XML fault report file."""
    result = {
        "device_info": {},
        "fault_info": {},
        "trip_info": [],
        "digital_events": [],
        "ct_pt_analysis": {},
    }

    try:
        tree = ET.parse(hdr_path)
        root = tree.getroot()

        # Parse DeviceInfo elements (name/value pairs)
        for device_info in root.findall("DeviceInfo"):
            name_elem = device_info.find("name")
            value_elem = device_info.find("value")
            if name_elem is not None and value_elem is not None:
                name = name_elem.text or ""
                value = value_elem.text or ""
                result["device_info"][name] = value

        # Parse FaultInfo elements (name/value pairs with optional unit)
        for fault_info in root.findall("FaultInfo"):
            name_elem = fault_info.find("name")
            value_elem = fault_info.find("value")
            unit_elem = fault_info.find("unit")
            if name_elem is not None and value_elem is not None:
                name = name_elem.text or ""
                value = value_elem.text or ""
                unit = unit_elem.text if unit_elem is not None else ""
                if unit:
                    result["fault_info"][name] = f"{value} {unit}"
                else:
                    result["fault_info"][name] = value

        # Parse TripInfo elements
        trip_infos = root.findall(".//TripInfo")
        for trip in trip_infos:
            trip_data = {}
            for child in trip:
                if child.text:
                    trip_data[child.tag] = child.text
            if trip_data:
                result["trip_info"].append(trip_data)

        # Parse digital events
        digital_events = root.findall(".//DigitalEvent")
        for event in digital_events:
            event_data = {}
            for child in event:
                if child.text:
                    event_data[child.tag] = child.text
            if event_data:
                result["digital_events"].append(event_data)

        # Parse CT/PT analysis
        ct_pt = root.find("CTPTAnalysis")
        if ct_pt is not None:
            for child in ct_pt:
                if child.text:
                    result["ct_pt_analysis"][child.tag] = child.text

    except Exception:
        pass

    return result


def generate_analysis_report(job_root: Path, cfg_data: dict, hdr_data: dict) -> Path:
    """Generate analysis report in Markdown format."""
    report_path = job_root / "analysis_report.md"

    lines = [
        "# 录波文件分析报告",
        "",
        "## 基本信息",
        "",
        f"- **站名**: {cfg_data.get('station_name', 'N/A')}",
        f"- **设备名**: {cfg_data.get('device_name', 'N/A')}",
        f"- **录波版本**: {cfg_data.get('version', 'N/A')}",
        f"- **采样率**: {cfg_data.get('sample_rate', 'N/A')} Hz",
        f"- **总采样点**: {cfg_data.get('total_samples', 'N/A')}",
        f"- **开始时间**: {cfg_data.get('start_time', 'N/A')}",
        f"- **触发时间**: {cfg_data.get('trigger_time', 'N/A')}",
        "",
        "## 通道配置",
        "",
        f"- **模拟通道数**: {cfg_data.get('analog_channels', 0)}",
        f"- **数字通道数**: {cfg_data.get('digital_channels', 0)}",
        "",
    ]

    channels = cfg_data.get("channels", [])
    if channels:
        lines.append("### 模拟通道列表")
        lines.append("")
        lines.append("| 序号 | 名称 | 相位 | 单位 |")
        lines.append("|------|------|------|------|")
        for ch in channels[:20]:  # Limit to first 20 channels
            lines.append(f"| {ch.get('index', '')} | {ch.get('name', '')} | {ch.get('phase', '')} | {ch.get('units', '')} |")
        if len(channels) > 20:
            lines.append(f"| ... | (共 {len(channels)} 个通道) | | |")
        lines.append("")

    # Add device info from HDR if available
    device_info = hdr_data.get("device_info", {})
    if device_info:
        lines.extend([
            "## 设备信息",
            "",
        ])
        for name, value in device_info.items():
            lines.append(f"- **{name}**: {value}")
        lines.append("")

    # Add fault info from HDR if available
    fault_info = hdr_data.get("fault_info", {})
    if fault_info:
        lines.extend([
            "## 故障信息",
            "",
        ])
        for name, value in fault_info.items():
            lines.append(f"- **{name}**: {value}")
        lines.append("")

    trip_info = hdr_data.get("trip_info", [])
    if trip_info:
        lines.extend([
            "## 跳闸信息",
            "",
        ])
        for trip in trip_info:
            for key, value in trip.items():
                lines.append(f"- **{key}**: {value}")
        lines.append("")

    digital_events = hdr_data.get("digital_events", [])
    if digital_events:
        lines.extend([
            "## 数字事件",
            "",
        ])
        for event in digital_events[:50]:  # Limit to first 50 events
            event_str = " | ".join(f"{k}: {v}" for k, v in event.items())
            lines.append(f"- {event_str}")
        if len(digital_events) > 50:
            lines.append(f"- ... (共 {len(digital_events)} 个事件)")
        lines.append("")

    ct_pt_analysis = hdr_data.get("ct_pt_analysis", {})
    if ct_pt_analysis:
        lines.extend([
            "## CT/PT 分析",
            "",
        ])
        for key, value in ct_pt_analysis.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    lines.extend([
        "---",
        f"*报告生成时间: {utcnow_iso()}*",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def execute_job(app_root: Path, job_id: str, progress_callback: Any = None) -> Path:
    """Execute wave record parsing job.

    Args:
        app_root: Application root directory
        job_id: Job ID
        progress_callback: Optional callback function(progress: int, message: str)
    """
    job_root = app_root / "jobs" / job_id
    inputs_dir = job_root / "inputs"

    # Read manifest to get device_type
    manifest_path = job_root / "inputs.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    device_type = manifest.get("device_type", "line")

    # Find uploaded files
    cfg_file = None
    dat_file = None
    hdr_file = None
    zip_file = None

    for f in inputs_dir.iterdir():
        if f.is_file():
            ext = f.suffix.lower()
            if ext == ".cfg":
                cfg_file = f
            elif ext == ".dat":
                dat_file = f
            elif ext == ".hdr":
                hdr_file = f
            elif ext == ".zip":
                zip_file = f

    # If zip file exists, use trip_briefing pipeline
    if zip_file:
        return execute_trip_briefing(job_root, zip_file, device_type, progress_callback)

    # Otherwise, use simple analysis (requires cfg file)
    if not cfg_file:
        raise FileNotFoundError("缺少必需的 .CFG 配置文件")

    # Parse files
    cfg_data = parse_cfg_file(cfg_file)
    hdr_data = {}
    if hdr_file:
        hdr_data = parse_hdr_file(hdr_file)

    # Generate report
    report_path = generate_analysis_report(job_root, cfg_data, hdr_data)

    if not report_path.exists():
        raise FileNotFoundError("报告生成失败")

    return report_path


def execute_trip_briefing(job_root: Path, zip_file: Path, device_type: str, progress_callback: Any = None) -> Path:
    """Execute trip_briefing pipeline for zip file.

    Args:
        job_root: Job root directory
        zip_file: Path to the zip file
        device_type: Device type (line/transformer/bus)
        progress_callback: Optional callback function(progress: int, message: str)
    """
    from webui.trip_briefing.config import create_config_from_provider
    from webui.trip_briefing.pipeline import run_pipeline

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
        # Fallback to .nanobot for backward compatibility
        config_path = Path.home() / ".nanobot" / "config.json"

    if not config_path.exists():
        raise FileNotFoundError("缺少配置文件 config.json，无法调用 LLM")

    config_data = json.loads(config_path.read_text(encoding="utf-8"))

    # 从 agents.defaults.model 获取默认模型名
    default_model = config_data.get("agents", {}).get("defaults", {}).get("model", "qwen3.5-flash")

    # Handle both dict and list format for providers
    providers = config_data.get("providers", {})
    if isinstance(providers, dict):
        # Dict format: prefer zhipu/dashscope for OpenAI compatibility, then find first with api_key
        provider = None
        # Priority order for OpenAI-compatible endpoints
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
        # Fallback: find first provider with api_key
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
    elif isinstance(providers, list):
        # List format
        if not providers:
            raise ValueError("配置文件中未找到 providers")
        provider = providers[0]
    else:
        raise ValueError("配置文件格式错误")

    api_url = provider.get("base_url", "")
    api_key = provider.get("api_key", "")
    model = provider.get("model", default_model)

    if not api_key:
        raise ValueError("配置文件中未找到 API key")

    report_progress(10, "正在创建 LLM 配置...")

    # Create pipeline config
    pipeline_config = create_config_from_provider(
        api_url=api_url,
        api_key=api_key,
        model=model,
    )

    report_progress(15, "正在解压文件...")

    # Prepare input directory (extract zip)
    input_dir = job_root / "extracted"
    input_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_file, 'r') as zf:
        zf.extractall(input_dir)
        # 修复 Windows 创建的 zip 中文文件名在 Linux 上的 GBK 乱码
        from webui.trip_briefing.pipeline import _fix_zip_encoding
        _fix_zip_encoding(input_dir, zf)

    report_progress(20, "正在准备输出目录...")

    # Output directory
    output_dir = job_root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    report_progress(25, "正在运行解析脚本...")

    # Run pipeline with progress tracking
    exit_code = run_pipeline(
        input_dir=input_dir,
        output_dir=output_dir,
        device_type=device_type,
        config=pipeline_config,
        progress_callback=report_progress,
    )

    report_progress(95, "正在查找生成结果...")

    # Find the briefing file
    briefing_path = output_dir / "跳闸简报.md"
    if not briefing_path.exists():
        # If pipeline failed, check for partial results
        paragraphs_dir = output_dir / "段落"
        if paragraphs_dir.exists():
            # Combine paragraphs into a simple report
            lines = ["# 录波分析报告（部分结果）", ""]
            for para_file in sorted(paragraphs_dir.glob("*.md")):
                content = para_file.read_text(encoding="utf-8")
                lines.append(content)
                lines.append("")
            report_path = job_root / "analysis_report.md"
            report_path.write_text("\n".join(lines), encoding="utf-8")
            return report_path
        raise FileNotFoundError(f"跳闸简报生成失败 (exit_code={exit_code})")

    return briefing_path


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
            "created_at": time.time(),
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
        received = set(meta.get("received_chunks", []))

        missing = set(range(total_chunks)) - received
        if missing:
            raise ValueError(f"Missing chunks: {sorted(missing)}")

        file_name = meta["file_name"]
        output_path = upload_dir / file_name
        chunks_dir = upload_dir / "chunks"

        with open(output_path, "wb") as out:
            for i in range(total_chunks):
                chunk_path = chunks_dir / f"{i:06d}"
                out.write(chunk_path.read_bytes())

        return output_path

    def cleanup(self, upload_id: str) -> None:
        upload_dir = self._uploads_dir / upload_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    def get_status(self, upload_id: str) -> dict[str, Any] | None:
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


class WaveRecordParserService:
    app_id = APP_ID_WAVE_RECORD_PARSER

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
                from webui.services.agentplayground.paths import default_wave_record_parser_app_root

                app_root = default_wave_record_parser_app_root(workspace)
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
            # Migration: add progress columns if they don't exist
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress INTEGER DEFAULT 0")
            except Exception:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN progress_message TEXT")
            except Exception:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN evaluation TEXT")
            except Exception:
                pass  # Column already exists
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
        files: list[UploadFile],
        *,
        station: str | None = None,
        device: str | None = None,
        device_type: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        file_bytes_list = []
        file_names = []
        for upload_file in files:
            file_bytes = await upload_file.read()
            file_bytes_list.append(file_bytes)
            file_names.append(Path(upload_file.filename or "upload").name)

        return self._create_job_from_bytes(
            file_names=file_names,
            file_bytes_list=file_bytes_list,
            station=station,
            device=device,
            device_type=device_type,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    async def create_job_from_chunked_upload(
        self,
        upload_id: str,
        *,
        station: str | None = None,
        device: str | None = None,
        device_type: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        file_path = self.chunked_upload.assemble_file(upload_id)
        file_name = file_path.name
        file_bytes = file_path.read_bytes()
        self.chunked_upload.cleanup(upload_id)

        return self._create_job_from_bytes(
            file_names=[file_name],
            file_bytes_list=[file_bytes],
            station=station,
            device=device,
            device_type=device_type,
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
                    file_name,
                    cfg_file_name,
                    dat_file_name,
                    hdr_file_name,
                    result_file_name,
                    result_relative_path,
                    result_download_token,
                    station,
                    device,
                    device_type,
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
                    file_name,
                    cfg_file_name,
                    dat_file_name,
                    hdr_file_name,
                    result_file_name,
                    result_relative_path,
                    result_download_token,
                    station,
                    device,
                    device_type,
                    progress,
                    progress_message,
                    evaluation
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None

    def mark_processing(self, job_id: str) -> None:
        self._update_job_status(job_id, "processing", None)

    def update_progress(self, job_id: str, progress: int, message: str | None = None) -> None:
        """Update job progress (0-100)."""
        self.initialize()
        now = utcnow_iso()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE jobs
                SET updated_at = ?, progress = ?, progress_message = ?
                WHERE id = ?
                """,
                (now, min(100, max(0, progress)), message, job_id),
            )

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
                    result_file_size = ?,
                    progress = 100,
                    progress_message = ?
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
                    "解析完成",
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
            "id": f"wrp_{token}",
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
                    # Create progress callback that updates the job
                    def progress_callback(progress: int, message: str) -> None:
                        self.update_progress(job_id, progress, message)

                    result_path = await asyncio.to_thread(
                        execute_job, self.app_root, job_id, progress_callback
                    )
                except Exception as exc:
                    self.mark_failed(job_id, str(exc))
                    continue
                self.mark_completed(job_id, result_path)

    def start_queue(self) -> None:
        self._schedule_queue()

    def _create_job_from_bytes(
        self,
        *,
        file_names: list[str],
        file_bytes_list: list[bytes],
        station: str | None,
        device: str | None,
        device_type: str | None,
        created_by: str | None,
        run_in_background: bool,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job_root = self._job_root(job_id)
        job_root.mkdir(parents=True, exist_ok=True)
        inputs_dir = job_root / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        cfg_name = None
        dat_name = None
        hdr_name = None
        zip_name = None
        primary_name = None

        for name, data in zip(file_names, file_bytes_list, strict=True):
            safe_name = self._safe_upload_name(name, "upload")
            dest = inputs_dir / safe_name
            dest.write_bytes(data)

            ext = Path(safe_name).suffix.lower()
            if ext == ".cfg":
                cfg_name = safe_name
                if primary_name is None:
                    primary_name = Path(safe_name).stem
            elif ext == ".dat":
                dat_name = safe_name
            elif ext == ".hdr":
                hdr_name = safe_name
            elif ext == ".zip":
                zip_name = safe_name
                if primary_name is None:
                    primary_name = Path(safe_name).stem

        if primary_name is None:
            primary_name = file_names[0] if file_names else "wave_record"

        # 使用厂站+装置作为显示文件名
        if station and device:
            primary_name = f"{station}-{device}"
        elif station:
            primary_name = station
        elif device:
            primary_name = device

        self._write_inputs_manifest(
            job_id,
            file_names=file_names,
            cfg_name=cfg_name,
            dat_name=dat_name,
            hdr_name=hdr_name,
            zip_name=zip_name,
            device_type=device_type,
        )

        return self._persist_created_job(
            job_id=job_id,
            file_name=primary_name,
            cfg_name=cfg_name,
            dat_name=dat_name,
            hdr_name=hdr_name,
            zip_name=zip_name,
            station=station,
            device=device,
            device_type=device_type,
            created_by=created_by,
            run_in_background=run_in_background,
        )

    def _persist_created_job(
        self,
        *,
        job_id: str,
        file_name: str,
        cfg_name: str | None,
        dat_name: str | None,
        hdr_name: str | None,
        zip_name: str | None,
        station: str | None,
        device: str | None,
        device_type: str | None,
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
                    file_name,
                    cfg_file_name,
                    dat_file_name,
                    hdr_file_name,
                    station,
                    device,
                    device_type
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, "queued", now, now, created_by, file_name, cfg_name, dat_name, hdr_name, station, device, device_type or "line"),
            )

        if run_in_background:
            self._schedule_queue()

        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Failed to load created wave record job: {job_id}")
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

    def _write_inputs_manifest(
        self,
        job_id: str,
        *,
        file_names: list[str],
        cfg_name: str | None,
        dat_name: str | None,
        hdr_name: str | None,
        zip_name: str | None = None,
        device_type: str | None = None,
    ) -> None:
        manifest = {
            "files": file_names,
            "cfg_file": cfg_name,
            "dat_file": dat_name,
            "hdr_file": hdr_name,
            "zip_file": zip_name,
            "device_type": device_type or "line",
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
            "file_name": row["file_name"],
            "result_file_name": row.get("result_file_name") if downloadable else None,
            "download_url": f"/api/files/d/{token}" if downloadable else None,
            "station": row.get("station"),
            "device": row.get("device"),
            "device_type": row.get("device_type"),
            "progress": row.get("progress") or 0,
            "progress_message": row.get("progress_message"),
            "evaluation": row.get("evaluation") or "",
        }

    def update_job_evaluation(self, job_id: str, evaluation: str) -> dict[str, Any] | None:
        self.initialize()
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE jobs SET evaluation = ?, updated_at = ? WHERE id = ?",
                (evaluation, utcnow_iso(), job_id),
            )
            row = conn.execute(
                """
                SELECT
                    id, status, created_at, updated_at, error_message, file_name,
                    cfg_file_name, dat_file_name, hdr_file_name,
                    result_file_name, result_relative_path, result_download_token,
                    station, device, device_type, progress, progress_message, evaluation
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None
