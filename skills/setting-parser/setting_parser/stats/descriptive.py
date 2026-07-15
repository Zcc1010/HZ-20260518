"""描述性统计：单份定值单摘要 + 多份分组 + 同名定值对比."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


def summarize_sheet(sheet: dict) -> dict:
    """对单份定值单做摘要."""
    return {
        "station": sheet.get("device", {}).get("station"),
        "equipment_name": sheet.get("device", {}).get("equipment_name"),
        "equipment_type": sheet.get("device", {}).get("equipment_type"),
        "model_base": sheet.get("protection_device", {}).get("model_base"),
        "voltage_kv": sheet.get("device", {}).get("voltage_kv"),
        "settings_count": len(sheet.get("settings", [])),
        "control_words_count": len(sheet.get("control_words", [])),
        "has_trip_matrix": sheet.get("trip_matrix") is not None,
        "warnings_count": len(sheet.get("parse_warnings", [])),
    }


def group_sheets_by(sheets: list[dict], *, by: str) -> dict[str, list[dict]]:
    """按指定字段分组。by 支持 'equipment_type' / 'model_base' / 'voltage_kv' / 'station'."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for sheet in sheets:
        if by in ("equipment_type", "station"):
            key = sheet.get("device", {}).get(by, "未知")
        elif by in ("model_base",):
            key = sheet.get("protection_device", {}).get(by, "未知")
        elif by in ("voltage_kv",):
            key = str(sheet.get("device", {}).get(by, "未知"))
        else:
            raise ValueError(f"不支持的分组字段: {by}")
        groups[key].append(sheet)
    return dict(groups)


def compare_named_settings(sheets: list[dict], *, setting_name: str) -> list[dict]:
    """跨多份定值单对比同名定值项."""
    rows: list[dict] = []
    for sheet in sheets:
        station = sheet.get("device", {}).get("station")
        for item in sheet.get("settings", []):
            if item.get("name_raw") == setting_name or item.get("name_alias") == setting_name:
                rows.append({
                    "station": station,
                    "equipment_name": sheet.get("device", {}).get("equipment_name"),
                    "value": item.get("value"),
                    "value_numeric": item.get("value_numeric"),
                    "unit": item.get("unit"),
                })
    return rows
