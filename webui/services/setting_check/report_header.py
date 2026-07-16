from datetime import datetime
from pathlib import Path


def generate_header(
    station: str,
    device: str,
    model: str,
    version: str,
    setting_file: str,
    calc_file: str,
    rules_names: list[str],
    device_type: str = "",
    voltage_level: int = 0,
    device_params: str = "",
    ct_ratio: str = "",
    pt_ratio: str = "",
    zero_seq_ct: str = "",
    manual_found: bool = False,
    setting_code: str = "",
    setting_reason: str = "",
) -> str:
    """生成定值校核报告头部信息（匹配 setting-check-agent 模板结构）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 设备类型中文映射
    device_type_cn = {
        "transformer": "变压器",
        "line": "线路",
        "bus": "母线",
        "breaker": "母联分段",
        "capacitor": "电容器",
        "reactor": "电抗器",
        "grounding_transformer": "接地变",
        "station_transformer": "站用变",
    }.get(device_type, device_type)

    voltage_str = f"{voltage_level}kV" if voltage_level > 0 else ""
    manual_str = "已加载" if manual_found else "未找到"

    lines = [
        f"# {station} {device} 定值校核报告",
        "",
        "## 一、基本信息",
        "",
        "### 设备概况",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 厂站 | {station or '-'} |",
        f"| 设备名称 | {device or '-'} |",
        f"| 电压等级 | {voltage_str or '-'} |",
        f"| 设备类型 | {device_type_cn or '-'} |",
        f"| 设备参数 | {device_params or '-'} |",
        "",
    ]

    # CT/PT参数（如果有）
    if ct_ratio or pt_ratio or zero_seq_ct:
        lines.extend([
            "### CT/PT参数",
            "",
            "| 项目 | 定值单 | 计算书 | 是否一致 |",
            "|------|--------|--------|---------|",
            f"| CT变比 | {ct_ratio or '-'} | - | - |",
            f"| PT变比 | {pt_ratio or '-'} | — | — |",
            f"| 零序CT变比 | {zero_seq_ct or '-'} | — | — |",
            "",
            "> **折算说明**：CT变比用于电流定值一二次值折算验证（二次值=一次值/CT变比）；PT变比+CT变比用于阻抗定值一二次值折算验证（Z₂=Z₁×CT变比/PT变比）。各保护功能逐项的折算结论见折算验证列，仅输出结论不展示计算过程。",
            "> **PT变比说明**：计算书未给出PT变比时，阻抗二次值折算按电压等级取默认值：220kV→220/0.1、110kV→110/0.1、35kV→35/0.1、10kV→10/0.1。",
            "",
        ])

    lines.extend([
        "### 保护装置",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 装置型号 | {model or '-'} |",
        f"| 软件版本 | {version or '-'} |",
    ])

    if setting_code:
        lines.append(f"| 定值单编号 | {setting_code} |")
    if setting_reason:
        lines.append(f"| 整定原因 | {setting_reason} |")

    lines.extend([
        "",
        "### 校核资料",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 定值单 | {setting_file or '-'} |",
        f"| 计算书 | {calc_file or '-'} |",
        f"| 说明书 | {manual_str} |",
        f"| 整定原则 | {', '.join(rules_names) if rules_names else '-'} |",
        "",
        "---",
        "",
    ])

    return "\n".join(lines)
