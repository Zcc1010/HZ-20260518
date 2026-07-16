from pathlib import Path

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 设备类型英文 → 中文映射
_DEVICE_TYPE_CN = {
    "transformer": "变压器",
    "line": "线路",
    "bus": "母线",
    "breaker": "母联分段",
    "capacitor": "电容器",
    "reactor": "电抗器",
    "grounding_transformer": "接地变",
    "station_transformer": "站用变",
}


def _voltage_prefix(voltage_level: int) -> str:
    """电压等级 → 设备类型文件名前缀"""
    if voltage_level >= 500:
        return "500kV"
    elif voltage_level >= 220:
        return "220kV"
    elif voltage_level >= 110:
        return "110kV"
    elif voltage_level >= 35:
        return "35kV"
    else:
        return "10~20kV"


def _device_type_key(device_type: str, voltage_level: int) -> str:
    """构造设备类型键名，用于匹配 principles/ 和 templates/ 下的文件"""
    cn = _DEVICE_TYPE_CN.get(device_type, device_type)
    vp = _voltage_prefix(voltage_level)

    if device_type == "transformer":
        return f"{vp}变压器"
    elif device_type == "line":
        return f"{vp}线路"
    elif device_type == "bus":
        if voltage_level >= 35:
            return f"{vp}母线"
        else:
            return "35kV及以下母线"
    elif device_type == "breaker":
        return "母联分段"
    elif device_type == "grounding_transformer":
        return "接地变"
    elif device_type == "station_transformer":
        return "站用变"
    elif device_type == "capacitor":
        return "电容器"
    elif device_type == "reactor":
        return "电抗器"
    return cn


def _sort_key(name: str) -> tuple:
    cn = name[0]
    chapter = _CN_NUM.get(cn, 0)
    section = 0
    if "§" in name:
        try:
            section = int(name.split("§")[1].split("_")[0])
        except ValueError:
            pass
    return (chapter, section)


def route_rules(device_type: str, voltage_level: int, ref_dir: Path) -> list[Path]:
    """路由到章节格式的整定原则文件（原有逻辑）"""
    files: list[str] = ["二、总则.md"]

    if device_type == "transformer":
        files.extend([
            "三、§1_一般规定.md",
            "三、§2_变压器差动保护.md",
            "三、§6_变压器辅助保护.md",
            "三、§8_变压器非电量保护.md",
        ])
        if voltage_level >= 500:
            files.append("三、§7_500kV变压器过励磁保护.md")
        if voltage_level >= 220:
            files.append("三、§3_220kV变压器后备保护.md")
        if voltage_level >= 110:
            files.append("三、§4_110kV变压器后备保护.md")
        files.append("三、§5_35kV变压器后备保护.md")

    elif device_type == "line":
        files.append("四、§1_线路一般规定.md")
        files.append("四、§8_重合闸.md")
        if voltage_level >= 220:
            files.append("四、§3_220kV终端线路保护.md")
        elif voltage_level >= 110:
            files.append("四、§4_110kV线路保护.md")
        elif voltage_level >= 35:
            files.append("四、§5_35kV线路保护.md")
        else:
            files.append("四、§6_10-20kV线路保护.md")

    elif device_type == "bus":
        files.append("五、§1_母线一般规定.md")
        if voltage_level >= 220:
            files.append("五、§2_220kV母线保护.md")
        elif voltage_level >= 110:
            files.append("五、§3_110kV母线保护.md")
        else:
            files.append("五、§4_35kV及以下母线保护.md")

    elif device_type == "breaker":
        files.append("六、§1_母联分段保护.md")

    elif device_type == "grounding_transformer":
        files.append("六、§2_接地变保护.md")

    elif device_type == "station_transformer":
        files.append("六、§3_站用变保护.md")

    elif device_type == "capacitor":
        files.append("六、§4_电容器保护.md")

    elif device_type == "reactor":
        files.append("六、§5_电抗器保护.md")

    return [ref_dir / f for f in sorted(files, key=_sort_key)]


def load_rules_content(device_type: str, voltage_level: int, ref_dir: Path) -> str:
    """加载章节格式的整定原则全文"""
    paths = route_rules(device_type, voltage_level, ref_dir)
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)


def load_device_principle(device_type: str, voltage_level: int, ref_dir: Path) -> str:
    """加载设备类型格式的整定原则（principles/{设备类型}整定原则.md）"""
    key = _device_type_key(device_type, voltage_level)
    principle_file = ref_dir / "principles" / f"{key}整定原则.md"
    if principle_file.exists():
        return principle_file.read_text(encoding="utf-8")
    return ""


def load_upstream_template(device_type: str, voltage_level: int, ref_dir: Path) -> str:
    """加载上下级定值模板（principles/{设备类型}上下级定值（模板）.md）"""
    key = _device_type_key(device_type, voltage_level)
    template_file = ref_dir / "principles" / f"{key}上下级定值（模板）.md"
    if template_file.exists():
        return template_file.read_text(encoding="utf-8")
    return ""


def load_report_template(device_type: str, voltage_level: int, ref_dir: Path) -> str:
    """加载校核报告模板（templates/校核报告模板-{设备类型}.md），无专属模板时用通用模板"""
    key = _device_type_key(device_type, voltage_level)
    template_file = ref_dir / "templates" / f"校核报告模板-{key}.md"
    if template_file.exists():
        return template_file.read_text(encoding="utf-8")
    # 回退到通用模板
    generic = ref_dir / "templates" / "校核报告模板-通用.md"
    if generic.exists():
        return generic.read_text(encoding="utf-8")
    return ""


def load_key_constraints(ref_dir: Path) -> str:
    """加载校核关键约束"""
    constraints_file = ref_dir / "校核关键约束.md"
    if constraints_file.exists():
        return constraints_file.read_text(encoding="utf-8")
    return ""


def load_manual_content(device_type: str, model: str, ref_dir: Path) -> str:
    """加载装置说明书内容（保护原理 + 定值说明）"""
    if not model:
        return ""

    manuals_dir = ref_dir / "manuals"
    if not manuals_dir.exists():
        return ""

    # 搜索匹配的说明书目录
    # nanobot-webui 的 manuals 结构: manuals/{厂家}/{型号}_{设备类型}_{章节}.md
    # 先按型号搜索
    model_upper = model.upper()
    parts = []

    for vendor_dir in manuals_dir.iterdir():
        if not vendor_dir.is_dir():
            continue
        for md_file in vendor_dir.iterdir():
            if not md_file.is_file() or not md_file.suffix == ".md":
                continue
            name = md_file.stem.upper()
            # 匹配型号前缀
            if model_upper in name or name.startswith(model_upper):
                if "保护原理" in md_file.stem or "定值说明" in md_file.stem:
                    try:
                        parts.append(md_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

    return "\n\n---\n\n".join(parts)
