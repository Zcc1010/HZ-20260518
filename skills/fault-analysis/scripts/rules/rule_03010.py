# -*- coding: utf-8 -*-
"""
Rule 03010: 主变保护未正确动作(主变自身分析规则)

使用条件:仅在 Rule 03008/03009 不适用时触发,优先级低于越级规则。

四个判定维度:
- D1:主变差动/重瓦斯拒动(区内故障但主变未动)
- D2:主变保护误动(区外故障但主变动了)
- D3:主变各侧后备配合不当(同侧两套保护动作时间差 > 50ms)
- D4:主变非电量保护误动(重瓦斯/压力释放跳闸但无内部故障)

严重度:危急
"""


DIM_REJECT = "D1_差动/重瓦斯拒动"
DIM_FALSE_TRIP = "D2_主变保护误动"
DIM_BACKUP_MISMATCH = "D3_后备配合不当"
DIM_NON_ELEC = "D4_非电量保护误动"


def evaluate(
    diff_tripped: bool,
    gas_tripped: bool,
    is_inside_main_zone: bool,
    backup_mismatch: bool,
    non_electrical_false_trip: bool,
) -> dict:
    """评估 Rule 03010 触发情况"""
    dimensions = []

    if is_inside_main_zone and not diff_tripped and not gas_tripped:
        dimensions.append(DIM_REJECT)

    if not is_inside_main_zone and (diff_tripped or gas_tripped):
        dimensions.append(DIM_FALSE_TRIP)

    if backup_mismatch:
        dimensions.append(DIM_BACKUP_MISMATCH)

    if non_electrical_false_trip and gas_tripped:
        dimensions.append(DIM_NON_ELEC)

    if not dimensions:
        return {
            "triggered": False,
            "severity": None,
            "dimensions": [],
        }

    return {
        "triggered": True,
        "severity": "危急",
        "dimensions": dimensions,
        "remediation": (
            "核对保护定值与说明书;"
            "检查保护装置功能性;"
            "检查二次回路绝缘与接线;"
            "必要时启动保护更换评估"
        ),
    }
