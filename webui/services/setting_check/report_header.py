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
) -> str:
    """生成定值校核报告头部信息（匹配 setting-check-web-2 模板结构）"""
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
        "### 保护装置",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 装置型号 | {model or '-'} |",
        f"| 软件版本 | {version or '-'} |",
        "",
        "### 校核资料",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 定值单 | {setting_file or '-'} |",
        f"| 计算书 | {calc_file or '-'} |",
        f"| 整定原则 | {', '.join(rules_names) if rules_names else '-'} |",
        "",
        "---",
        "",
    ]

    return "\n".join(lines)
