# -*- coding: utf-8 -*-
"""
Rule 03009: CT 饱和致主变差动误动

判定:
- 前置:主变比率差动动作 + 主变各侧差流 > 差动动作电流定值
- 主体:主变某侧 CT 二次电流有饱和特征(2次谐波/基波>15% 且 基波>2In)
       或(HDR 中 CT 饱和标志=1)
- 误报避免:差流 > 2×定值时判为真实差动动作,不触发本规则

严重度:危急
"""
from typing import Optional


def evaluate(
    diff_tripped: bool,
    diff_current_a: float,
    diff_setting_a: float,
    ct_saturation: dict,
    is_outside_main_zone: bool,
) -> dict:
    """评估 Rule 03009 触发情况"""
    # 前置 1: 差动必须动作
    if not diff_tripped:
        return {
            "triggered": False,
            "severity": None,
            "evidence": {"reason": "差动未动作"},
        }

    # 前置 2: 差流必须超过定值
    if diff_current_a <= diff_setting_a:
        return {
            "triggered": False,
            "severity": None,
            "evidence": {"reason": "差流未超过定值"},
        }

    # 误报避免: 差流 > 2×定值 → 判为真实区内故障差动动作
    if diff_current_a > 2 * diff_setting_a:
        return {
            "triggered": False,
            "severity": None,
            "evidence": {"reason": "差流 > 2×定值,判为真实差动动作"},
        }

    # 主体: 检测到 CT 饱和
    saturated_sides = []
    for side, phases in ct_saturation.items():
        for phase, info in phases.items():
            if isinstance(info, dict) and info.get("saturated"):
                saturated_sides.append(side)
                break

    if not saturated_sides:
        return {
            "triggered": False,
            "severity": None,
            "evidence": {"reason": "差流超定值但未检测到 CT 饱和"},
        }

    return {
        "triggered": True,
        "severity": "危急",
        "evidence": {
            "diff_current_a": diff_current_a,
            "diff_setting_a": diff_setting_a,
            "saturated_sides": saturated_sides,
            "is_outside_main_zone": is_outside_main_zone,
        },
        "remediation": (
            f"检查 {', '.join(saturated_sides)} CT 变比、极性、二次负担;"
            "校验差动保护抗饱和措施(比率制动、二次谐波制动);"
            "必要时调整 CT 变比或更换 CT"
        ),
    }
