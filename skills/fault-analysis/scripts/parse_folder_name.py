# -*- coding: utf-8 -*-
"""
parse_folder_name.py —— 根据波形所在【文件夹名称 / 路径】推断厂站、设备名称、保护套别。

适用场景（comtrade-parser 电压等级开关前置步骤）：
  录波文件夹通常以“事故文件夹/厂站/设备描述/”层级组织，设备描述目录名即编码了：
    · 电压等级     例：500kV、220kV
    · 设备类型     例：线路（光差/纵差/距离）、断路器（开关保护）、母差、主变、配电设备
    · 设备名称     例：陕嘉Ⅱ回线、5042（断路器编号）
    · 保护套别     例：第一套 / 第二套
    · 装置型号     例：PCS931AG、PRS753NA、PCS921A
    · 3/2 中边开关 例：断路器编号末位 2=中、1/3=边（完整串 X2 中、X1/X3 边）

输入：文件路径（*.cfg/dat/hdr/zip）或设备文件夹路径，或多个路径。
  · 若指向文件 → 取其所在目录为“设备文件夹”。
  · 若指向目录且直接含录波文件（或含多个设备子目录）→ 自动发现每个设备文件夹并逐个解析。
输出：终端表格（默认）+ 可选 --json 结构化结果。

置信度/待核实：无法从名称确定的项（如电压、厂站为容器名）一律标注 needs_review，
  绝不臆造；最终以 HDR 内容校验（保持“HDR内容 > 目录名称 > 用户确认”原则）。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

# ----------------------------------------------------------------------------
# 1. 设备类型关键词 → 标准化类型
#    顺序即优先级：断路器/开关 > 母差 > 配电 > 主变 > 线路（线路关键词最泛，放最后作兜底）
#    注意：配电(站用变/接地变含“变”)须排在 主变 之前；主变仅认“主变/变压器”，
#          不用裸“变”，以免 站用变/接地变 被误判为主变。
# ----------------------------------------------------------------------------
TYPE_KEYWORDS = [
    ("breaker", ["断路器", "开关", "失灵", "breaker"]),               # 开关保护（断路器保护）
    ("busbar", ["母差", "母线", "busbar", "bus"]),                    # 母差保护
    ("distribution", ["电容器", "电容", "电抗器", "电抗", "站用变",     # 配电设备
                      "接地变", "所用变", "配电"]),
    ("transformer", ["主变", "变压器"]),                               # 主变保护
    ("line", ["光差", "纵差", "分相电流差动", "线路", "回线", "线"]), # 线路保护（兜底）
]
TYPE_CN = {
    "line": "线路保护",
    "breaker": "开关保护（断路器保护）",
    "busbar": "母差保护",
    "transformer": "主变保护",
    "distribution": "配电设备",
    None: "待核实",
}

# 制造厂典型装置型号前缀（用于从名称取"型号"，避免把 L5011A 这类设备编号误当型号）
MODEL_PREFIXES = ["PCS", "PRS", "CSC", "NSR", "RCS", "BP", "WBC", "ISA",
                   "SAC", "SEL", "GE", "ABB", "SIEMENS", "NR", "GUID",
                   "WXH", "WHX"]  # 许继（XJ）线路/辅助保护型号前缀
MODEL_RE = re.compile(
    r"(?i)(?:%s)\-?\d{1,4}[\-A-Za-z]*" % "|".join(MODEL_PREFIXES))

# 套别中文数字
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4,
          "Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4}
# 套别关键词 → (数字, 规范中文"第X套"）
SET_KW = [
    ("第一套", 1), ("第1套", 1), ("一套", 1),
    ("第二套", 2), ("第2套", 2), ("二套", 2),
    ("第三套", 3), ("第3套", 3), ("三套", 3),
    ("第四套", 4), ("第4套", 4), ("四套", 4),
]
CN_SET = {1: "第一套", 2: "第二套", 3: "第三套", 4: "第四套"}

# 套别层关键词（位于 厂站 与 设备文件夹 之间，如 第一套/第二套，非厂站本身，
# 推断厂站时需“跳过”这一层继续上溯）
SET_FOLDER_KW = ["第一套", "第二套", "第三套", "第四套",
                 "第1套", "第2套", "第3套", "第4套",
                 "一套", "二套", "三套", "四套"]

# 设备文件夹名本身含厂站特征词（变/站/厂/工区）时的回退提取
STATION_RE = re.compile(r"([\u4e00-\u9fff]{1,}(?:变|站|厂|工区))")

# 容器/事故层关键词（父目录若是这些，则厂站需另寻或待核实）
CONTAINER_KW = ["保护录波", "故障录波", "录波", "事故", "output", "提取",
                 "extracted", "分析", "波形", "data", "files", "zip"]


def _strip_tokens(text: str, tokens: list[str]) -> str:
    """从 text 中删除给定 token（及型号整串）。空 token 直接跳过，
    否则 str.replace('', ' ') 会在每个字符间插入空格。"""
    for t in tokens:
        if not t:
            continue
        text = text.replace(t, " ")
    return text


def parse_device_name(name: str, station: str | None = None) -> dict:
    """解析【设备文件夹名称】→ 结构化元数据。station 为已知厂站（用于清理设备名前缀）。"""
    raw = name.strip()
    text = raw
    needs = []  # 待核实项

    # —— 电压等级 ——
    m = re.search(r"(\d{2,4})\s*[kK][vV]", text)
    voltage_kv = int(m.group(1)) if m else None
    if voltage_kv is None:
        needs.append("电压等级：目录名无 xxkV，需从 HDR/PT 变比确认")

    # —— 装置型号（制造厂前缀）——
    mm = MODEL_RE.search(text)
    model = mm.group(0).upper() if mm else None

    # —— 保护套别 ——
    set_no, set_cn = None, None
    for kw, num in SET_KW:
        if kw in text:
            set_no, set_cn = num, CN_SET[num]
            break
    if set_no is None:
        m = re.search(r"([一二三ⅠⅡⅢ])\s*套", text)
        if m:
            n = CN_NUM[m.group(1)]
            set_no, set_cn = n, CN_SET[n]
    if set_no is None:
        # 线路常以 A/B（第1/2套）或 I/II 后缀区分；母线 II 母等不在设备名
        if re.search(r"[AB]\b", text) and "断路器" not in text and "母" not in text:
            # 如 L5011A → 第1套；仅作弱提示，不强行判定
            pass

    # —— 设备类型 ——
    low = text.lower()
    device_type = None
    for t, kws in TYPE_KEYWORDS:
        if any(k.lower() in low for k in kws):
            device_type = t
            break
    if device_type is None:
        needs.append("设备类型：目录名无明确关键词，需从 HDR/通道确认")

    # —— 设备名称（先按类型取，再清理）——
    breaker_no = None
    device_name = raw
    if device_type == "breaker":
        # 断路器编号：去掉型号串后取首个 3~4 位独立数字（避免吞掉型号里的 921）
        cand = text.replace(model, " ") if model else text
        mb = re.search(r"(?<!\d)(\d{3,4})(?!\d)", cand)
        if mb:
            breaker_no = mb.group(1)
        # 清理：型号、类型词、保护
        device_name = _strip_tokens(
            device_name, [model or "", "断路器", "开关", "保护", "失灵"])
        device_name = device_name.strip(" _-")
        if breaker_no:
            device_name = breaker_no
    else:
        # 清理：先去时间戳，再剥电压/型号/套别/类型关键词/保护/装置/厂站前缀/冗余符
        device_name = raw
        # 文件名常带录波时刻，先整体去除（如 2026-06-28 11_23_57.368）
        device_name = re.sub(
            r"\d{4}[-_]\d{2}[-_]\d{2}[ T_]?\d{2}[_]\d{2}[_]\d{2}(?:\.\d+)?", " ", device_name)
        device_name = re.sub(r"\d{1,2}[:_]\d{2}[:_]\d{2}(?:\.\d+)?", " ", device_name)
        tokens = [model or "", f"{voltage_kv}kV" if voltage_kv else "",
                  "第一套", "第二套", "第三套", "第四套", "第1套", "第2套",
                  "第3套", "第4套", "一套", "二套", "三套", "四套",
                  "断路器", "开关", "失灵", "母差", "母线",
                  "光差", "纵差", "分相电流差动", "线路",
                  "距离", "保护", "装置",
                  (station or ""), "安徽", ".", "_", " "]
        device_name = _strip_tokens(device_name, tokens)
        device_name = device_name.replace(" ", "").strip(" _-")
        if not device_name:
            # 清理过头：先剥掉型号/保护/装置再试，仍空才回退原名
            device_name = _strip_tokens(raw, [model or "", "保护", "装置"]).replace(" ", "").strip(" _-")
            if not device_name:
                device_name = raw
                needs.append("设备名称：清理后为空，已回退为原目录名，请核对")

    # —— 3/2 中边开关（仅断路器且编号完整）——
    middle_edge = None
    edge_note = ""
    if device_type == "breaker" and breaker_no:
        last = breaker_no[-1]
        if last == "2":
            middle_edge = "中"
        elif last in ("1", "3"):
            middle_edge = "边"
        else:
            middle_edge = None
            edge_note = "末位非1/2/3，中边无法按编号判定"
    # 单套标注（断路器保护通常不分套，但同串多台时以中边区分）
    set_label = set_cn or ("单套" if device_type == "breaker" else None)

    return {
        "device_folder": raw,
        "voltage_kv": voltage_kv,
        "device_type": device_type,
        "device_type_cn": TYPE_CN[device_type],
        "device_name": device_name or None,
        "set_no": set_no,
        "set_cn": set_label,
        "model": model,
        "breaker_no": breaker_no,
        "middle_edge": middle_edge,          # 中 / 边 / None
        "middle_edge_rule": ("完整串 X2=中、X1/X3=边（按编号末位）" if middle_edge else None),
        "needs_review": needs + ([edge_note] if edge_note else []),
    }


def _guess_type(name: str) -> str | None:
    """从名称快速猜测设备类型（供 infer_station 在未知类型时回退判断）。"""
    low = name.lower()
    for t, kws in TYPE_KEYWORDS:
        if any(k.lower() in low for k in kws):
            return t
    return None


def _extract_station_from_name(name: str, device_type: str | None) -> str | None:
    """设备文件夹名本身含厂站特征词（变/站/厂/工区）时的回退提取。
    仅对线路/开关类启用，避免主变/配电/母差的设备名被误当厂站。"""
    dt = device_type or _guess_type(name)
    if dt not in ("line", "breaker"):
        return None
    m = STATION_RE.search(name)
    if not m:
        return None
    cand = m.group(1)
    # 排除设备类型关键词本身（主变/站用变/接地变/母差/电容器/电抗器等）
    if any(k in cand for k in ("主变", "站用变", "接地变", "电容器", "电抗器", "母线", "母差")):
        return None
    return cand


def infer_station(device_dir: Path, root: Path | None = None,
                  device_type: str | None = None, device_folder: str | None = None) -> dict:
    """从设备文件夹【向上】推断厂站。
    · 父目录为容器/事故层 → 厂站待核实(low)
    · 父目录为“套别层”(第一套/第二套…) → 跳过继续上溯，取真实厂站目录
    · 仍无法从路径确定时，回退到设备文件夹名中的厂站特征词(medium)
    """
    cur = device_dir.parent
    while True:
        if cur.name in CONTAINER_KW or (root is not None and cur == root):
            # 抵达容器/事故层或 root：路径法无厂站
            fb = _extract_station_from_name(device_folder or device_dir.name, device_type)
            if fb:
                return {"station": fb, "station_confidence": "medium",
                        "station_note": "目录层级无厂站，已从设备文件夹名提取厂站特征词，HDR 校验"}
            return {"station": None, "station_confidence": "low",
                    "station_note": "父目录为容器/事故层，厂站需从 HDR 或用户确认"}
        if any(kw in cur.name for kw in SET_FOLDER_KW):
            # 套别层（第一套/第二套…）非厂站，继续上溯
            if cur.parent != cur:
                cur = cur.parent
                continue
            break
        return {"station": cur.name, "station_confidence": "high", "station_note": ""}
    fb = _extract_station_from_name(device_folder or device_dir.name, device_type)
    if fb:
        return {"station": fb, "station_confidence": "medium",
                "station_note": "目录层级无厂站，已从设备文件夹名提取厂站特征词，HDR 校验"}
    return {"station": None, "station_confidence": "low",
            "station_note": "父目录为容器/事故层，厂站需从 HDR 或用户确认"}


def _is_comtrade_file(p: Path) -> bool:
    return p.suffix.lower() in (".cfg", ".dat", ".hdr", ".zip")


def discover_device_dirs(path: Path, root: Path | None = None, _depth: int = 0):
    """发现给定路径下所有【设备文件夹】（直接含录波文件的最深目录）。"""
    dirs: list[Path] = []
    if path.is_file():
        if _is_comtrade_file(path):
            dirs.append(path.parent)
        return dirs
    # 目录：若直接含录波文件 → 自身即设备文件夹
    if any(_is_comtrade_file(p) for p in path.iterdir() if p.is_file()):
        dirs.append(path)
        return dirs
    # 否则递归子目录（限深 6，覆盖 事故/厂站/套别/设备描述 等多层结构）
    if _depth < 6:
        for sub in sorted(p for p in path.iterdir() if p.is_dir()):
            dirs.extend(discover_device_dirs(sub, root, _depth + 1))
    return dirs


def parse_path(path: Path, root: Path | None = None, station_override: str | None = None) -> dict:
    meta = parse_device_name(path.name)
    st = infer_station(path, root, device_type=meta.get("device_type"),
                       device_folder=path.name)
    if station_override:
        st = {"station": station_override, "station_confidence": "override",
               "station_note": "用户/命令行显式指定"}
    # 已知厂站回填到设备名清理（剥离厂站前缀）
    if st.get("station") and st["station_confidence"] in ("high", "medium", "override"):
        meta = parse_device_name(path.name, station=st["station"])
    meta.update(st)
    meta["path"] = str(path)
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="根据波形文件夹名称推断厂站/设备名称/保护套别等元数据")
    ap.add_argument("paths", nargs="+", help="录波文件或设备/事故文件夹路径（可多个）")
    ap.add_argument("--root", help="事故根目录（用于判定厂站层级）", default=None)
    ap.add_argument("--station", help="显式指定厂站（覆盖推断）", default=None)
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非表格")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else None
    collected: list[Path] = []
    for p in args.paths:
        pp = Path(p)
        if not pp.exists():
            print(f"[跳过] 路径不存在: {p}", file=sys.stderr)
            continue
        collected.extend(discover_device_dirs(pp.resolve(), root))

    # 去重
    seen, device_dirs = set(), []
    for d in collected:
        if d not in seen:
            seen.add(d)
            device_dirs.append(d)

    if not device_dirs:
        print("[提示] 未在任何路径下发现录波文件（cfg/dat/hdr/zip）。", file=sys.stderr)
        return 1

    results = [parse_path(d, root, args.station) for d in device_dirs]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    # 表格输出（Markdown，规避 CJK 等宽对齐问题）
    print("| 厂站 | 设备名称 | 类型 | 套别 | 电压 | 型号 | 中/边 | 备注(待核实) |")
    print("|------|----------|------|------|------|------|-------|--------------|")
    for r in results:
        note = "；".join(r.get("needs_review") or [])
        if r.get("station_note"):
            note = (note + " ｜ " + r["station_note"]).strip(" ｜")
        print("| {station} | {name} | {type} | {setc} | {volt} | {model} | {me} | {note} |".format(
            station=r.get("station") or "待核实",
            name=r.get("device_name") or "待核实",
            type=r.get("device_type_cn") or "待核实",
            setc=r.get("set_cn") or "—",
            volt=f"{r['voltage_kv']}kV" if r.get("voltage_kv") else "—",
            model=r.get("model") or "—",
            me=r.get("middle_edge") or "—",
            note=note or "—",
        ))
    print(f"\n共解析 {len(results)} 个设备文件夹。"
          f"厂站/设备/套别以目录名推断，标注“待核实”的须用 HDR 校验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
