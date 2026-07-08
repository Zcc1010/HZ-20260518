# -*- coding: utf-8 -*-
"""故障录波文件解析器 - 解析 .RPT / .ANA / .INF 文件"""
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


def _read_file_auto_encode(file_path: str) -> str:
    """自动检测编码读取文件"""
    path = Path(file_path)
    if not path.exists():
        return ""

    raw = path.read_bytes()
    # 尝试 UTF-8 (带 BOM 和不带 BOM)
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    # 尝试 GBK
    try:
        return raw.decode("gbk")
    except (UnicodeDecodeError, ValueError):
        pass
    # 尝试 chardet
    try:
        import chardet
        detected = chardet.detect(raw)
        if detected and detected.get("encoding"):
            return raw.decode(detected["encoding"])
    except ImportError:
        pass
    # 最后 fallback
    return raw.decode("utf-8", errors="replace")


# ============================================================
# RPT 解析
# ============================================================

def _parse_phasor_line(line: str) -> Optional[Dict[str, str]]:
    """解析相量行，如: A相:(一次值= 301.692 kV); (二次值=  60.338 V); (相角= 177.927 °)"""
    m = re.match(
        r'\s*([一-龥A-Za-z]+)\S*:\(一次值=\s*([\d.\-]+)\s*(\w+)\);\s*\(二次值=\s*([\d.\-]+)\s*(\w+)\);\s*\(相角=\s*([\d.\-]+)\s*°?\)',
        line.strip()
    )
    if m:
        return {
            "phase": m.group(1),
            "primary_value": m.group(2),
            "primary_unit": m.group(3),
            "secondary_value": m.group(4),
            "secondary_unit": m.group(5),
            "angle": m.group(6),
        }
    return None


def _parse_fault_block(lines: List[str]) -> Dict[str, Any]:
    """解析一个故障记录块"""
    fault: Dict[str, Any] = {}
    phasors: Dict[str, List[Dict]] = {}
    current_phasor_group = ""

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 基本字段
        for key, pattern in [
            ("element", r"故障元件:\s*(.+)"),
            ("fault_type", r"故障类型:\s*(\S+)"),
            ("fault_phase", r"故障相别:\s*(\S+)"),
            ("trip_phase", r"跳闸相别:\s*(\S+)"),
            ("start_time", r"故障起始时间:\s*([\d.]+\s*ms)"),
            ("end_time", r"故障结束时间:\s*([\d.]+\s*ms)"),
            ("protection_time", r"保护动作时间:\s*([\d.]+\s*ms)"),
            ("breaker_time", r"断路器跳闸时间:\s*([\d.]+\s*ms)"),
            ("distance", r"故障距离:\s*([\d.]+\s*kM)"),
            ("reactance", r"二次侧电抗:\s*([\d.]+\s*\S+)"),
            ("min_voltage", r"故障过程中最小电压有效值:\s*([\d.]+\s*\w+)"),
            ("max_current", r"故障过程中最大电流有效值:\s*([\d.]+\s*\w+)"),
        ]:
            m = re.match(pattern, line)
            if m:
                fault[key] = m.group(1).strip()
                break

        # 相量组标题
        phasor_group_match = re.match(
            r"(故障前一周波|故障时|故障后一周波|故障后二周波)(电压|电流)有效值:",
            line
        )
        if phasor_group_match:
            current_phasor_group = phasor_group_match.group(0).rstrip(":")
            if current_phasor_group not in phasors:
                phasors[current_phasor_group] = []
            continue

        # 相量数据行
        if current_phasor_group:
            phasor = _parse_phasor_line(line)
            if phasor:
                phasors[current_phasor_group].append(phasor)
                continue

        # 线路参数
        m = re.match(r"名义参数:(.+)", line)
        if m:
            fault["nominal_params"] = m.group(1).strip()
        m = re.match(r"实测参数:(.+)", line)
        if m:
            fault["measured_params"] = m.group(1).strip()

        # 保护边界参数
        for key, pattern in [
            ("ZR", r"ZR:\s*([\d.]+)"),
            ("ZX", r"ZX:\s*([\d.]+)"),
            ("ARG", r"ARG:\s*([\d.]+)"),
        ]:
            m = re.match(pattern, line)
            if m:
                fault[key] = m.group(1)

    if phasors:
        fault["phasors"] = phasors
    return fault


def _parse_switch_events(lines: List[str]) -> List[Dict[str, str]]:
    """解析开关量变位清单"""
    events = []
    current_channel = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 通道标题行
        ch_match = re.match(
            r"第(\d+)通道:(.+?);信号类型:(.+?);通道标记:(.+)",
            line
        )
        if ch_match:
            if current_channel:
                events.append(current_channel)
            current_channel = {
                "channel_no": ch_match.group(1),
                "channel_name": ch_match.group(2).strip(),
                "signal_type": ch_match.group(3).strip(),
                "channel_tag": ch_match.group(4).strip(),
                "changes": [],
            }
            continue

        # 变位/复位行
        change_match = re.match(
            r"(变位|复位):相对时间=\s*([\d.]+)毫秒,\s*采样点=(\d+),\s*采样值=(\d+)",
            line
        )
        if change_match and current_channel:
            current_channel["changes"].append({
                "type": change_match.group(1),
                "relative_time_ms": change_match.group(2),
                "sample_point": change_match.group(3),
                "value": change_match.group(4),
            })

    if current_channel:
        events.append(current_channel)
    return events


def parse_rpt(rpt_path: str) -> Dict[str, Any]:
    """
    解析 .RPT 文件，返回结构化故障数据。

    Returns:
        {
            "station": str,
            "device_name": str,
            "trigger_time": str,
            "faults": [{...故障记录...}],
            "switch_events": [{...开关量变位...}],
        }
    """
    content = _read_file_auto_encode(rpt_path)
    if not content:
        return {"station": "", "device_name": "", "trigger_time": "", "faults": [], "switch_events": []}

    result = {
        "station": "",
        "device_name": "",
        "trigger_time": "",
        "faults": [],
        "switch_events": [],
    }

    # 分割三个主要区块
    sections = re.split(r"={50,}", content)

    # 解析厂站及装置基本信息
    for section in sections:
        if "厂站及装置基本信息" in section:
            m = re.search(r"变电站名称:\s*(.+)", section)
            if m:
                result["station"] = m.group(1).strip()
            m = re.search(r"装置名称:\s*(.+)", section)
            if m:
                result["device_name"] = m.group(1).strip()
            m = re.search(r"录波触发时间:\s*(.+)", section)
            if m:
                result["trigger_time"] = m.group(1).strip()
            break

    # 解析故障分析报告
    fault_section = ""
    switch_section = ""
    for i, section in enumerate(sections):
        if "故障分析报告" in section:
            fault_section = section
        if "开关量变位清单" in section:
            switch_section = section

    # 解析每次故障
    if fault_section:
        # 按"第N次故障"分割
        fault_blocks = re.split(r"(第\d+次故障)", fault_section)
        current_fault_lines = []
        for part in fault_blocks:
            if re.match(r"第\d+次故障", part):
                if current_fault_lines:
                    fault = _parse_fault_block(current_fault_lines)
                    if fault:
                        result["faults"].append(fault)
                current_fault_lines = []
            else:
                current_fault_lines.extend(part.split("\n"))
        # 最后一个故障块
        if current_fault_lines:
            fault = _parse_fault_block(current_fault_lines)
            if fault:
                result["faults"].append(fault)

    # 解析开关量变位清单
    if switch_section:
        switch_lines = switch_section.split("\n")
        result["switch_events"] = _parse_switch_events(switch_lines)

    return result


# ============================================================
# ANA 解析
# ============================================================

def _parse_ana_time_offset(offset_str: str, fault_start: str) -> str:
    """将 ANA 中的偏移量(ms)转换为绝对时间"""
    try:
        offset_ms = float(offset_str)
        # fault_start 格式: "2026-07-01 19:43:34:582"
        from datetime import datetime, timedelta
        dt = datetime.strptime(fault_start, "%Y-%m-%d %H:%M:%S:%f")
        dt += timedelta(milliseconds=offset_ms)
        return dt.strftime("%H:%M:%S.%f")[:-3]
    except (ValueError, TypeError):
        return offset_str


def parse_ana(ana_path: str) -> Dict[str, Any]:
    """
    解析 .ANA XML 文件，返回装置信息和事件数据。

    Returns:
        {
            "device_info": {name: value, ...},
            "trig_info": [{time, name, value, setting}, ...],
            "fault_info": {name: value, ...},
            "fault_start_time": str,
            "trip_info": [{time, name, phase, value, abs_time}, ...],
            "digital_events": [{time, name, value, abs_time}, ...],
            "digital_status": [{name, value}, ...],  # 只包含 value=1
        }
    """
    content = _read_file_auto_encode(ana_path)
    if not content:
        return {}

    result = {
        "device_info": {},
        "trig_info": [],
        "fault_info": {},
        "fault_start_time": "",
        "trip_info": [],
        "digital_events": [],
        "digital_status": [],
    }

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        logger.error(f"ANA XML 解析失败: {e}")
        return result

    # DeviceInfo
    for elem in root.findall("DeviceInfo"):
        name = elem.findtext("name", "")
        value = elem.findtext("value", "")
        if name:
            result["device_info"][name] = value

    # TrigInfo
    for elem in root.findall("TrigInfo"):
        result["trig_info"].append({
            "time": elem.findtext("time", ""),
            "name": elem.findtext("name", ""),
            "value": elem.findtext("value", ""),
            "setting": elem.findtext("setting", ""),
        })

    # FaultInfo
    for elem in root.findall("FaultInfo"):
        name = elem.findtext("name", "")
        value = elem.findtext("value", "")
        if name:
            result["fault_info"][name] = value

    # FaultStartTime
    fault_start = root.findtext("FaultStartTime", "")
    result["fault_start_time"] = fault_start

    # TripInfo (偏移量转绝对时间)
    for elem in root.findall("TripInfo"):
        time_offset = elem.findtext("time", "")
        result["trip_info"].append({
            "time": time_offset,
            "name": elem.findtext("name", ""),
            "phase": elem.findtext("phase", ""),
            "value": elem.findtext("value", ""),
            "abs_time": _parse_ana_time_offset(time_offset, fault_start) if fault_start else time_offset,
        })

    # DigitalEvent
    for elem in root.findall("DigitalEvent"):
        time_offset = elem.findtext("time", "")
        result["digital_events"].append({
            "time": time_offset,
            "name": elem.findtext("name", ""),
            "value": elem.findtext("value", ""),
            "abs_time": _parse_ana_time_offset(time_offset, fault_start) if fault_start else time_offset,
        })

    # DigitalStatus - 只保留 value=1 的条目
    for elem in root.findall("DigitalStatus"):
        value = elem.findtext("value", "0")
        if value == "1":
            result["digital_status"].append({
                "name": elem.findtext("name", ""),
                "value": value,
            })

    return result


# ============================================================
# INF 解析
# ============================================================

def parse_inf(inf_path: str) -> Dict[str, Any]:
    """
    解析 .INF 文件，返回通道配置。

    Returns:
        {
            "station_name": str,
            "recording_device_id": str,
            "channels": [{channel_id, phase_id, component, units, multiplier,
                          ratio_primary, ratio_secondary, primary_secondary}, ...],
        }
    """
    content = _read_file_auto_encode(inf_path)
    if not content:
        return {"station_name": "", "recording_device_id": "", "channels": []}

    result = {
        "station_name": "",
        "recording_device_id": "",
        "channels": [],
    }

    # 简单 INI 解析
    current_section = ""
    current_channel: Dict[str, str] = {}

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue

        # Section header
        section_match = re.match(r"\[(.+)\]", line)
        if section_match:
            # 保存上一个通道
            if current_channel and current_section.startswith("Public Analog_Channel"):
                result["channels"].append(current_channel)

            current_section = section_match.group(1)
            current_channel = {}
            continue

        # Key=Value
        kv_match = re.match(r"(\w+)\s*=\s*(.+)", line)
        if kv_match:
            key = kv_match.group(1)
            value = kv_match.group(2).strip()

            if current_section == "Public File_Description":
                if key == "Station_Name":
                    result["station_name"] = value
                elif key == "Recording_Device_ID":
                    result["recording_device_id"] = value
            elif current_section.startswith("Public Analog_Channel"):
                key_map = {
                    "Channel_ID": "channel_id",
                    "Phase_ID": "phase_id",
                    "Monitored_Component": "component",
                    "Channel_Units": "units",
                    "Channel_Multiplier": "multiplier",
                    "Channel_Ratio_Primary": "ratio_primary",
                    "Channel_Ratio_Secondary": "ratio_secondary",
                    "Data_Primary_Secondary": "primary_secondary",
                }
                if key in key_map:
                    current_channel[key_map[key]] = value

    # 最后一个通道
    if current_channel and current_section.startswith("Public Analog_Channel"):
        result["channels"].append(current_channel)

    return result


# ============================================================
# 整合输出
# ============================================================

def _format_phasors_table(phasors: Dict[str, List[Dict]]) -> str:
    """将相量数据格式化为 Markdown 表格"""
    if not phasors:
        return ""

    lines = []
    lines.append("| 时刻 | 相别 | 一次值 | 二次值 | 相角 |")
    lines.append("|------|------|--------|--------|------|")

    for group_name, group_phasors in phasors.items():
        for p in group_phasors:
            lines.append(
                f"| {group_name} | {p['phase']} | "
                f"{p['primary_value']} {p['primary_unit']} | "
                f"{p['secondary_value']} {p['secondary_unit']} | "
                f"{p['angle']}° |"
            )

    return "\n".join(lines)


def _format_switch_events_table(events: List[Dict]) -> str:
    """将开关量变位格式化为 Markdown 表格"""
    if not events:
        return ""

    lines = []
    lines.append("| 通道名称 | 信号类型 | 变位/复位 | 相对时间(ms) | 采样值 |")
    lines.append("|----------|----------|-----------|-------------|--------|")

    for evt in events:
        ch_name = evt.get("channel_name", "")
        sig_type = evt.get("signal_type", "")
        for change in evt.get("changes", []):
            lines.append(
                f"| {ch_name} | {sig_type} | {change['type']} | "
                f"{change['relative_time_ms']} | {change['value']} |"
            )

    return "\n".join(lines)


def build_fault_recorder_context(
    rpt_data: Dict[str, Any],
    ana_data: Dict[str, Any],
    inf_data: Dict[str, Any],
    hdr_content: str = "",
) -> str:
    """
    将 RPT/ANA/INF 解析结果整合为 LLM 可读的 Markdown 文本。

    Args:
        rpt_data: parse_rpt() 的返回值
        ana_data: parse_ana() 的返回值
        inf_data: parse_inf() 的返回值
        hdr_content: HDR 文件原始内容（可选）

    Returns:
        Markdown 格式的结构化文本
    """
    sections = []

    # RPT 故障分析报告
    if rpt_data and rpt_data.get("faults"):
        sections.append("## 故障分析报告（RPT）")
        sections.append(f"**变电站**: {rpt_data.get('station', '')}")
        sections.append(f"**录波触发时间**: {rpt_data.get('trigger_time', '')}")
        sections.append("")

        for i, fault in enumerate(rpt_data["faults"], 1):
            sections.append(f"### 第{i}次故障")
            for key, label in [
                ("element", "故障元件"),
                ("fault_type", "故障类型"),
                ("fault_phase", "故障相别"),
                ("trip_phase", "跳闸相别"),
                ("start_time", "故障起始时间"),
                ("end_time", "故障结束时间"),
                ("protection_time", "保护动作时间"),
                ("breaker_time", "断路器跳闸时间"),
                ("distance", "故障距离"),
                ("reactance", "二次侧电抗"),
                ("min_voltage", "故障过程中最小电压有效值"),
                ("max_current", "故障过程中最大电流有效值"),
            ]:
                val = fault.get(key)
                if val:
                    sections.append(f"- {label}: {val}")

            # 相量数据
            if fault.get("phasors"):
                sections.append("")
                sections.append("**电压电流相量**:")
                sections.append(_format_phasors_table(fault["phasors"]))

            # 线路参数
            if fault.get("nominal_params") or fault.get("measured_params"):
                sections.append("")
                sections.append("**线路参数**:")
                if fault.get("nominal_params"):
                    sections.append(f"- 名义参数: {fault['nominal_params']}")
                if fault.get("measured_params"):
                    sections.append(f"- 实测参数: {fault['measured_params']}")

            # 保护边界参数
            boundary = []
            for k in ("ZR", "ZX", "ARG"):
                if fault.get(k):
                    boundary.append(f"{k}={fault[k]}")
            if boundary:
                sections.append(f"- 保护边界参数: {', '.join(boundary)}")

            sections.append("")

    # RPT 开关量变位清单
    if rpt_data and rpt_data.get("switch_events"):
        sections.append("## 开关量变位清单（RPT）")
        sections.append(_format_switch_events_table(rpt_data["switch_events"]))
        sections.append("")

    # ANA 装置信息和事件
    if ana_data:
        if ana_data.get("device_info"):
            sections.append("## 装置信息（ANA）")
            for name, value in ana_data["device_info"].items():
                sections.append(f"- {name}: {value}")
            sections.append("")

        if ana_data.get("fault_info"):
            sections.append("## 故障信息（ANA）")
            for name, value in ana_data["fault_info"].items():
                sections.append(f"- {name}: {value}")
            sections.append("")

        if ana_data.get("trip_info"):
            sections.append("## 保护动作时序（ANA TripInfo）")
            sections.append("| 动作名称 | 动作时间(ms) | 绝对时间 | 相别 | 值 |")
            sections.append("|----------|-------------|----------|------|-----|")
            for t in ana_data["trip_info"]:
                sections.append(
                    f"| {t['name']} | {t['time']} | {t.get('abs_time', '')} | "
                    f"{t['phase']} | {t['value']} |"
                )
            sections.append("")

        if ana_data.get("digital_events"):
            sections.append("## 数字量事件（ANA DigitalEvent）")
            sections.append("| 通道名称 | 时间(ms) | 绝对时间 | 值 |")
            sections.append("|----------|----------|----------|-----|")
            for evt in ana_data["digital_events"]:
                sections.append(
                    f"| {evt['name']} | {evt['time']} | {evt.get('abs_time', '')} | {evt['value']} |"
                )
            sections.append("")

        if ana_data.get("digital_status"):
            sections.append("## 数字状态（ANA DigitalStatus，仅 value=1）")
            for ds in ana_data["digital_status"]:
                sections.append(f"- {ds['name']}")
            sections.append("")

    # INF 通道配置
    if inf_data and inf_data.get("channels"):
        sections.append("## 通道配置（INF）")
        sections.append(f"**录波器**: {inf_data.get('recording_device_id', '')}")
        sections.append("")
        sections.append("| 通道ID | 相别 | 监控组件 | 单位 | CT/PT变比 |")
        sections.append("|--------|------|----------|------|-----------|")
        for ch in inf_data["channels"]:
            ratio_str = ""
            rp = ch.get("ratio_primary", "")
            rs = ch.get("ratio_secondary", "")
            if rp and rs:
                try:
                    ratio_str = f"{float(rp):.0f}/{float(rs):.0f}"
                except ValueError:
                    ratio_str = f"{rp}/{rs}"
            sections.append(
                f"| {ch.get('channel_id', '')} | {ch.get('phase_id', '')} | "
                f"{ch.get('component', '')} | {ch.get('units', '')} | {ratio_str} |"
            )
        sections.append("")

    # HDR 原始内容（可选补充）
    if hdr_content:
        sections.append("## HDR 文件内容")
        sections.append(hdr_content)

    return "\n".join(sections)
