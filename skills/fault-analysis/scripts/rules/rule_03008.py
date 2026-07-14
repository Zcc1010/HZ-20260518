# -*- coding: utf-8 -*-
"""
Rule 03008: 主变后备越级

判定:
- 前置:主变后备保护任一动作 + 故障点不在主变保护区内(穿越性判据)
- 场景A:下级保护未动作
- 场景B:下级保护动作但断路器拒动(BRK_POS=合)
- 场景C:≥2 条出线不同相单相接地 + 线路保护未动
- 场景D:下级保护动作 + 断路器跳开 + 但主变后备同时动作(典型越级)

严重度:严重
"""
from typing import Optional


SCENARIO_A = "A"
SCENARIO_B = "B"
SCENARIO_C = "C"
SCENARIO_D = "D"


def check_through_current(
    i_high: float,
    i_mid: float,
    i_low: float,
    downstream_fault_a: float,
    diff_current_a: float,
    diff_setting_a: float,
    downstream_in_a: float = 600.0,
) -> dict:
    """故障点"穿越性"判据

    三条同时满足,判定故障不在主变区内:
    1. |I_H + I_M + I_L| < 0.1 × |I_H|
    2. 至少 1 条出线故障电流 > 2In
    3. 主变差流 < 0.5 × 差动动作电流定值
    """
    vector_sum = abs(i_high - i_mid - i_low)
    cond1 = vector_sum < 0.1 * abs(i_high)
    cond2 = downstream_fault_a > 2 * downstream_in_a
    cond3 = diff_current_a < 0.5 * diff_setting_a
    return {
        "is_outside": cond1 and cond2 and cond3,
        "cond1_vector_sum_lt_10pct": cond1,
        "cond2_downstream_fault_gt_2In": cond2,
        "cond3_diff_lt_half_setting": cond3,
    }


def evaluate(
    main_backup_tripped: bool,
    downstream_tripped: bool,
    downstream_brk_open: bool,
    two_phase_grounding: bool,
    is_outside_main_zone: bool,
    same_time_action: bool = False,
) -> dict:
    """评估 Rule 03008 触发情况

    same_time_action: 主变后备与下级保护"同时刻"动作(<100ms 偏差)
    若为 True 即便下级正确跳闸,主变后备不应动作,仍判越级(场景D)
    """
    if not main_backup_tripped or not is_outside_main_zone:
        return {
            "triggered": False,
            "scenario": None,
            "severity": None,
            "evidence": {"reason": "主变后备未动作 或 故障在主变区内,不属于越级"},
        }

    if two_phase_grounding and not downstream_tripped:
        scenario = SCENARIO_C
    elif downstream_tripped and not downstream_brk_open:
        scenario = SCENARIO_B
    elif not downstream_tripped:
        scenario = SCENARIO_A
    elif downstream_tripped and downstream_brk_open and same_time_action:
        # 关键场景:下级正确动作且断路器跳开,但主变后备与下级"同时"动作 = 越级
        # (典型案例:10kV线路跳闸同时主变低后备也跳)
        scenario = SCENARIO_D
    else:
        return {
            "triggered": False,
            "scenario": None,
            "severity": None,
            "evidence": {"reason": "下级保护正确动作且断路器跳开,主变后备越级不成立"},
        }

    remediation_d = (
        "检查主变后备保护时限配合(下级跳闸后主变后备不应再动作);"
        "核对后备保护定值整定;"
        "检查主变后备保护投入/压板状态;"
        "提交越级跳闸专项分析报告"
    )
    remediation_default = (
        "检查下级保护装置功能、定值、回路;"
        "检查下级断路器操作机构、二次回路;"
        "核对后备保护时限配合"
    )
    remediation_c = remediation_default + ";提交异相两点接地专项分析"

    return {
        "triggered": True,
        "scenario": scenario,
        "severity": "严重",
        "evidence": {
            "main_backup_tripped": main_backup_tripped,
            "downstream_tripped": downstream_tripped,
            "downstream_brk_open": downstream_brk_open,
            "two_phase_grounding": two_phase_grounding,
            "is_outside_main_zone": is_outside_main_zone,
            "same_time_action": same_time_action,
        },
        "remediation": (
            remediation_d if scenario == SCENARIO_D
            else remediation_c if scenario == SCENARIO_C
            else remediation_default
        ),
    }
