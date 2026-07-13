"""load_local_data.py
本地 JSON 数据加载器。

将 5 份保信 JSON + 1 份可选检修工作数据 解析为统一的 DataPackage，
供风险评估消费。

接口契约：
    DataPackage
        ├── inventory        (台账，按 station 索引)
        ├── real_time_values (实时定值，按 (station, primary_device, set_index))
        ├── real_time_status (实时状态)
        ├── press_board      (压板/模拟量)
        ├── alarms           (历史告警，按 (station, primary_device, set_index))
        ├── maintenance      (检修工作，按 (station, primary_device))
        └── raw_paths        (源文件路径)

归一化策略：
    告警 JSON 中的 device_name 形如 "220kV崔挥2C55线路第一套保护PCS931A-G"，
    台账 device_name 形如 "崔挥 2C55 线"。两者不能直接匹配。

    本加载器做两件事：
        1. normalize_to_primary_device(name)
            → 归一到间隔级（去电压等级 + 去套后缀 + 去型号后缀）。
              例: "220kV崔挥2C55线第一套保护PCS931A-G" → "崔挥2C55线"
        2. extract_set_index(name)
            → 提取第 N 套，无则返回 None。
              例: "220kV崔挥2C55线第一套保护PCS931A-G" → 1
"""

from __future__ import annotations
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ──────────────────────────── 归一化 ────────────────────────────


_VOLTAGE_RE = re.compile(r"^\s*\d+\s*[kK]?[vV]\s*")
_TAIL_RE = re.compile(
    r"(第\s*(\d+)\s*套|第\s*([一二三四五]+)\s*套).*$"
)
_MODEL_TAIL_RE = re.compile(r"(保护|装置|微机.+?保护)\s*$")
_SUFFIX_RE = re.compile(r"(线路|线)\s*(第\s*\d+\s*套|第\s*[一二三四五]+\s*套).*$")
# 用于从告警 device_name 中剥离掉尾部修饰。
# 支持「第N套」「第二套」「二套」「N套」「第二套微机母差保护」等形态。
_TAIL_PUNCT_RE = re.compile(
    r"(?:第\s*)?[一二三四五\d]+\s*套"
    r"(?:[一-龥]+)?"
    r"(?:保护|装置)"
    r"(?:\s*[A-Z]+)?"
    r"[-\dA-Za-z]*"
    r"$"
)


def normalize_to_primary_device(name: str) -> str:
    """从告警 JSON 风格的 device_name 中提取间隔级 primary_device。

    Examples
    --------
    >>> normalize_to_primary_device("220kV崔挥2C55线路第一套保护PCS931A-G")
    '崔挥2C55线'
    >>> normalize_to_primary_device("220kV红古2C97线第一套保护CSC-103A-G")
    '红古2C97线'
    >>> normalize_to_primary_device("500kVⅠ母线第二套微机母差保护NSR-371A-GCN")
    '500kVⅠ母线'
    """
    s = name.strip()
    # 1. 去前缀电压等级
    s = _VOLTAGE_RE.sub("", s)
    # 2. 去尾部「第N套...保护」之类
    s = _TAIL_PUNCT_RE.sub("", s)
    # 3. 去尾部型号（PCS931A-G / CSC-103A-G 等）
    s = re.sub(
        r"[A-Z]+-?\d+[A-Z\d-]*$",
        "",
        s,
    )
    # 4. 去尾部「保护」「装置」「微机」等
    s = _MODEL_TAIL_RE.sub("", s)
    # 5. 整理空白
    s = re.sub(r"\s+", "", s)
    # 6. 兜底：保留"线"作尾
    if not s.endswith("线") and not s.endswith("变") and not s.endswith("母线") and not s.endswith("开关"):
        if "线" in s and s.rfind("线") > len(s) - 3:
            s = s[: s.rfind("线") + 1]
    return s


def extract_set_index(name: str) -> int | None:
    """提取第 N 套，1 表示第一套，2 表示第二套，无则返回 None。

    Examples
    --------
    >>> extract_set_index("220kV崔挥2C55线路第一套保护PCS931A-G")
    1
    >>> extract_set_index("220kV红古2C98线第二套保护PSC-931")
    2
    """
    s = name
    # 阿拉伯数字：第1套、第2套
    m = re.search(r"第\s*(\d+)\s*套", s)
    if m:
        return int(m.group(1))
    # 中文数字：第一套、第二套、第三套、第四套、第五套
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    m = re.search(r"第\s*([一二三四五])\s*套", s)
    if m:
        return cn_map.get(m.group(1))
    return None


def normalize_device_short(name: str) -> str:
    """把台账风格简名也归一（去前后空格）。"""
    return re.sub(r"\s+", "", name).strip()


# ──────────────────────────── 数据类 ────────────────────────────


@dataclass
class DeviceKey:
    """三级 device_key：厂站 + 间隔 + 第N套。"""

    station: str
    primary_device: str  # 间隔级（一次设备）
    set_index: int | None  # 第 N 套，None 表示非独立套（如失灵）

    def __hash__(self):
        return hash((self.station, self.primary_device, self.set_index))

    def __str__(self):
        s = f"{self.station}::{self.primary_device}"
        if self.set_index is not None:
            s += f"::第{self.set_index}套"
        return s


@dataclass
class IntervalKey:
    """间隔级（一次设备）。"""

    station: str
    primary_device: str

    def __hash__(self):
        return hash((self.station, self.primary_device))

    def __str__(self):
        return f"{self.station}::{self.primary_device}"


@dataclass
class MaintenanceRecord:
    """一条检修记录。"""

    primary_device: str
    start_time: str  # ISO 字符串
    end_time: str
    work_type: str  # 例: "首检", "消缺", "技改"
    description: str = ""


@dataclass
class DataPackage:
    """风险评估消费的统一数据形状。"""

    inventory: dict[IntervalKey, list[dict]] = field(default_factory=dict)
    real_time_values: dict[DeviceKey, dict] = field(default_factory=dict)
    real_time_status: dict[DeviceKey, dict] = field(default_factory=dict)
    press_board: dict[DeviceKey, dict] = field(default_factory=dict)
    alarms: dict[DeviceKey, list[dict]] = field(default_factory=lambda: defaultdict(list))
    maintenance: dict[IntervalKey, list[MaintenanceRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    raw_paths: dict[str, str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def all_device_keys(self) -> list[DeviceKey]:
        keys: set[DeviceKey] = set()
        keys.update(self.real_time_values.keys())
        keys.update(self.real_time_status.keys())
        keys.update(self.press_board.keys())
        keys.update(self.alarms.keys())
        return sorted(keys, key=str)

    def all_interval_keys(self) -> list[IntervalKey]:
        keys: set[IntervalKey] = set()
        # inventory 与 alarms 都是基于间隔级的来源
        keys.update(self.inventory.keys())
        for k in self.alarms.keys():
            keys.add(IntervalKey(k.station, k.primary_device))
        for k in self.real_time_status.keys():
            keys.add(IntervalKey(k.station, k.primary_device))
        for k in self.press_board.keys():
            keys.add(IntervalKey(k.station, k.primary_device))
        for k in self.real_time_values.keys():
            keys.add(IntervalKey(k.station, k.primary_device))
        return sorted(keys, key=str)


# ──────────────────────────── JSON 加载 ────────────────────────────


def _load_json(path: Path) -> Any:
    """统一编码处理 JSON 加载，兼容截断/不完整 JSON。"""
    raw = path.read_bytes()
    text: str | None = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "gb2312"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    import re as _re

    pat = _re.compile(r"\},\s*\n\s*\{\s*\"station_name\":")
    matches = list(pat.finditer(text))
    if matches:
        cut_pos = matches[-1].start() + 1
        recovered = text[:cut_pos] + "\n  ]\n}\n"
        try:
            return json.loads(recovered)
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    bracket_pairs = {"]": "[", "}": "{"}
    open_brackets = set(bracket_pairs.values())
    last_good = -1
    stack: list[str] = []
    in_string = False
    escape = False
    for i, c in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c in open_brackets:
            stack.append(c)
        elif c in bracket_pairs:
            if stack and stack[-1] == bracket_pairs[c]:
                stack.pop()
                if not stack:
                    try:
                        _, idx = decoder.raw_decode(text[: i + 1])
                        last_good = idx
                    except json.JSONDecodeError:
                        pass

    if last_good > 0:
        try:
            return json.loads(text[:last_good])
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(f"无法解析 {path}", text, 0)


# ──────────────────────────── 加载器 ────────────────────────────


def load_inventory(path: str | Path, data: DataPackage) -> None:
    """加载保护装置台账.json —— 按 station 索引，devices 含 set 字段。

    台账中 devices[].set 已经直接给出「第 1 套 / 第 2 套 / 母线 / 失灵」。
    """
    raw = _load_json(Path(path))
    data.meta["region"] = raw.get("region")
    data.meta["query_time"] = raw.get("query_time")
    for station in raw.get("stations", []):
        sname = station["station_name"]
        for dev in station.get("devices", []):
            short = normalize_device_short(dev["device_name"])
            set_idx = _parse_set_from_inventory(dev.get("set", ""))
            key = IntervalKey(sname, short)
            entry = {**dev, "_station": sname, "_set_index": set_idx}
            data.inventory.setdefault(key, []).append(entry)
    data.raw_paths["inventory"] = str(path)


def _parse_set_from_inventory(s: str) -> int | None:
    """台账 `set` 字段解析为 set_index。例: "第 1 套"→1, "第 2 套"→2。"""
    m = re.search(r"第\s*(\d+)\s*套", s or "")
    return int(m.group(1)) if m else None


def load_real_time_values(path: str | Path, data: DataPackage) -> None:
    """加载保护装置实时运行定值信息.json —— 单装置定值（扁平）。"""
    raw = _load_json(Path(path))
    station = raw.get("station", "")
    device = raw.get("device_name", "")
    if station and device:
        primary = normalize_to_primary_device(device)
        set_idx = extract_set_index(device) or _parse_set_from_inventory(raw.get("set", ""))
        key = DeviceKey(station, primary, set_idx)
        data.real_time_values[key] = raw
    data.raw_paths["real_time_values"] = str(path)


def load_real_time_status(path: str | Path, data: DataPackage) -> None:
    """加载保护装置实时运行状态.json —— 按 (station, primary_device, set_idx) 索引。"""
    raw = _load_json(Path(path))
    for station in raw.get("substations", []):
        sname = station["station_name"]
        for category in ("line_protections", "bus_protections", "breaker_protections"):
            for dev in station.get(category, []):
                full_name = dev["device_name"]
                primary = normalize_to_primary_device(full_name)
                set_idx = extract_set_index(full_name)
                key = DeviceKey(sname, primary, set_idx)
                data.real_time_status[key] = {
                    "_station": sname,
                    "_category": category.rstrip("_protections"),
                    "_full_name": full_name,
                    **dev,
                }
    data.raw_paths["real_time_status"] = str(path)


def load_press_board(path: str | Path, data: DataPackage) -> None:
    """加载 皋城变...压板.json —— 按 device_name 索引。"""
    raw = _load_json(Path(path))
    station = raw.get("station", "")
    for dev in raw.get("devices", []):
        full_name = dev["device_name"]
        primary = normalize_to_primary_device(full_name)
        set_idx = extract_set_index(full_name)
        key = DeviceKey(station, primary, set_idx)
        data.press_board[key] = {**dev, "_station": station, "_full_name": full_name}
    data.raw_paths["press_board"] = str(path)


def load_alarms(path: str | Path, data: DataPackage) -> None:
    """加载 保护装置告警记录.json —— 按 device_key 聚合。

    **重要**：告警 JSON 中 station_name 是数据采集时的归属标签。
    但用户的查询口径以台账 station_name 为准，红石变/挥手变等归属冲突
    在上层规则引擎处置——本加载器只做归一化键，不做归属判定。
    """
    raw = _load_json(Path(path))
    data.meta["alarm_total"] = raw.get("total_alarms")
    for station in raw.get("stations", []):
        sname = station["station_name"]
        for alarm in station.get("alarms", []):
            full_name = alarm["device_name"]
            primary = normalize_to_primary_device(full_name)
            set_idx = extract_set_index(full_name)
            key = DeviceKey(sname, primary, set_idx)
            data.alarms[key].append({**alarm, "_primary_device": primary})
    data.raw_paths["alarms"] = str(path)


def load_maintenance(path: str | Path, data: DataPackage) -> None:
    """加载 保护装置检修工作.json —— 加载间隔级检修记录。

    支持三种数据格式：
        1. JSON 数组：``[{...}, {...}, ...]``
        2. JSON 对象含 ``records`` 键：``{"records": [...]}``
        3. **JSON Lines / 裸对象拼接**（典型半人工整理）：
           ``{...}\n{...}\n{...}`` → 每行一个 JSON 对象

    数据字段：
        - station: 厂站名
        - primary_device: 间隔名（推荐）；或 device_name 全文自动归一
        - start_time: 检修开始时间 ISO 字符串
        - end_time: 检修结束时间
        - work_type: 例: "首检", "消缺", "技改", "例行检验"
        - description: 自由文本

    缺失文件时 noop，等接口样本到位后启用。
    """
    p = Path(path)
    if not p.exists():
        data.raw_paths.setdefault("maintenance", f"<not found: {path}>")
        return

    raw_text = p.read_text(encoding="utf-8")
    records: list[dict] = []

    # 尝试 1: 标准 JSON 数组
    try:
        loaded = json.loads(raw_text)
        if isinstance(loaded, list):
            records = loaded
        elif isinstance(loaded, dict) and "records" in loaded:
            records = loaded["records"]
    except json.JSONDecodeError:
        # 尝试 2: JSON Lines（每行一个 JSON 对象），含跨行字段
        # 把所有 `{...}` 块提取出来，块之间按 ", " 分隔
        # 容忍三种风格：
        #   - 单行对象: {"...": ...}
        #   - 多行对象: {\n  "...": ...,\n  "...": ...\n}
        #   - 多行对象后跟逗号: {...},\n{...},
        # 用正则匹配所有顶层 {...} 块
        import re as _re

        # 平衡大括号提取
        blocks = []
        depth = 0
        cur_start = -1
        for i, ch in enumerate(raw_text):
            if ch == "{":
                if depth == 0:
                    cur_start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and cur_start >= 0:
                    blocks.append(raw_text[cur_start : i + 1])
                    cur_start = -1

        for i, block in enumerate(blocks):
            try:
                obj = json.loads(block)
                records.append(obj)
            except json.JSONDecodeError as e:
                print(f"[load_maintenance] 第 {i+1} 块 JSON 解析失败: {e}")

    for rec in records:
        station = rec.get("station", "")
        primary = normalize_to_primary_device(
            rec.get("primary_device") or rec.get("device_name", "")
        )
        key = IntervalKey(station, primary)
        data.maintenance[key].append(
            MaintenanceRecord(
                primary_device=primary,
                start_time=rec.get("start_time", ""),
                end_time=rec.get("end_time", ""),
                work_type=rec.get("work_type", ""),
                description=rec.get("description", ""),
            )
        )
    data.raw_paths["maintenance"] = str(path)


# ──────────────────────────── 主入口 ────────────────────────────


def load_all(
    base_dir: str | Path,
    maintenance_file: str | None = None,
) -> DataPackage:
    """加载全部数据。

    Parameters
    ----------
    base_dir : str | Path
        默认指向仓库根目录的 `保护装置信息/` 文件夹。
    maintenance_file : str | Path | None
        检修工作文件路径。None 时不加载（不影响其他文件）。
    """
    base = Path(base_dir)
    pkg = DataPackage()

    files = {
        "inventory": "保护装置台账.json",
        "real_time_values": "保护装置实时运行定值信息.json",
        "real_time_status": "保护装置实时运行状态.json",
        "press_board": "皋城变保护装置实时运行软压板和硬压板和模拟量信息.json",
        "alarms": "保护装置告警记录.json",
    }
    loaders = {
        "inventory": load_inventory,
        "real_time_values": load_real_time_values,
        "real_time_status": load_real_time_status,
        "press_board": load_press_board,
        "alarms": load_alarms,
    }
    for tag, fname in files.items():
        p = base / fname
        if not p.exists():
            print(f"[load_local_data] 跳过 {p}")
            continue
        loaders[tag](p, pkg)

    if maintenance_file is not None:
        load_maintenance(maintenance_file, pkg)

    return pkg


# ──────────────────────────── 工具 ────────────────────────────


def alarm_in_maintenance_window(
    alarm_ts: str,
    maintenance_records: list[MaintenanceRecord],
) -> bool:
    """判别告警 timestamp 是否落在某条检修窗口内。

    字符串时间比较用 ISO 顺序足够（YYYY-MM-DD HH:MM:SS）。
    维护检修时段内的告警通常由检修操作引起，不计入运行风险。
    """
    if not alarm_ts or not maintenance_records:
        return False
    for rec in maintenance_records:
        if rec.start_time and rec.end_time:
            if rec.start_time <= alarm_ts <= rec.end_time:
                return True
    return False


if __name__ == "__main__":
    import sys
    base = sys.argv[1] if len(sys.argv) > 1 else "../保护装置信息"
    pkg = load_all(base)
    print("== DataPackage 概览 ==")
    print(f"  inventory (intervals): {len(pkg.inventory)}")
    print(f"  real_time_values: {len(pkg.real_time_values)}")
    print(f"  real_time_status: {len(pkg.real_time_status)}")
    print(f"  press_board: {len(pkg.press_board)}")
    print(f"  alarms: {sum(len(v) for v in pkg.alarms.values())} 条 / {len(pkg.alarms)} key")
    print(f"  maintenance: {sum(len(v) for v in pkg.maintenance.values())} 条")

    # 演示归一化
    samples = [
        "220kV崔挥2C55线路第一套保护PCS931A-G",
        "220kV红古2C98线第二套保护PCS-931A-G",
        "500kVⅠ母线第二套微机母差保护NSR-371A-GCN",
    ]
    print("\n== 归一化示例 ==")
    for s in samples:
        print(f"  '{s}' → primary='{normalize_to_primary_device(s)}', set={extract_set_index(s)}")
