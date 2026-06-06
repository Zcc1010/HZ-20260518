from pathlib import Path

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


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
    paths = route_rules(device_type, voltage_level, ref_dir)
    parts = []
    for p in paths:
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts)
