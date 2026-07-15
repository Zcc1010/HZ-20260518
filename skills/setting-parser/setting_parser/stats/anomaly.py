"""异常检测：定值范围 + 控制字合法性."""
from __future__ import annotations

import re
from typing import Literal

AnomalyStatus = Literal["ok", "near_boundary", "out_of_range", "no_kb_ref"]
ControlStatus = Literal["ok", "invalid"]


def check_setting_range(item: dict) -> tuple[AnomalyStatus, str]:
    """检查单条定值是否在说明书范围内.

    Returns:
        (status, detail_message)
    """
    kb = item.get("knowledge_ref")
    if not kb:
        return "no_kb_ref", "知识库无范围信息"
    v = item.get("value_numeric")
    if v is None:
        return "no_kb_ref", "定值非数值，跳过范围检查"
    rmin = kb.get("range_min")
    rmax = kb.get("range_max")
    if rmin is None or rmax is None:
        return "no_kb_ref", "知识库无 min/max"
    if v < rmin or v > rmax:
        return "out_of_range", f"定值 {v} {item.get('unit', '')} 超出说明书范围 [{rmin}, {rmax}]"
    # 边界检查：距任一边界 < 5%
    span = rmax - rmin
    threshold = span * 0.05
    if v - rmin < threshold or rmax - v < threshold:
        return "near_boundary", f"定值 {v} {item.get('unit', '')} 接近说明书边界 [{rmin}, {rmax}]"
    return "ok", ""


def check_control_word_legality(cw: dict) -> ControlStatus:
    """检查控制字值合法性（二进制 0/1 或 1-4 位 hex）."""
    v = str(cw.get("value", "")).strip()
    if v in ("0", "1"):
        return "ok"
    if re.match(r"^[0-9A-Fa-f]{2,4}$", v):
        return "ok"
    return "invalid"


def detect_anomalies(sheet: dict) -> dict:
    """对单份定值单做完整异常检测.

    Returns:
        {
            "ok": [...],
            "near_boundary": [...],
            "out_of_range": [...],
            "no_kb_ref": [...],
            "control_word_invalid": [...],
        }
    """
    report = {
        "ok": [],
        "near_boundary": [],
        "out_of_range": [],
        "no_kb_ref": [],
        "control_word_invalid": [],
    }
    for item in sheet.get("settings", []):
        status, detail = check_setting_range(item)
        report[status].append({"item": item.get("name_raw"), "detail": detail})
    for cw in sheet.get("control_words", []):
        status = check_control_word_legality(cw)
        if status == "invalid":
            report["control_word_invalid"].append({"item": cw.get("name_raw"), "value": cw.get("value")})
    return report