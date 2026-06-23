from __future__ import annotations

import asyncio
import io
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
    evaluation TEXT,
    external_id TEXT
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


# 设备类型映射：中文 → 英文
_EQUIP_TYPE_MAP = {
    "线路": "line",
    "主变": "transformer",
    "变压器": "transformer",
    "母线": "bus",
    "母差": "bus",
}


def parse_fault_event_md(md_path: Path) -> dict[str, str]:
    """解析 _故障事件信息.md 文件，提取结构化字段。

    返回 dict，包含 id, equipmentName, equipType 等字段。
    """
    result: dict[str, str] = {}
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            text = md_path.read_text(encoding="gb18030", errors="ignore")
        except Exception:
            return result

    import re
    # 匹配 Markdown 表格行: | key | value |（跳过分隔行 |---|---|）
    for m in re.finditer(r"^\|\s*([^|\s]+)\s*\|\s*(.+?)\s*\|", text, re.MULTILINE):
        key = m.group(1).strip()
        value = m.group(2).strip()
        if key and value:
            result[key] = value

    return result


def _equip_type_to_device_type(equip_type: str) -> str:
    """将中文设备类型转为英文 device_type。"""
    for zh, en in _EQUIP_TYPE_MAP.items():
        if zh in equip_type:
            return en
    return "line"


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
        result = execute_trip_briefing(job_root, zip_file, device_type, progress_callback)
        # Copy briefing outputs to workspace for AI access
        try:
            _copy_briefing_to_workspace(job_root, app_root, zip_file.name)
        except Exception as e:
            print(f"[工作区] 复制简报到工作区失败: {e}", flush=True)
        return result

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


def _reorganize_flat_subdir(subdir: Path) -> None:
    """将子目录下扁平的装置文件按设备名分组到子子目录中。

    适配内层ZIP解压后文件直接放在保护录波/或故障录波/下、无厂站/套别层级的情况。
    文件名模式: {DEVICE}_RCD_{N}_{DATE}_{TIME}_{SEQ}_{TYPE}.EXT
    """
    import re

    DEVICE_FILE_EXTS = {".cfg", ".dat", ".hdr", ".rms.csv", ".events.csv", ".inf", ".ana", ".dmf", ".rpt", ".des", ".mid"}
    groups: dict[str, list[Path]] = {}  # device_name -> [files]

    for f in sorted(subdir.iterdir()):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        is_device_file = ext in DEVICE_FILE_EXTS or f.name.lower().endswith(('.rms.csv', '.events.csv'))
        if not is_device_file:
            continue
        # 尝试从文件名提取设备名
        m = re.match(r'^(.+?)_RCD_\d+_\d{8}_\d{6}_\d+_[FS]', f.stem, re.IGNORECASE)
        if m:
            device_name = m.group(1)
        else:
            # 其他模式：用第一个下划线前的部分，或整个文件名去掉扩展名
            device_name = f.stem.split('_')[0] if '_' in f.stem else f.stem
        groups.setdefault(device_name, []).append(f)

    if not groups:
        return

    print(f"[重组] {subdir.name}: 检测到 {len(groups)} 组扁平装置文件，自动创建子目录...", flush=True)
    for device_name, files in groups.items():
        target_dir = subdir / device_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = target_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
        print(f"[重组] {device_name}: {len(files)} 个文件 -> {target_dir.relative_to(subdir.parent)}", flush=True)


def _reorganize_flat_device_files(input_dir: Path, station_name: str) -> None:
    """将扁平的装置文件自动组织到 保护录波/故障录波 目录结构中。

    适配内层ZIP直接包含COMTRADE文件、无标准目录结构的情况。
    文件名模式: {DEVICE}_RCD_{N}_{DATE}_{TIME}_{SEQ}_{TYPE}.EXT
    - TYPE = F → 保护录波
    - TYPE = S → 故障录波

    每个内层ZIP代表一组录波数据，以ZIP文件名（去掉扩展名）作为目录名。
    """
    import re

    DEVICE_FILE_EXTS = {".cfg", ".dat", ".hdr", ".rms.csv", ".events.csv", ".inf", ".ana", ".dmf", ".rpt"}
    # 按ZIP来源分组：用文件名去掉扩展名作为key
    zip_groups: dict[str, dict[str, Any]] = {}  # key: zip_base_name -> {type, device, files}

    for f in sorted(input_dir.iterdir()):
        if not f.is_file():
            continue
        # 匹配 {DEVICE}_RCD_{N}_{DATE}_{TIME}_{SEQ}_{TYPE}.EXT 模式
        m = re.match(r'^(.+?_RCD_\d+_\d{8}_\d{6}_\d+_[FS])\.(.+)$', f.name, re.IGNORECASE)
        if not m:
            continue
        base_name = m.group(1)  # e.g. SH11841A_RCD_742_20260213_035402_165_F
        ext = f".{m.group(2)}".lower()
        if ext not in DEVICE_FILE_EXTS and not f.name.lower().endswith(('.rms.csv', '.events.csv')):
            continue
        # 从 base_name 提取设备名和类型
        dm = re.match(r'^(.+?)_RCD_\d+_\d{8}_\d{6}_\d+_([FS])$', base_name, re.IGNORECASE)
        if not dm:
            continue
        device_name = dm.group(1)
        file_type = dm.group(2).upper()
        if base_name not in zip_groups:
            zip_groups[base_name] = {"device": device_name, "type": file_type, "files": []}
        zip_groups[base_name]["files"].append(f)

    if not zip_groups:
        return

    # 推断厂站名：优先用包裹目录名，否则用 md 文件中的 equipmentName
    station = station_name
    if not station:
        for f in input_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".md" and "故障事件" in f.name:
                meta = parse_fault_event_md(f)
                station = meta.get("equipmentName", "")
                break
    if not station:
        station = input_dir.name

    print(f"[重组] 检测到 {len(zip_groups)} 组扁平装置文件，自动创建标准目录结构...", flush=True)

    for base_name, info in zip_groups.items():
        device_name = info["device"]
        file_type = info["type"]
        files = info["files"]

        if file_type == "S":
            # 故障录波: 故障录波/厂站/录波名/
            target_dir = input_dir / "故障录波" / station / base_name
        else:
            # 保护录波: 保护录波/厂站/装置名/（装置名作为套别）
            target_dir = input_dir / "保护录波" / station / device_name

        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            dest = target_dir / f.name
            if not dest.exists():
                shutil.move(str(f), str(dest))
        print(f"[重组] {file_type}: {base_name} -> {target_dir.relative_to(input_dir)}", flush=True)


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

    # 自动展开多余的包裹目录层（先展开，再解压内层ZIP）
    # 用户打包时可能多套了一层目录，如: zip → 事故名/ → 保护录波/
    # 这里检测并自动修正，最多向下查找 3 层
    from webui.trip_briefing.pipeline import _unwrap_single_child_dirs
    EXPECTED_DIRS = {"保护录波", "故障录波"}
    wrapper_dir_name = ""  # 保存包裹目录名，用于后续推断厂站名
    for _depth in range(3):
        current_names = {p.name for p in input_dir.iterdir() if p.is_dir()}
        if current_names & EXPECTED_DIRS:
            break  # 已找到目标目录
        # 只有一个子目录时才展开（避免误移正常结构）
        sub_dirs = [p for p in input_dir.iterdir() if p.is_dir()]
        if len(sub_dirs) == 1:
            wrapper = sub_dirs[0]
            wrapper_dir_name = wrapper.name  # 保存包裹目录名（可能是厂站名）
            print(f"[解压] 检测到多余包裹目录: {wrapper.name}/，正在展开...", flush=True)
            # 将包裹目录内的所有内容移到 input_dir
            for item in wrapper.iterdir():
                dest = input_dir / item.name
                if dest.exists():
                    # 目标已存在，跳过
                    continue
                shutil.move(str(item), str(dest))
            # 删除空的包裹目录
            try:
                wrapper.rmdir()
            except OSError:
                pass  # 非空则保留
        else:
            break  # 多个子目录，不做自动展开

    # 解压内层嵌套的 ZIP 文件（保护录波/故障录波目录下的装置 ZIP）
    from webui.trip_briefing.pipeline import _find_zip_files
    inner_zips = _find_zip_files(input_dir)
    inner_zip_errors: list[str] = []
    for inner_zip in inner_zips:
        # 跳过 0 字节的空文件
        if inner_zip.stat().st_size == 0:
            inner_zip_errors.append(f"{inner_zip.name}（文件为空，0字节）")
            inner_zip.unlink()
            print(f"[解压] 跳过空文件: {inner_zip.name}", flush=True)
            continue
        target_dir = inner_zip.parent
        try:
            with zipfile.ZipFile(inner_zip, 'r') as zf:
                zf.extractall(target_dir)
                _fix_zip_encoding(target_dir, zf)
            _unwrap_single_child_dirs(target_dir)
            inner_zip.unlink()  # 解压后删除内层 ZIP
            print(f"[解压] 内层ZIP: {inner_zip.name} -> {target_dir}", flush=True)
        except Exception as e:
            inner_zip_errors.append(f"{inner_zip.name}（{e}）")
            print(f"[解压] 内层ZIP失败: {inner_zip.name}: {e}", flush=True)

    # ── 兼容扁平内层ZIP结构 ──
    # 如果解压后没有 保护录波/故障录波 目录，但存在扁平的装置文件，
    # 自动按文件名模式分组并创建标准目录结构
    has_protect_now = (input_dir / "保护录波").is_dir()
    has_fault_now = (input_dir / "故障录波").is_dir()
    if not has_protect_now and not has_fault_now:
        _reorganize_flat_device_files(input_dir, wrapper_dir_name)

    # ── 目录名规范化 ──
    # 兼容 "故障录波器录波" 等非标准目录名，重命名为标准名
    for d in list(input_dir.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if "故障录波" in name and name != "故障录波":
            dest = input_dir / "故障录波"
            if not dest.exists():
                d.rename(dest)
                print(f"[规范化] {name} -> 故障录波", flush=True)
        elif "保护录波" in name and name != "保护录波":
            dest = input_dir / "保护录波"
            if not dest.exists():
                d.rename(dest)
                print(f"[规范化] {name} -> 保护录波", flush=True)

    # ── 扁平子目录重组 ──
    # 内层ZIP解压后文件可能直接放在保护录波/或故障录波/下（无厂站/套别层级），
    # 按设备名自动分组到子目录中
    for subdir_name in ("保护录波", "故障录波"):
        subdir = input_dir / subdir_name
        if subdir.is_dir():
            _reorganize_flat_subdir(subdir)

    # ── 验证 ZIP 内容结构 ──
    report_progress(20, "正在验证文件结构...")

    has_protect = (input_dir / "保护录波").is_dir()
    has_fault = (input_dir / "故障录波").is_dir()

    if not has_protect and not has_fault:
        # 列出实际目录帮助用户排查
        actual = [p.name for p in input_dir.iterdir() if p.is_dir()]
        actual_str = "、".join(actual[:10]) if actual else "（空）"
        detail = ""
        if inner_zip_errors:
            detail = f"。内层压缩包解压失败：{'、'.join(inner_zip_errors[:5])}"
        raise ValueError(
            f"压缩包内未找到「保护录波」或「故障录波」目录。"
            f"实际目录：{actual_str}{detail}。"
            f"请确认压缩包结构正确（应包含 保护录波/ 或 故障录波/ 目录）"
        )

    # 检查每个子目录下是否有装置文件
    from webui.trip_briefing.pipeline import scan_devices
    errors = []
    if has_protect:
        devices = scan_devices(input_dir, sub_dir="保护录波")
        if not devices:
            # 兼容 .ZWAV 等非标准压缩包（后续 prepare_work_dir 会解压）
            protect_dir = input_dir / "保护录波"
            has_zwav = any(
                f.is_file() and f.suffix.lower() in (".zwav", ".zip")
                for f in protect_dir.rglob("*")
            )
            if not has_zwav:
                sub_names = [p.name for p in protect_dir.iterdir() if p.is_dir()]
                sub_str = "、".join(sub_names[:10]) if sub_names else "（空）"
                errors.append(f"「保护录波」目录下未找到有效的装置文件（子目录：{sub_str}）")
    if has_fault:
        devices = scan_devices(input_dir, sub_dir="故障录波")
        if not devices:
            # 兼容 .ZWAV 等非标准压缩包
            fault_dir = input_dir / "故障录波"
            has_zwav = any(
                f.is_file() and f.suffix.lower() in (".zwav", ".zip")
                for f in fault_dir.rglob("*")
            )
            if not has_zwav:
                sub_names = [p.name for p in fault_dir.iterdir() if p.is_dir()]
                sub_str = "、".join(sub_names[:10]) if sub_names else "（空）"
                errors.append(f"「故障录波」目录下未找到有效的装置文件（子目录：{sub_str}）")

    if errors:
        raise ValueError("；".join(errors) + "。每个装置目录下需包含 .hdr / .cfg / .rms.csv / .events.csv 中至少一种文件")

    report_progress(22, "正在准备输出目录...")

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
            if exit_code != 0:
                raise RuntimeError(f"跳闸简报生成失败（可能超时），已保留部分段落结果")
            return report_path
        raise FileNotFoundError(f"跳闸简报生成失败 (exit_code={exit_code})")

    return briefing_path


def _copy_briefing_to_workspace(job_root: Path, app_root: Path, zip_name: str) -> None:
    """Copy briefing outputs and source files to workspace for AI access.

    Copies to {workspace}/跳闸简报/:
      - 跳闸简报.md
      - 段落/*.md
      - source COMTRADE files (.cfg, .hdr, .dat, .rms.csv, .events.csv)
      - info.json (metadata)
    """
    workspace_dir = app_root.parent.parent / "workspace"
    if not workspace_dir.exists():
        return

    briefing_src = job_root / "output" / "跳闸简报.md"
    if not briefing_src.exists():
        return

    dest = workspace_dir / "跳闸简报"
    # Clean previous briefing
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    # Copy briefing markdown
    shutil.copy2(str(briefing_src), str(dest / "跳闸简报.md"))

    # Copy paragraphs
    para_src = job_root / "output" / "段落"
    if para_src.is_dir():
        para_dest = dest / "段落"
        shutil.copytree(str(para_src), str(para_dest))

    # Copy source COMTRADE files from extracted directory
    extracted = job_root / "extracted"
    src_dest = dest / "录波源文件"
    if extracted.is_dir():
        _copy_comtrade_files(extracted, src_dest)

    # Write metadata
    info = {
        "zip_name": zip_name,
        "job_id": job_root.name,
        "copied_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (dest / "info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[工作区] 已复制简报到工作区: {dest}", flush=True)


def _copy_comtrade_files(src_dir: Path, dest_dir: Path) -> None:
    """Recursively copy COMTRADE-related files from src to dest, preserving directory structure."""
    COMTRADE_EXTS = {".cfg", ".dat", ".hdr", ".inf", ".rms.csv", ".events.csv"}
    for f in src_dir.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        is_comtrade = ext in COMTRADE_EXTS or f.name.lower().endswith((".rms.csv", ".events.csv"))
        if not is_comtrade:
            continue
        rel = f.relative_to(src_dir)
        dest_f = dest_dir / rel
        dest_f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(f), str(dest_f))


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
            try:
                conn.execute("ALTER TABLE jobs ADD COLUMN external_id TEXT")
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

    def create_job_from_directory(
        self,
        dir_path: str | Path,
        *,
        station: str | None = None,
        device: str | None = None,
        device_type: str | None = None,
        created_by: str | None = None,
        run_in_background: bool = True,
    ) -> dict[str, Any]:
        """从本地目录创建任务，自动读取 _故障事件信息.md 提取元数据。"""
        dir_path = Path(dir_path).expanduser().resolve()
        if not dir_path.is_dir():
            raise FileNotFoundError(f"目录不存在: {dir_path}")

        file_names: list[str] = []
        file_bytes_list: list[bytes] = []

        # 收集目录中的所有文件（递归子目录）
        for f in sorted(dir_path.rglob("*")):
            if f.is_file():
                # 保留相对路径结构
                try:
                    rel = f.relative_to(dir_path)
                    arc_name = str(rel).replace("\\", "/")
                except ValueError:
                    arc_name = f.name
                file_names.append(arc_name)
                file_bytes_list.append(f.read_bytes())

        if not file_names:
            raise FileNotFoundError(f"目录为空: {dir_path}")

        return self._create_job_from_bytes(
            file_names=file_names,
            file_bytes_list=file_bytes_list,
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
                    evaluation,
                    external_id
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
                    evaluation,
                    external_id
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None

    def get_job_by_external_id(self, external_id: str) -> dict[str, Any] | None:
        """通过外部 ID 查询任务。"""
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
                    evaluation,
                    external_id
                FROM jobs
                WHERE external_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (external_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None

    def search_jobs(self, station: str) -> list[dict[str, Any]]:
        """按 station 关键词模糊搜索任务。"""
        self.initialize()
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    id, status, created_at, updated_at, error_message,
                    file_name, cfg_file_name, dat_file_name, hdr_file_name,
                    result_file_name, result_relative_path, result_download_token,
                    station, device, device_type,
                    progress, progress_message, evaluation, external_id
                FROM jobs
                WHERE station LIKE ? OR device LIKE ?
                ORDER BY created_at DESC
                """,
                (f"%{station}%", f"%{station}%"),
            ).fetchall()
        results = []
        for row in rows:
            job = self._serialize_job(dict(row))
            # 为已完成的任务附加简报预览
            if job["status"] == "completed":
                briefing_path = self.app_root / "jobs" / job["id"] / "output" / "跳闸简报.md"
                if briefing_path.exists():
                    try:
                        content = briefing_path.read_text(encoding="utf-8")
                        job["preview"] = content[:500]
                    except Exception:
                        job["preview"] = None
                else:
                    job["preview"] = None
            else:
                job["preview"] = None
            results.append(job)
        return results

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
                # Rename result file to include station/device name
                result_path = self._rename_result_with_station(job_id, result_path)

                # Convert .md to .docx for user download
                result_path = self._convert_to_docx(result_path)

                self.mark_completed(job_id, result_path)

    def _rename_result_with_station(self, job_id: str, result_path: Path) -> Path:
        """确保结果文件名为 跳闸简报.md"""
        # 如果文件名已经是跳闸简报.md，无需重命名
        if result_path.name == "跳闸简报.md":
            return result_path
        # 重命名为跳闸简报.md
        new_path = result_path.parent / "跳闸简报.md"
        try:
            result_path.rename(new_path)
            return new_path
        except OSError:
            pass  # If rename fails, keep original name
        return result_path

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
        external_id: str | None = None,
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

        # 先写入所有文件
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

        # 检测 _故障事件信息.md 文件，自动提取元数据
        md_meta: dict[str, str] = {}
        for name, data in zip(file_names, file_bytes_list, strict=True):
            safe_name = self._safe_upload_name(name, "upload")
            if safe_name.endswith(".md") and "故障事件" in safe_name:
                # 临时写入以便解析
                tmp_md = inputs_dir / safe_name
                md_meta = parse_fault_event_md(tmp_md)
                break

        # 如果上传文件中没有 md，尝试从 zip 内部提取
        if not md_meta:
            for name, data in zip(file_names, file_bytes_list, strict=True):
                safe_name = self._safe_upload_name(name, "upload")
                if not safe_name.lower().endswith(".zip"):
                    continue
                try:
                    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                        for entry in zf.infolist():
                            if entry.filename.endswith(".md") and "故障事件" in entry.filename:
                                md_bytes = zf.read(entry)
                                tmp_md = inputs_dir / Path(entry.filename).name
                                tmp_md.write_bytes(md_bytes)
                                md_meta = parse_fault_event_md(tmp_md)
                                break
                except Exception:
                    pass
                if md_meta:
                    break

        # 用 md 文件中的元数据补充 station/device/device_type/external_id
        if md_meta:
            if not external_id and md_meta.get("id"):
                external_id = md_meta["id"]
            if not station and md_meta.get("equipmentName"):
                station = md_meta["equipmentName"]
            if not device and md_meta.get("equipmentName"):
                device = md_meta["equipmentName"]
            if (not device_type or device_type == "line") and md_meta.get("equipType"):
                device_type = _equip_type_to_device_type(md_meta["equipType"])

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
            external_id=external_id,
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
        external_id: str | None = None,
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
                    device_type,
                    external_id
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, "queued", now, now, created_by, file_name, cfg_name, dat_name, hdr_name, station, device, device_type or "line", external_id),
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

    def delete_job(self, job_id: str) -> bool:
        """删除任务及其所有文件。返回 True 表示成功。"""
        self.initialize()
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        # 删除任务文件目录
        import shutil
        job_dir = self._job_root(job_id)
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
        return True

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
            "preview_url": f"/api/wave-record-parser/jobs/{row['id']}/preview" if downloadable else None,
            "station": row.get("station"),
            "device": row.get("device"),
            "device_type": row.get("device_type"),
            "progress": row.get("progress") or 0,
            "progress_message": row.get("progress_message"),
            "evaluation": row.get("evaluation") or "",
            "external_id": row.get("external_id") or "",
        }

    def get_export_files(self, job_ids: list[str]) -> list[tuple[Path, str]]:
        """Return (file_path, display_name) for completed jobs with result files."""
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
                    station, device, device_type, progress, progress_message, evaluation,
                    external_id
                FROM jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        raw = row_to_dict(row)
        return self._serialize_job(raw) if raw else None
