import json
import re
from pathlib import Path

from webui.services.setting_check.converter import convert_to_md
from webui.services.setting_check.principle_checker import build_check_prompt, build_cleanup_prompt
from webui.services.setting_check.router import (
    load_rules_content,
    load_key_constraints,
    load_report_template,
    load_device_principle,
    load_upstream_template,
    load_manual_content,
    route_rules,
)

REF_DIR = Path(__file__).parent / "references"

SETTING_EXTENSIONS = {".xls", ".xlsx", ".doc", ".docx", ".pdf", ".md", ".txt"}

# 设备类型关键词 → 英文 key
_DEVICE_TYPE_KEYWORDS = {
    "变压器": "transformer",
    "主变": "transformer",
    "线路": "line",
    "母线": "bus",
    "母差": "bus",
    "母联": "breaker",
    "分段": "breaker",
    "电容器": "capacitor",
    "电抗器": "reactor",
    "接地变": "grounding_transformer",
    "站用变": "station_transformer",
}


def _collect_settings(paths: list[str]) -> list[tuple[str, str]]:
    results = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            results.append((p.name, convert_to_md(str(p))))
        elif p.is_dir():
            for f in sorted(p.iterdir()):
                if f.suffix.lower() in SETTING_EXTENSIONS:
                    results.append((f.name, convert_to_md(str(f))))
        else:
            raise FileNotFoundError(f"路径不存在: {path}")
    if not results:
        raise ValueError(f"未找到定值单文件: {paths}")
    return results


def _collect_calcs(paths: list[str]) -> list[tuple[str, str]]:
    """Collect calc files and convert to markdown."""
    results = []
    for path in paths:
        p = Path(path)
        if p.is_file():
            results.append((p.name, convert_to_md(str(p))))
        else:
            raise FileNotFoundError(f"计算书文件不存在: {path}")
    if not results:
        raise ValueError(f"未找到计算书文件: {paths}")
    return results


def _extract_device_info(setting_md: str, setting_names: list[str]) -> dict:
    """从定值单内容中提取设备信息（纯规则，不调用 LLM）。"""
    info = {
        "station": "",
        "device": "",
        "model": "",
        "version": "",
        "device_type": "",
        "voltage_level": 0,
    }

    # 从文件名提取厂站名（通常格式：{厂站}{设备}定值单.xls）
    if setting_names:
        fname = setting_names[0]
        # 去掉扩展名
        name = Path(fname).stem
        # 尝试提取厂站（取前面的中文部分）
        m = re.match(r'^([一-鿿]+(?:变|站|厂|所))', name)
        if m:
            info["station"] = m.group(1)

    # 从定值单内容提取设备类型
    for keyword, device_type in _DEVICE_TYPE_KEYWORDS.items():
        if keyword in setting_md[:5000]:  # 只看前 5000 字符
            info["device_type"] = device_type
            break

    # 从定值单内容提取电压等级
    voltage_match = re.search(r'(\d+)\s*[kK][vV]', setting_md[:3000])
    if voltage_match:
        info["voltage_level"] = int(voltage_match.group(1))

    # 从定值单内容提取装置型号
    model_match = re.search(r'(?:保护装置型号|装置型号|保护型号)[：:\s]*([A-Za-z]+-?\d+[A-Za-z]*)', setting_md[:5000])
    if model_match:
        info["model"] = model_match.group(1).strip()

    # 从定值单内容提取软件版本
    version_match = re.search(r'(?:软件版本|版本号|程序版本)[：:\s]*([^\s|]+)', setting_md[:5000])
    if version_match:
        info["version"] = version_match.group(1).strip()

    # 从定值单内容提取设备名称
    device_match = re.search(r'(?:设备名称|被保护设备|一次设备)[：:\s]*([^\n|]+)', setting_md[:5000])
    if device_match:
        info["device"] = device_match.group(1).strip()

    return info


def _extract_device_info_from_report(report: str) -> dict:
    """从 LLM 生成的报告中提取设备信息（补充/修正）。"""
    info = {}

    m = re.search(r'\|\s*厂站\s*\|\s*(.+?)\s*\|', report)
    if m:
        val = m.group(1).strip().strip('-').strip()
        if val:
            info["station"] = val

    m = re.search(r'\|\s*设备名称\s*\|\s*(.+?)\s*\|', report)
    if m:
        val = m.group(1).strip().strip('-').strip()
        if val:
            info["device"] = val

    m = re.search(r'\|\s*装置型号\s*\|\s*(.+?)\s*\|', report)
    if m:
        val = m.group(1).strip().strip('-').strip()
        if val:
            info["model"] = val

    m = re.search(r'\|\s*软件版本\s*\|\s*(.+?)\s*\|', report)
    if m:
        val = m.group(1).strip().strip('-').strip()
        if val:
            info["version"] = val

    m = re.search(r'\|\s*电压等级\s*\|\s*(\d+)\s*kV\s*\|', report)
    if m:
        info["voltage_level"] = int(m.group(1))

    m = re.search(r'\|\s*设备类型\s*\|\s*(.+?)\s*\|', report)
    if m:
        type_cn = m.group(1).strip().strip('-').strip()
        cn_to_en = {
            "变压器": "transformer",
            "线路": "line",
            "母线": "bus",
            "母联分段": "breaker",
            "电容器": "capacitor",
            "电抗器": "reactor",
            "接地变": "grounding_transformer",
            "站用变": "station_transformer",
        }
        info["device_type"] = cn_to_en.get(type_cn, type_cn)

    return info


def run_pipeline(
    setting_paths: list[str],
    calc_paths: list[str],
    llm_call_func,
    output_dir: str = "",
) -> dict:
    # Step 1: 文件转换
    setting_parts = _collect_settings(setting_paths)
    if not setting_parts:
        raise ValueError(f"未找到定值单文件: {setting_paths}")

    calc_parts = _collect_calcs(calc_paths)
    if not calc_parts:
        raise ValueError(f"未找到计算书文件: {calc_paths}")

    setting_names = [name for name, _ in setting_parts]
    all_setting_md = "\n\n---\n\n".join(
        f"## 定值单: {name}\n\n{content}"
        for name, content in setting_parts
    )

    calc_names = [name for name, _ in calc_parts]
    all_calc_md = "\n\n---\n\n".join(
        f"## 计算书: {name}\n\n{content}"
        for name, content in calc_parts
    )

    # Step 2: 从定值单内容提取设备信息（纯规则，不调用 LLM）
    device_info = _extract_device_info(all_setting_md, setting_names)
    device_type = device_info.get("device_type", "")
    voltage_level = device_info.get("voltage_level", 0)
    model = device_info.get("model", "")

    # Step 3: 加载设备专属参考材料
    rules_content = load_rules_content(device_type, voltage_level, REF_DIR)
    rules_paths = route_rules(device_type, voltage_level, REF_DIR)
    rules_names = [p.stem for p in rules_paths]

    constraints = load_key_constraints(REF_DIR)
    report_template = load_report_template(device_type, voltage_level, REF_DIR)
    device_principle = load_device_principle(device_type, voltage_level, REF_DIR)
    upstream_template = load_upstream_template(device_type, voltage_level, REF_DIR)
    manual_content = load_manual_content(device_type, model, REF_DIR) if model else ""

    # Step 4: 单次 LLM 调用（信息提取 + 校核合一）
    prompt = build_check_prompt(
        setting_md=all_setting_md,
        calc_md=all_calc_md,
        rules_content=rules_content,
        station=device_info.get("station", ""),
        device=device_info.get("device", ""),
        model=model,
        constraints=constraints,
        report_template=report_template,
        manual_content=manual_content,
        upstream_template=upstream_template,
        device_principle=device_principle,
    )
    draft = llm_call_func(prompt)

    # Step 5: Cleanup（删除推理过程）
    cleanup_prompt = build_cleanup_prompt(draft)
    report = llm_call_func(cleanup_prompt)

    # Step 6: 从报告中补充/修正设备信息
    report_info = _extract_device_info_from_report(report)
    for key, val in report_info.items():
        if val and (not device_info.get(key)):
            device_info[key] = val

    # Step 7: 写入文件
    station = device_info.get("station", "未知")
    device = device_info.get("device", "未知")

    out = Path(output_dir) if output_dir else Path("output")
    out_dir = out / f"{station}{device}定值校核"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{station}{device}定值校核报告.md"
    report_path.write_text(report, encoding="utf-8")

    return {
        "device_info": device_info,
        "rules_names": rules_names,
        "setting_files": setting_names,
        "calc_files": calc_names,
        "report_path": str(report_path),
    }
