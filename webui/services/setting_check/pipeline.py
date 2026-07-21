import json
import re
from pathlib import Path

from webui.services.setting_check.converter import convert_to_md
from webui.services.setting_check.principle_checker import build_check_prompt, build_cleanup_prompt
from webui.services.setting_check.report_header import generate_header
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
    # 方法1: 从设备名称中提取（如 "220kV变压器"、"35kV线路"）
    voltage_match = re.search(r'(\d+)\s*[kK][vV]', setting_md[:5000])
    if voltage_match:
        info["voltage_level"] = int(voltage_match.group(1))

    # 方法2: 如果设备名称中没有电压等级，从PT一次值推断
    if info["voltage_level"] == 0:
        # PT一次值格式: 高压侧PT一次值（千伏）= 220 或 PT一次值 = 220
        pt_match = re.search(r'(?:高压侧PT一次值|PT一次值)[^=]*=\s*(\d+)', setting_md[:5000])
        if pt_match:
            pt_val = int(pt_match.group(1))
            # 根据PT一次值推断电压等级
            if pt_val >= 200:
                info["voltage_level"] = 220
            elif pt_val >= 100:
                info["voltage_level"] = 110
            elif pt_val >= 30:
                info["voltage_level"] = 35
            elif pt_val >= 10:
                info["voltage_level"] = 10

    # 方法3: 从额定电压字段提取（处理XLS转换后的格式）
    # XLS转换后格式: | 5 | 高压侧额定电压（千伏） | ... | 230 |
    if info["voltage_level"] == 0:
        lines = setting_md[:8000].split('\n')
        for line in lines:
            # 查找包含额定电压的行（可能有编码问题，使用宽松匹配）
            if '额定电压' in line or ('千伏' in line and re.search(r'\|\s*\d{2,3}\s*\|', line)):
                # 提取数字（通常是 230、117、38 等）
                numbers = re.findall(r'\|\s*(\d{2,3})\s*\|', line)
                if numbers:
                    # 取第一个数字作为高压侧额定电压
                    rated_v = int(numbers[0])
                    if rated_v >= 200:
                        info["voltage_level"] = 220
                        break
                    elif rated_v >= 100:
                        info["voltage_level"] = 110
                        break
                    elif rated_v >= 30:
                        info["voltage_level"] = 35
                        break

    # 方法4: 从PT变比推断（如 "220kV/100V"）
    if info["voltage_level"] == 0:
        pt_ratio_match = re.search(r'(\d+)\s*[kK][vV]\s*/\s*\d+\s*[vV]', setting_md[:5000])
        if pt_ratio_match:
            pt_kv = int(pt_ratio_match.group(1))
            if pt_kv >= 200:
                info["voltage_level"] = 220
            elif pt_kv >= 100:
                info["voltage_level"] = 110
            elif pt_kv >= 30:
                info["voltage_level"] = 35

    # 尝试从表格格式提取设备信息
    # 格式1: | 设备所属 | 设备名称 | 装置型号 | 软件版本号 |
    # 格式2: | 设备所属 | ... | 一次设备名称 | ... | 保护装置型号 | ... | (XLS格式，中间有空列)
    # 格式3: 设备所属 ... 一次设备名称 ... 保护装置型号 ... (管道分隔但无表头行)

    # 先尝试标准表格格式
    table_match = re.search(
        r'\|\s*设备所属\s*\|\s*设备名称\s*\|.*?\|\s*装置型号\s*\|\s*软件版本号\s*\|\s*\n'
        r'\|[-\s:|]+\|\s*\n'
        r'\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|.*?\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|',
        setting_md[:5000],
        re.DOTALL
    )
    if table_match:
        info["station"] = info["station"] or table_match.group(1).strip()
        info["device"] = table_match.group(2).strip()
        info["model"] = table_match.group(3).strip()
        info["version"] = table_match.group(4).strip()
    else:
        # 尝试从 XLS 转换后的格式提取（管道分隔，可能有空列）
        # 查找包含设备信息的行
        lines = setting_md[:8000].split('\n')
        for i, line in enumerate(lines):
            # 查找包含"设备所属"的行，确定列位置
            if '设备所属' in line and '一次设备名称' in line:
                cols = [c.strip() for c in line.split('|')]
                # 找到各字段的列索引
                station_idx = next((j for j, c in enumerate(cols) if '设备所属' in c), -1)
                device_idx = next((j for j, c in enumerate(cols) if '一次设备名称' in c or '设备名称' in c), -1)
                model_idx = next((j for j, c in enumerate(cols) if '保护装置型号' in c or '装置型号' in c), -1)
                version_idx = next((j for j, c in enumerate(cols) if '装置版本' in c or '软件版本' in c), -1)

                # 下一行是数据行
                if i + 1 < len(lines):
                    data_line = lines[i + 1]
                    data_cols = [c.strip() for c in data_line.split('|')]

                    if station_idx >= 0 and station_idx < len(data_cols) and data_cols[station_idx]:
                        info["station"] = info["station"] or data_cols[station_idx]
                    if device_idx >= 0 and device_idx < len(data_cols) and data_cols[device_idx]:
                        info["device"] = data_cols[device_idx]
                    if model_idx >= 0 and model_idx < len(data_cols) and data_cols[model_idx]:
                        info["model"] = data_cols[model_idx]

                # 版本可能在下一行或隔一行
                if i + 2 < len(lines):
                    version_line = lines[i + 2]
                    if '版本' in version_line or 'V' in version_line:
                        version_cols = [c.strip() for c in version_line.split('|')]
                        # 查找版本号（通常格式：V数字.数字）
                        for vc in version_cols:
                            if re.match(r'^V\d+', vc):
                                info["version"] = vc
                                break
                break

        # 如果表格格式没找到，降级到 key：value 格式提取
        if not info["model"]:
            model_match = re.search(r'(?:保护装置型号|装置型号|保护型号)[：:\s]*([A-Za-z]+-?\d+[A-Za-z]*)', setting_md[:5000])
            if model_match:
                info["model"] = model_match.group(1).strip()

        if not info["version"]:
            version_match = re.search(r'(?:软件版本|版本号|程序版本|装置版本)[：:\s]*([^\s|]+)', setting_md[:5000])
            if version_match:
                info["version"] = version_match.group(1).strip()

        if not info["device"]:
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

    # Step 4: 先生成报告头部，再让 LLM 生成正文
    header = generate_header(
        station=device_info.get("station", ""),
        device=device_info.get("device", ""),
        model=device_info.get("model", ""),
        version=device_info.get("version", ""),
        setting_file=", ".join(setting_names),
        calc_file=", ".join(calc_names),
        rules_names=rules_names,
        device_type=device_type,
        voltage_level=voltage_level,
    )

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
        report_header=header,
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

    # Step 7: 拼接头部 + 报告正文，写入文件
    full_report = header + report

    station = device_info.get("station", "未知")
    device = device_info.get("device", "未知")

    out = Path(output_dir) if output_dir else Path("output")
    out_dir = out / f"{station}{device}定值校核"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{station}{device}定值校核报告.md"
    report_path.write_text(full_report, encoding="utf-8")

    return {
        "device_info": device_info,
        "rules_names": rules_names,
        "setting_files": setting_names,
        "calc_files": calc_names,
        "report_path": str(report_path),
    }
