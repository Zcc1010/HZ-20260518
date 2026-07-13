import json
from pathlib import Path

from webui.services.setting_check.converter import convert_to_md
from webui.services.setting_check.device_extractor import build_extraction_prompt
from webui.services.setting_check.principle_checker import build_check_prompt
from webui.services.setting_check.router import load_rules_content, route_rules
from webui.services.setting_check.report_header import generate_header

REF_DIR = Path(__file__).parent / "references"

SETTING_EXTENSIONS = {".xls", ".xlsx", ".doc", ".docx", ".pdf", ".md", ".txt"}


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


def run_pipeline(
    setting_paths: list[str],
    calc_paths: list[str],
    llm_call_func,
    output_dir: str = "",
) -> dict:
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

    agent1_prompt = build_extraction_prompt(setting_parts[0][1])
    agent1_response = llm_call_func(agent1_prompt)

    # Extract JSON from response (handle markdown code blocks or extra text)
    json_str = agent1_response.strip()
    if json_str.startswith("```"):
        # Remove markdown code block
        lines = json_str.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        json_str = "\n".join(lines).strip()

    # Try to find JSON object in the response
    import re
    json_match = re.search(r'\{[^{}]*\}', json_str, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)

    device_info = json.loads(json_str)

    station = device_info.get("station", "")
    device = device_info.get("device", "")
    model = device_info.get("model", "")
    version = device_info.get("version", "")
    device_type = device_info.get("device_type", "")
    voltage_level = device_info.get("voltage_level", 0)

    rules_content = load_rules_content(device_type, voltage_level, REF_DIR)
    rules_paths = route_rules(device_type, voltage_level, REF_DIR)
    rules_names = [p.stem for p in rules_paths]

    agent2_prompt = build_check_prompt(
        setting_md=all_setting_md,
        calc_md=all_calc_md,
        rules_content=rules_content,
        station=station,
        device=device,
        model=model,
    )
    agent2_response = llm_call_func(agent2_prompt)

    header = generate_header(
        station=station,
        device=device,
        model=model,
        version=version,
        setting_file="、".join(setting_names),
        calc_file="、".join(calc_names),
        rules_names=rules_names,
        device_type=device_type,
        voltage_level=voltage_level,
    )
    full_report = header + "\n\n" + agent2_response

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
