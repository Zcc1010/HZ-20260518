# -*- coding: utf-8 -*-
"""
越级分析主控脚本

整合:
- Phase 1:transformer-trip-matrix skill (load + 实际vs预期对比)
- Phase 2:auto_select_fault_line + align_cross_device (真数据驱动)
- Phase 3:Rule 03008/03009/03010 (真数据触发判定)

CLI:
    python over_trip_analysis.py \
      --main-transformer-dir "事故A/保护录波/崇本变" \
      --downstream-dir "事故A/保护录波/崇本变/下级" \
      --fault-recorder-dir "事故A/故障录波" \
      --trip-matrix "data/matrices/崇本变_T1.yaml" \
      --output-dir "output/越级分析/事故A"

数据流:
    cfg/dat
      → parse_dat_to_csv.py
      → calculate_rms.py -m
      → events.csv / rms.csv / current_mutation.csv
      → auto_select_fault_line (基于rms+mutation+events)
      → align_cross_device (基于events首正突变)
      → harmonic_analysis.py → detect_ct_saturation
      → rule_03008/03009/03010
      → trip_matrix 对比
      → 越级分析报告.md
"""
import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent.parent  # .../skills

sys.path.insert(0, str(SCRIPT_DIR))
# transformer-trip-matrix 跨技能依赖：仅用于跳闸矩阵设备→断路器映射。
# 该 import 在 _device_to_brk 中已被 try/except 保护，此处仅注册搜索路径，
# 技能缺失时不影响主流程（走启发式兜底）。
_ttms_scripts = SKILLS_DIR / "transformer-trip-matrix" / "scripts"
if _ttms_scripts.exists():
    sys.path.insert(0, str(_ttms_scripts))

import auto_select_fault_line
import align_cross_device
import detect_ct_saturation

try:
    import yaml
except ImportError:
    yaml = None

from rules import rule_03008, rule_03009, rule_03010


def collect_inputs(main_dir: str, downstream_dir: str, fault_dir: str) -> dict:
    """收集各目录下的录波文件(events.csv优先;也收集cfg/dat用于预处理)"""
    out = {
        "main": {"events": [], "rms": [], "mutation": [], "cfg": [], "dat": [], "csv": []},
        "downstream": {},
        "fault_recorder": {"events": [], "rms": [], "mutation": [], "cfg": [], "dat": [], "csv": []},
    }

    def _scan(d: Path, target: dict):
        if not d.exists():
            return
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            name = p.name
            if name.endswith(".events.csv"):
                target["events"].append(p)
            elif name.endswith(".rms.csv"):
                target["rms"].append(p)
            elif name.endswith(".current_mutation.csv"):
                target["mutation"].append(p)
            elif name.endswith(".cfg"):
                target["cfg"].append(p)
            elif name.endswith(".dat"):
                target["dat"].append(p)
            elif name.endswith(".csv") and not any(
                name.endswith(s) for s in (".events.csv", ".rms.csv", ".current_mutation.csv")
            ):
                target["csv"].append(p)

    if main_dir:
        _scan(Path(main_dir), out["main"])
    if downstream_dir:
        for line_dir in sorted(Path(downstream_dir).iterdir()):
            if line_dir.is_dir():
                bucket = {"events": [], "rms": [], "mutation": [], "cfg": [], "dat": [], "csv": []}
                _scan(line_dir, bucket)
                out["downstream"][line_dir.name] = bucket
    if fault_dir:
        _scan(Path(fault_dir), out["fault_recorder"])
    return out


def run_preprocess(inputs: dict, output_root: Optional[Path] = None) -> dict:
    """对所有 cfg/dat 调用 parse_dat_to_csv + calculate_rms,产出中间 CSV

    输出到 <output_root>/_preprocess/ 下,保持原文件名。
    若 cfg/dat 已经在同目录生成过 csv/rms/events,则跳过。
    """
    if output_root is None:
        output_root = Path.cwd() / "output" / "_preprocess"
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    all_sources: List[Dict[str, Path]] = []
    for bucket in [inputs["main"], inputs["fault_recorder"]]:
        for cfg in bucket.get("cfg", []):
            dat = cfg.with_suffix(".dat")
            if dat.exists():
                all_sources.append({"cfg": cfg, "dat": dat, "side": bucket is inputs["fault_recorder"] and "fault_recorder" or "main"})
    for line_id, bucket in inputs.get("downstream", {}).items():
        for cfg in bucket.get("cfg", []):
            dat = cfg.with_suffix(".dat")
            if dat.exists():
                all_sources.append({"cfg": cfg, "dat": dat, "side": f"downstream/{line_id}"})

    if not all_sources:
        return {"preprocessed": False, "reason": "无 cfg/dat 可处理", "file_count": 0}

    csv_dir = output_root / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    cfg_paths = [str(src["cfg"]) for src in all_sources]
    cmd1 = [sys.executable, str(SCRIPT_DIR / "parse_dat_to_csv.py"), *cfg_paths, "-o", str(csv_dir)]
    print(f"  [parse] {' '.join(cmd1[1:4])} ...({len(cfg_paths)} files)")
    r1 = subprocess.run(cmd1, capture_output=True, text=True)
    if r1.returncode != 0:
        return {"preprocessed": False, "reason": f"parse_dat_to_csv 失败: {r1.stderr[:200]}", "file_count": 0}

    # 找全部 csv(parse_dat_to_csv 会按 子目录结构 输出)
    csv_files = sorted([str(p) for p in csv_dir.rglob("*.csv")])
    if not csv_files:
        return {"preprocessed": False, "reason": "parse_dat_to_csv 成功但无 csv 输出", "file_count": 0}

    # 把 cfg 复制到 csv 同目录(calculate_rms 期望 cfg 与 csv 同目录)
    for src in all_sources:
        csv_sibling = next((p for p in csv_files if Path(p).stem == src["cfg"].stem), None)
        if not csv_sibling:
            continue
        tgt_cfg = Path(csv_sibling).parent / src["cfg"].name
        if not tgt_cfg.exists():
            tgt_cfg.write_bytes(src["cfg"].read_bytes())

    cmd2 = [sys.executable, str(SCRIPT_DIR / "calculate_rms.py"), *csv_files, "-m",
            "--output", str(output_root)]
    print(f"  [rms]   {len(csv_files)} csv files")
    r2 = subprocess.run(cmd2, capture_output=True, text=True)
    rms_ok = r2.returncode == 0
    rms_stderr = r2.stderr[:500] if not rms_ok else ""

    # 统计产物:calculate_rms 的 --output 模式下,根据 csv 路径是否含"保护录波/故障录波"标记
    # 决定是写到 output_root 顶层 还是 保持子目录
    produced = {"csv": len(csv_files), "events": 0, "rms": 0, "mutation": 0}
    for src_csv in csv_files:
        stem = Path(src_csv).stem
        for ext, key in ((".events.csv", "events"), (".rms.csv", "rms"), (".current_mutation.csv", "mutation")):
            # 优先看 csv 同目录(calculate_rms 在子目录含标记时的行为)
            cand_a = Path(src_csv).parent / f"{stem}{ext}"
            # 否则看 output_root 顶层
            cand_b = output_root / f"{stem}{ext}"
            src = cand_a if cand_a.exists() else (cand_b if cand_b.exists() else None)
            if src is None:
                continue
            # 复制到 output_root 顶层(便于 glob 查找)
            tgt = output_root / src.name
            if tgt.resolve() != src.resolve():
                tgt.write_bytes(src.read_bytes())
            produced[key] += 1

    return {
        "preprocessed": True,
        "file_count": len(all_sources),
        "output_root": str(output_root),
        "produced": produced,
        "rms_stderr": rms_stderr if not rms_ok else "",
    }


def _filename_event_time(stem: str) -> Optional[datetime]:
    """从文件名提取事故真实时间(优先于 CFG 内部时间)

    模式 1(标准): "2026年02月13日04时16分07秒..." → 2026-02-13 04:16:07 (北京时间)
    模式 2(下划线): "2026_02_13_04_16_07..." → 2026-02-13 04:16:07
    """
    patterns = [
        (r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})时(\d{1,2})分(\d{1,2})秒", "年月日时分秒"),
        (r"(\d{4})_(\d{1,2})_(\d{1,2})_(\d{1,2})_(\d{1,2})_(\d{1,2})", "下划线"),
        (r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2}):(\d{1,2})", "ISO"),
    ]
    for pat, _ in patterns:
        m = re.search(pat, stem)
        if not m:
            continue
        try:
            y, mo, d, h, mi, s = [int(g) for g in m.groups()]
            return datetime(y, mo, d, h, mi, s)
        except (ValueError, TypeError):
            continue
    return None


def _device_label(p: Path) -> str:
    """从文件路径推断设备标签(用于自动选线)

    优先级:CFG设备ID > 父目录名 > 文件名(去扩展名)
    """
    parent = p.parent.name
    stem = p.stem

    # 主变识别:文件名包含 #N主变 或 父目录是 主变名
    m = re.search(r"#\d+主变", stem)
    if m:
        m2 = re.search(r"\d+开关", stem)
        if m2:
            return f"主变/{m.group(0)}/{m2.group(0)}"
        return f"主变/{m.group(0)}"

    # 出线识别:文件名包含 NN开关
    m = re.search(r"(\d+千伏)?(\d+开关)", stem)
    if m:
        return f"出线/{m.group(0)}"

    if "主变" in parent or "主变" in stem:
        return f"主变/{parent}"

    if "保护录波" in str(p):
        return f"保护录波/{parent}"
    return parent or stem


def _extract_candidate_from_mutation(mutation_csv: Path, rms_csv: Optional[Path],
                                     source_tag: str) -> Optional[dict]:
    """从 current_mutation.csv + rms.csv 提取单设备候选信息"""
    if not mutation_csv.exists():
        return None
    try:
        with open(mutation_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader, None)
            if not row:
                return None
    except Exception:
        return None

    phases = ["A", "B", "C"]
    i_max_phase = None
    i_max_value = 0.0
    pos_mutation_time_ms = None
    for p in phases:
        try:
            v = float(row.get(f"{p}相电流正突变最大值") or 0)
            t = row.get(f"{p}相正突变发生时间")
            if v > i_max_value:
                i_max_value = v
                i_max_phase = p
                if t:
                    try:
                        dt = datetime.fromisoformat(t)
                        pos_mutation_time_ms = (dt.hour * 3600 + dt.minute * 60 + dt.second) * 1000 + dt.microsecond / 1000.0
                    except Exception:
                        pass
        except (ValueError, KeyError):
            continue

    if i_max_value == 0 or pos_mutation_time_ms is None:
        return None

    if rms_csv and rms_csv.exists():
        try:
            with open(rms_csv, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                header = reader.fieldnames or []
                for r in reader:
                    if r.get("统计项") == "RMS最大值":
                        for p in phases:
                            for col_suffix in (f"I{p}A", f"IaA", f"IbA", f"IcA"):
                                if col_suffix in header:
                                    try:
                                        v = float(r[col_suffix] or 0)
                                        if v > i_max_value:
                                            i_max_value = v
                                            i_max_phase = p
                                    except ValueError:
                                        pass
                        break
        except Exception:
            pass

    label = _device_label(mutation_csv)
    return {
        "line_id": label,
        "i_max_a": round(i_max_value, 3),
        "mutation_time_ms": round(pos_mutation_time_ms, 3),
        "protection_match": True,
        "protection_zone": "I",
        "impedance_km": None,
        "line_length_km": None,
        "in_a": 600.0,
        "source": source_tag,
        "i_max_phase": i_max_phase,
    }


def run_auto_select(inputs: dict, topk: int = 3) -> dict:
    """从 current_mutation.csv + rms.csv 自动生成候选故障线路"""
    candidates = []

    for mut_path in inputs["fault_recorder"].get("mutation", []):
        rms_path = mut_path.with_name(mut_path.name.replace(".current_mutation.csv", ".rms.csv"))
        cand = _extract_candidate_from_mutation(mut_path, rms_path, "P1_故障录波器")
        if cand:
            candidates.append(cand)

    for line_id, bucket in inputs.get("downstream", {}).items():
        for mut_path in bucket.get("mutation", []):
            rms_path = mut_path.with_name(mut_path.name.replace(".current_mutation.csv", ".rms.csv"))
            cand = _extract_candidate_from_mutation(mut_path, rms_path, f"P2_{line_id}")
            if cand:
                cand["line_id"] = f"{line_id}"
                candidates.append(cand)

    for mut_path in inputs["main"].get("mutation", []):
        rms_path = mut_path.with_name(mut_path.name.replace(".current_mutation.csv", ".rms.csv"))
        cand = _extract_candidate_from_mutation(mut_path, rms_path, "P3_主变保护")
        if cand:
            candidates.append(cand)

    if not candidates:
        return {"topk": [], "all_count": 0, "candidates": []}

    top = auto_select_fault_line.select_topk(candidates, k=topk)
    return {"topk": top, "all_count": len(candidates), "candidates": candidates}


def _events_to_dict(events_csv: Path, device_id: str) -> List[dict]:
    """把 events.csv 转成 align_cross_device 期望的格式"""
    out: List[dict] = []
    if not events_csv.exists():
        return out
    try:
        with open(events_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t_str = row.get("绝对时间", "")
                channel = row.get("通道名称", "")
                content = row.get("内容", "")
                if not t_str:
                    continue
                try:
                    t = datetime.fromisoformat(t_str)
                except Exception:
                    continue
                delta = 1 if "动作" in content else (-1 if "返回" in content else 0)
                out.append({
                    "time": t,
                    "channel": channel,
                    "value": content,
                    "delta": delta,
                })
    except Exception:
        return out
    return out


def _mutation_to_dict(mutation_csv: Path, device_id: str) -> List[dict]:
    """从 current_mutation.csv 读取电流正/负突变时间,补充到对齐输入"""
    out: List[dict] = []
    if not mutation_csv.exists():
        return out
    try:
        with open(mutation_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader, None)
            if not row:
                return out
        phases = ["A", "B", "C"]
        for p in phases:
            for sign_key, sign in (("正突变发生时间", 1), ("负突变发生时间", -1)):
                t_str = row.get(f"{p}相{sign_key}")
                if not t_str:
                    continue
                try:
                    t = datetime.fromisoformat(t_str)
                    out.append({
                        "time": t,
                        "channel": f"I{p}",
                        "value": row.get(f"{p}相{'电流正突变最大值' if sign > 0 else '电流负突变最小值'}"),
                        "delta": sign,
                    })
                except Exception:
                    continue
    except Exception:
        return out
    return out


def build_events_with_filename_time(inputs: dict) -> Dict[str, List[dict]]:
    """按装置目录收集 events + mutation,统一应用文件名时间校正

    优先使用文件名时间(事故真实时间,北京时间)作为基准
    CFG 内部时间 仅用于波形相对位置
    """
    events_by_device: Dict[str, List[dict]] = {}

    def _ingest(ev_path: Path, mut_paths: List[Path], device_id: str):
        evts = _events_to_dict(ev_path, device_id)
        for mut_path in mut_paths:
            if mut_path.stem == ev_path.stem.replace(".events", ""):
                evts.extend(_mutation_to_dict(mut_path, device_id))
        if not evts:
            return
        fname_t = _filename_event_time(ev_path.stem)
        if fname_t is None:
            fname_t = _filename_event_time(Path(ev_path).with_suffix("").stem)
        if fname_t is not None:
            first_evt_t = min(e["time"] for e in evts if e.get("time"))
            if first_evt_t is not None:
                shift = (fname_t - first_evt_t).total_seconds()
                for e in evts:
                    if e.get("time") is not None:
                        e["time"] = e["time"] + timedelta(seconds=shift)
                evts[0]["_filename_time"] = fname_t
        events_by_device[device_id] = evts

    for ev_path in inputs["fault_recorder"].get("events", []):
        device_id = _device_label(ev_path)
        _ingest(ev_path, inputs["fault_recorder"].get("mutation", []), device_id)

    for ev_path in inputs["main"].get("events", []):
        device_id = f"主变_{_device_label(ev_path)}"
        _ingest(ev_path, inputs["main"].get("mutation", []), device_id)

    for line_id, bucket in inputs.get("downstream", {}).items():
        for ev_path in bucket.get("events", []):
            device_id = f"出线_{line_id}_{_device_label(ev_path)}"
            _ingest(ev_path, bucket.get("mutation", []), device_id)

    return events_by_device


def run_align(inputs: dict, ref_strategy: str = "fault_recorder_first") -> dict:
    """调用 align_cross_device,基于真实事件流(优先 events.csv,补充 mutation.csv)

    时间对齐策略:
    1. 优先使用文件名时间(事故真实时间,北京时间)作为基准
    2. CFG 内部时间(UTC) 仅用于波形相对位置
    3. 现场装置对时问题时,各装置文件名时间已带相对偏差,可基于此归并
    """
    events_by_device = build_events_with_filename_time(inputs)

    if not events_by_device:
        return {
            "ref_time": None,
            "ref_strategy": ref_strategy,
            "offsets_ms": {},
            "sync_quality": {},
            "error": "无任何事件流数据",
        }

    try:
        ref_time, offsets = align_cross_device.compute_offsets(events_by_device, ref_strategy)
        aligned = align_cross_device.apply_offsets(events_by_device, offsets)
        quality_map = align_cross_device.check_sync_quality(offsets)
        quality = {k: v.value for k, v in quality_map.items()}
    except ValueError as e:
        return {
            "ref_time": None,
            "ref_strategy": ref_strategy,
            "offsets_ms": {},
            "sync_quality": {},
            "error": str(e),
        }

    return {
        "ref_time": ref_time.isoformat() if ref_time else None,
        "ref_strategy": ref_strategy,
        "offsets_ms": {k: round(v, 3) for k, v in offsets.items()},
        "sync_quality": quality,
        "aligned_events": aligned,
    }


def run_ct_saturation(inputs: dict, harmonics_dir: str = "", main_in_a: float = 600.0) -> dict:
    """对每个电流 CSV 调用 harmonic_analysis,然后用 detect_ct_saturation 检测饱和"""
    if not harmonics_dir:
        harmonics_dir = str(Path.cwd() / "output" / "_preprocess" / "csv")
    harmonics_dir_path = Path(harmonics_dir)
    if not harmonics_dir_path.exists():
        return {}

    # latent-faults 跨技能依赖：复用其谐波分析脚本做 CT 饱和检测。
    # 脚本缺失时跳过饱和检测（不影响主流程），仅打印一次提示。
    ha_script = SKILLS_DIR / "latent-faults" / "scripts" / "harmonic_analysis.py"
    if not ha_script.exists():
        print("  [ct] latent-faults 技能未安装，跳过 CT 饱和检测")
        return {}
    csv_files = sorted(harmonics_dir_path.glob("*.csv"))
    result = {}

    for csv_path in csv_files:
        stem = csv_path.stem
        if any(stem.endswith(s) for s in (".events", ".rms", ".current_mutation", ".harmonics")):
            continue
        harmonics_csv = csv_path.with_suffix(".harmonics.csv")
        if not harmonics_csv.exists():
            try:
                r = subprocess.run(
                    [sys.executable, str(ha_script), str(csv_path)],
                    capture_output=True, text=True, timeout=120,
                )
                if r.returncode != 0:
                    print(f"  [ct] {stem}: 谐波分析失败 (rc={r.returncode})")
                    continue
            except Exception as e:
                print(f"  [ct] {stem}: 谐波分析异常 {e}")
                continue
        if not harmonics_csv.exists():
            continue
        label = _device_label(csv_path)
        try:
            sat = detect_ct_saturation.detect_saturation_for_csv(
                str(harmonics_csv), side=label, in_a=main_in_a, window_ms=40.0
            )
            result[label] = sat.get(label, {})
        except Exception as e:
            print(f"  [ct] {stem}: 饱和检测失败 {e}")

    return result


def run_rules(rule_inputs: dict) -> List[dict]:
    """执行 3 条越级规则"""
    results = []

    r008 = rule_03008.evaluate(
        main_backup_tripped=rule_inputs.get("main_backup_tripped", False),
        downstream_tripped=rule_inputs.get("downstream_tripped", False),
        downstream_brk_open=rule_inputs.get("downstream_brk_open", True),
        two_phase_grounding=rule_inputs.get("two_phase_grounding", False),
        is_outside_main_zone=rule_inputs.get("is_outside_main_zone", False),
        same_time_action=rule_inputs.get("same_time_action", False),
    )
    r008["rule_id"] = "03008"
    r008["rule_name"] = "主变后备越级"
    results.append(r008)

    r009 = rule_03009.evaluate(
        diff_tripped=rule_inputs.get("diff_tripped", False),
        diff_current_a=rule_inputs.get("diff_current_a", 0.0),
        diff_setting_a=rule_inputs.get("diff_setting_a", 10.0),
        ct_saturation=rule_inputs.get("ct_saturation", {}),
        is_outside_main_zone=rule_inputs.get("is_outside_main_zone", False),
    )
    r009["rule_id"] = "03009"
    r009["rule_name"] = "CT 饱和致主变差动误动"
    results.append(r009)

    r010 = rule_03010.evaluate(
        diff_tripped=rule_inputs.get("diff_tripped", False),
        gas_tripped=rule_inputs.get("gas_tripped", False),
        is_inside_main_zone=rule_inputs.get("is_inside_main_zone", True),
        backup_mismatch=rule_inputs.get("backup_mismatch", False),
        non_electrical_false_trip=rule_inputs.get("non_electrical_false_trip", False),
    )
    r010["rule_id"] = "03010"
    r010["rule_name"] = "主变保护未正确动作"
    results.append(r010)

    return results


def load_trip_matrix(yaml_path: str) -> Optional[dict]:
    """加载 trip-matrix YAML,失败返回 None"""
    if not yaml_path or not Path(yaml_path).exists() or yaml is None:
        return None
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def compare_actual_vs_matrix(actual_trips: List[str], matrix: Optional[dict]) -> dict:
    """对比实际跳闸范围 vs 矩阵预期

    actual_trips: 从 events.csv 提取的断路器跳闸列表,如 ["高压侧断路器"]
    """
    if not matrix:
        return {"matrix_loaded": False}

    expected_breakers = set()
    coverage_map = {}
    for item in matrix.get("trip_matrix", []):
        for brk in item.get("action", {}).get("trip_breaker", []):
            expected_breakers.add(brk)
            coverage_map.setdefault(brk, []).append(item.get("protection", ""))

    brk_mapping = {
        "高压侧": ["高压侧断路器"],
        "中压侧": ["中压侧断路器"],
        "低压侧": ["低压侧断路器1", "低压侧断路器2"],
        "出线": ["出线断路器"],
        "母联": ["母联断路器"],
    }

    actual_normalized = set()
    for trip in actual_trips:
        matched_any = False
        for key, brks in brk_mapping.items():
            if key in trip:
                # 精确匹配:若 trip 已含数字后缀(如"低压侧断路器1"),只匹配精确的
                # 否则才展开为全集
                precise_matches = [b for b in brks if trip in b or b in trip]
                if precise_matches:
                    actual_normalized.update(precise_matches)
                else:
                    actual_normalized.update(brks)
                matched_any = True
        if not matched_any:
            actual_normalized.add(trip)

    matched = actual_normalized & expected_breakers
    missing = expected_breakers - actual_normalized
    unexpected = actual_normalized - expected_breakers
    return {
        "matrix_loaded": True,
        "expected_breakers": sorted(expected_breakers),
        "actual_breakers_raw": sorted(actual_trips),
        "actual_breakers": sorted(actual_normalized),
        "matched": sorted(matched),
        "missing_expected": sorted(missing),
        "unexpected": sorted(unexpected),
        "match_rate": round(len(matched) / max(len(expected_breakers), 1) * 100, 1),
    }


def generate_report(
    rule_results: List[dict],
    candidates: List[dict],
    aligned_summary: dict,
    ct_sat: dict,
    matrix_compare: dict,
    actual_trips: List[str],
    output_path: str,
    site_name: str = "未知厂站",
    transformer_id: str = "未知主变",
) -> None:
    """生成 Markdown 报告"""
    triggered = [r for r in rule_results if r.get("triggered")]

    lines = [
        "## 七、越级跳闸判别",
        "",
        f"> 自动生成于 {datetime.now().isoformat()} · 主变:`{site_name} #{transformer_id}`",
        "",
        "### 7.1 越级规则触发结果",
        "",
        "| 规则ID | 名称 | 触发场景 | 严重度 | 是否触发 |",
        "|---|---|---|---|---|",
    ]
    for r in rule_results:
        scenario = r.get("scenario") or (",".join(r.get("dimensions", [])) if r.get("dimensions") else "-") or "-"
        lines.append(
            f"| {r['rule_id']} | {r.get('rule_name', '')} | {scenario} | "
            f"{r.get('severity') or '-'} | {'是' if r.get('triggered') else '否'} |"
        )
    lines.append("")

    lines.extend([
        "### 7.2 候选故障线路(自动选线结果)",
        "",
        "| 排名 | 设备标签 | 故障电流(A) | 突变时刻(ms) | 故障相 | 嫌疑分数 |",
        "|---|---|---|---|---|---|",
    ])
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"| {i} | {c.get('line_id', '')} | {c.get('i_max_a', '-')} | "
            f"{c.get('mutation_time_ms', '-')} | {c.get('i_max_phase', '-')} | "
            f"{c.get('score', '-')} |"
        )
    lines.append("")

    lines.extend([
        "### 7.3 跨设备时间对齐",
        "",
        f"参考时间: {aligned_summary.get('ref_time') or '-'}",
        f"参考策略: {aligned_summary.get('ref_strategy', '-')}",
    ])
    if aligned_summary.get("error"):
        lines.append(f"**警告**: {aligned_summary['error']}")
    lines.append("")
    lines.extend([
        "| 设备 | 偏移(ms) | 同步质量 |",
        "|---|---|---|",
    ])
    for dev, off in aligned_summary.get("offsets_ms", {}).items():
        quality = aligned_summary.get("sync_quality", {}).get(dev, "-")
        lines.append(f"| {dev} | {off} | {quality} |")
    lines.append("")

    lines.extend(["### 7.4 触发详情", ""])
    if not triggered:
        lines.append("> 本次分析未触发任何越级规则。")
        lines.append("")
    else:
        for r in triggered:
            lines.extend([
                f"**{r['rule_id']} {r.get('rule_name', '')}**",
                "",
                f"- 严重度: {r.get('severity', '-')}",
                f"- 证据: `{json.dumps(r.get('evidence', {}), ensure_ascii=False)}`",
                f"- 整改建议: {r.get('remediation', '-')}",
                "",
            ])

    lines.extend(["### 7.5 CT 饱和检测", ""])
    if not ct_sat:
        lines.append("> 未做 CT 饱和检测(无谐波分析 CSV 或未提供主变额定电流)。")
        lines.append("")
    else:
        lines.extend([
            "| 设备 | A 相 | B 相 | C 相 |",
            "|---|---|---|---|",
        ])
        for side, phases in ct_sat.items():
            if not isinstance(phases, dict):
                continue
            a = "饱和" if phases.get("A", {}).get("saturated") else "正常"
            b = "饱和" if phases.get("B", {}).get("saturated") else "正常"
            c = "饱和" if phases.get("C", {}).get("saturated") else "正常"
            lines.append(f"| {side} | {a} | {b} | {c} |")
        lines.append("")

    lines.extend([
        "### 7.6 跳闸矩阵对比",
        "",
    ])
    if not matrix_compare.get("matrix_loaded"):
        lines.append("> 未加载跳闸矩阵 YAML,跳过实际 vs 预期对比。")
        lines.append("")
    else:
        lines.extend([
            f"- 矩阵预期跳闸断路器({len(matrix_compare['expected_breakers'])}): {', '.join(matrix_compare['expected_breakers'])}",
            f"- 实际跳闸断路器({len(matrix_compare['actual_breakers'])}): {', '.join(matrix_compare['actual_breakers'])}",
            f"- 匹配断路器: {', '.join(matrix_compare['matched']) or '无'}",
            f"- 应跳未跳: {', '.join(matrix_compare['missing_expected']) or '无'}",
            f"- 多跳: {', '.join(matrix_compare['unexpected']) or '无'}",
            f"- 匹配率: {matrix_compare['match_rate']}%",
            "",
        ])

    over_trip_detected = any(r.get("triggered") for r in rule_results)
    primary = triggered[0] if triggered else None
    lines.extend([
        "### 7.7 推送数据(保护在线监视)",
        "",
        "```json",
        json.dumps({
            "over_trip_detected": over_trip_detected,
            "severity": primary.get("severity") if primary else "无",
            "rule_id": primary.get("rule_id") if primary else None,
            "site": site_name,
            "transformer": transformer_id,
            "candidates": [{"line_id": c.get("line_id"), "score": c.get("score"),
                            "i_max_a": c.get("i_max_a")} for c in candidates[:3]],
            "matrix_match_rate": matrix_compare.get("match_rate"),
        }, ensure_ascii=False, indent=2),
        "```",
    ])

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")


def derive_rule_inputs(aligned: dict, candidates: List[dict], events_by_device: Dict[str, list],
                       matrix_compare: dict) -> dict:
    """基于真实事件流推导 3 条规则的输入参数

    关键: same_time_action 判定
    - 主变后备与下级保护首次动作时间差 < 100ms 视为同时刻
    - 此情况下即便下级正确跳闸,主变后备不应动作 → 仍判越级(场景D)
    """
    rule_inputs = {}

    main_tripped = False
    downstream_tripped = False
    downstream_brk_open = True
    diff_tripped = False
    gas_tripped = False
    main_trip_signals = []
    downstream_trip_signals = []
    main_first_trip_time = None
    downstream_first_trip_time = None

    is_main = lambda did: (
        "主变_主变/" in did  # "主变_主变/...: 来自主变目录的主变设备
        or "主变/#" in did
        or re.search(r"主变[/_]#\d+主变", did) is not None
    )
    is_downstream = lambda did: (
        "主变_出线/" in did  # 主变目录里被误归的下级出线
        or "出线_出线/" in did
        or "出线/" in did
        or "故障录波" in did
    )

    for device_id, evts in events_by_device.items():
        last_trip_time = None
        for e in evts:
            ch = e.get("channel", "")
            val = e.get("value", "")
            is_trip_signal = (
                ("跳位" in ch or "开入" in ch) and val == "动作"
            )
            is_close_action = "合位" in ch and val == "动作"
            is_diff = ("差动" in ch or "比率" in ch) and val == "动作"
            is_gas = "瓦斯" in ch and val == "动作"
            t = e.get("time")

            if is_main(device_id):
                if is_trip_signal:
                    main_tripped = True
                    main_trip_signals.append((device_id, ch, val))
                    if main_first_trip_time is None and t is not None:
                        main_first_trip_time = t
                if is_diff:
                    diff_tripped = True
                if is_gas:
                    gas_tripped = True
            elif is_downstream(device_id):
                if is_trip_signal:
                    downstream_tripped = True
                    downstream_trip_signals.append((device_id, ch, val))
                    if downstream_first_trip_time is None and t is not None:
                        downstream_first_trip_time = t
                    last_trip_time = t
                # 拒动判定:跳闸后 1000ms 内合位再次动作 → 拒动
                if is_close_action and last_trip_time is not None and t is not None:
                    dt_ms = (t - last_trip_time).total_seconds() * 1000
                    if 0 < dt_ms < 1000:
                        downstream_brk_open = False

    same_time_action = False
    same_time_gap_ms = None
    if (main_first_trip_time is not None and downstream_first_trip_time is not None):
        same_time_gap_ms = abs((main_first_trip_time - downstream_first_trip_time).total_seconds() * 1000)
        same_time_action = same_time_gap_ms < 100  # 100ms 阈值

    rule_inputs["main_backup_tripped"] = main_tripped
    rule_inputs["downstream_tripped"] = downstream_tripped
    rule_inputs["downstream_brk_open"] = downstream_brk_open
    rule_inputs["two_phase_grounding"] = False
    rule_inputs["is_outside_main_zone"] = main_tripped and not diff_tripped
    rule_inputs["diff_tripped"] = diff_tripped
    rule_inputs["diff_current_a"] = 0.0
    rule_inputs["diff_setting_a"] = 10.0
    rule_inputs["gas_tripped"] = gas_tripped
    rule_inputs["is_inside_main_zone"] = diff_tripped
    rule_inputs["backup_mismatch"] = False
    rule_inputs["non_electrical_false_trip"] = False
    rule_inputs["same_time_action"] = same_time_action
    rule_inputs["_same_time_gap_ms"] = same_time_gap_ms

    rule_inputs["_main_trip_signals"] = main_trip_signals
    rule_inputs["_downstream_trip_signals"] = downstream_trip_signals

    if candidates:
        top1 = candidates[0]
        rule_inputs["diff_current_a"] = float(top1.get("i_max_a") or 0.0)

    return rule_inputs


def main():
    parser = argparse.ArgumentParser(description="主变越级跳闸分析")
    parser.add_argument("--main-transformer-dir", required=True)
    parser.add_argument("--downstream-dir", default="")
    parser.add_argument("--fault-recorder-dir", default="")
    parser.add_argument("--trip-matrix", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--main-in-a", type=float, default=600.0,
                        help="主变高压侧额定电流(二次值,A),用于 CT 饱和检测")
    parser.add_argument("--no-preprocess", action="store_true",
                        help="跳过预处理(若中间 CSV 已生成)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inputs = collect_inputs(args.main_transformer_dir, args.downstream_dir, args.fault_recorder_dir)
    main_files = inputs["main"]
    down_count = sum(len(b["events"]) for b in inputs["downstream"].values())
    fault_files = inputs["fault_recorder"]
    print(f"[1] 输入收集: 主变 {len(main_files['events'])} 事件, "
          f"下级 {down_count} 事件 ({len(inputs['downstream'])} 条线路), "
          f"故障录波 {len(fault_files['events'])} 事件")

    if not args.no_preprocess:
        preprocess_root = out_dir / "_preprocess"
        pp = run_preprocess(inputs, output_root=preprocess_root)
        print(f"[2] 预处理: csv={pp.get('produced', {}).get('csv', 0)} "
              f"events={pp.get('produced', {}).get('events', 0)} "
              f"rms={pp.get('produced', {}).get('rms', 0)} "
              f"mutation={pp.get('produced', {}).get('mutation', 0)}")
        inputs = collect_inputs(args.main_transformer_dir, args.downstream_dir, args.fault_recorder_dir)
        if pp.get("output_root"):
            for bucket in [inputs["main"], inputs["fault_recorder"]]:
                bucket["events"].clear()
                bucket["rms"].clear()
                bucket["mutation"].clear()
            for p in Path(pp["output_root"]).glob("*.events.csv"):
                inputs["main"]["events"].append(p)
            for p in Path(pp["output_root"]).glob("*.rms.csv"):
                inputs["main"]["rms"].append(p)
            for p in Path(pp["output_root"]).glob("*.current_mutation.csv"):
                inputs["main"]["mutation"].append(p)
            print(f"[2.5] 重扫描: events={len(inputs['main']['events'])} "
                  f"rms={len(inputs['main']['rms'])} mutation={len(inputs['main']['mutation'])}")

    sel = run_auto_select(inputs, topk=args.topk)
    Path(out_dir / "candidate_lines.json").write_text(
        json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[3] 自动选线: Top-{args.topk} {len(sel['topk'])} 条 / 共 {sel['all_count']} 条候选")

    aligned = run_align(inputs)
    Path(out_dir / "aligned_events.json").write_text(
        json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[4] 时间对齐: 参考 {aligned.get('ref_time') or '-'}, "
          f"{len(aligned.get('offsets_ms', {}))} 设备")

    harmonics_dir = str(Path(pp["output_root"]) / "csv") if pp.get("output_root") else ""
    ct_sat = run_ct_saturation(inputs, harmonics_dir=harmonics_dir, main_in_a=args.main_in_a)
    Path(out_dir / "ct_saturation.json").write_text(
        json.dumps(ct_sat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[5] CT 饱和: {len(ct_sat)} 设备")

    matrix = load_trip_matrix(args.trip_matrix)
    site_name = "未知厂站"
    transformer_id = "未知主变"
    if matrix:
        site_name = matrix.get("transformer", {}).get("site", site_name)
        transformer_id = matrix.get("transformer", {}).get("id", transformer_id)

    events_by_device = build_events_with_filename_time(inputs)

    rule_inputs = derive_rule_inputs(aligned, sel["topk"], events_by_device, None)

    main_trip_signals = rule_inputs.pop("_main_trip_signals", [])
    downstream_trip_signals = rule_inputs.pop("_downstream_trip_signals", [])

    actual_trips_raw = []
    actual_trips_normalized = set()
    brk_mapping = {
        "高压侧": ["高压侧断路器"],
        "中压侧": ["中压侧断路器"],
        "低压侧": ["低压侧断路器1", "低压侧断路器2"],
    }

    def _device_to_brk(device_id: str) -> list:
        # 优先用 trip matrix 推断(支持 2 绕组 / 3 绕组)
        if matrix:
            try:
                from query_matrix import map_device_to_breakers
                brks = map_device_to_breakers(matrix, device_id)
                if brks:
                    return brks
            except Exception:
                pass
        # 兜底:启发式匹配
        if "主变/" in device_id:
            tail = device_id.split("主变/", 1)[1]
            if "101" in tail or "高压" in tail:
                return ["高压侧断路器"]
            if "102" in tail:
                # 102 在 3 绕组 = 中压,在 2 绕组 = 低压
                return ["低压侧断路器1", "低压侧断路器2"]
            if "201" in tail or "202" in tail:
                return ["低压侧断路器1", "低压侧断路器2"]
        return []

    for device_id, ch, val in main_trip_signals:
        actual_trips_raw.append(f"{device_id}/{ch}")
        actual_trips_normalized.update(_device_to_brk(device_id))

    # 下级出线不在主变跳闸矩阵内(矩阵仅主变本体出口)。此处按保护配置/故障点归类为"出线断路器",用于越级"应跳未跳"判定,非矩阵对比
    for device_id, ch, val in downstream_trip_signals:
        actual_trips_raw.append(f"{device_id}/{ch}")
        # 下级出线:主变跳闸矩阵中无此设备,按保护配置归类为出线断路器(越级判定用,非矩阵映射)
        brks = _device_to_brk(device_id)
        if brks and "出线断路器" in brks:
            actual_trips_normalized.update(brks)
        else:
            # 下级线 = 出线断路器(直接归类,用于越级分析)
            actual_trips_normalized.add("出线断路器")

    matrix_compare = compare_actual_vs_matrix(list(actual_trips_normalized), matrix)
    if actual_trips_raw:
        matrix_compare["actual_breakers_raw"] = actual_trips_raw

    rule_inputs["ct_saturation"] = ct_sat
    print(f"[6] 规则输入: {json.dumps({k: v for k, v in rule_inputs.items() if not k.startswith('_')}, ensure_ascii=False)}")

    rule_results = run_rules(rule_inputs)
    Path(out_dir / "越级分析结果.json").write_text(
        json.dumps(rule_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    generate_report(
        rule_results=rule_results,
        candidates=sel["topk"],
        aligned_summary=aligned,
        ct_sat=ct_sat,
        matrix_compare=matrix_compare,
        actual_trips=actual_trips_raw,
        output_path=str(out_dir / "越级分析报告.md"),
        site_name=site_name,
        transformer_id=transformer_id,
    )
    print(f"[7] 报告已生成: {out_dir / '越级分析报告.md'}")


if __name__ == "__main__":
    main()