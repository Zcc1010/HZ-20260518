from pathlib import Path


def generate_header(
    station: str,
    device: str,
    model: str,
    version: str,
    setting_file: str,
    calc_file: str,
    rules_names: list[str],
) -> str:
    """生成定值校核报告头部信息"""
    lines = [
        "# 定值校核报告",
        "",
        "## 一、基本信息",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 厂站 | {station or '-'} |",
        f"| 设备 | {device or '-'} |",
        f"| 装置型号 | {model or '-'} |",
        f"| 软件版本 | {version or '-'} |",
        f"| 计算书 | {Path(calc_file).name if calc_file else '-'} |",
        "",
        "## 二、定值单文件",
        "",
    ]

    if setting_file:
        for name in setting_file.split("、"):
            lines.append(f"- {name.strip()}")

    lines.extend([
        "",
        "## 三、校核依据",
        "",
    ])

    if rules_names:
        for rule in rules_names:
            lines.append(f"- {rule}")
    else:
        lines.append("- 无")

    lines.extend([
        "",
        "---",
        "",
    ])

    return "\n".join(lines)
