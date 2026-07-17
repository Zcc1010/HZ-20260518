"""run_risk_assessment.py
继电保护运行风险评估智能体的主评估逻辑（v2 重写版）。

修订内容：
1. **告警状态机**：对 (装置, status_name) 时间序列分析
    - 当前最后一条是「复归」→ 信号已消除，不计入风险（默认情形）
    - 当前最后一条是「告警」→ 信号持续活跃，强信号
2. **频发抖动检测**：24h 窗口内，同一 status_name 出现 ≥ 5 次「告警→复归」反复
    → 触发新规则 B5「频发抖动」，升级到严重
3. **检修时段过滤**：告警 timestamp 落在维护检修窗口内 → 不计入风险
4. **按台账归一**：筛选评估目标时，使用台账 station_name 作为权威
5. **间隔级综合**：输出按 primary_device（间隔/一次设备）粒度，
    综合 max(套级风险) + 双套独立运行加权

工作流程：
1. 加载 DataPackage
2. 评估目标 = 台账中 [station] 的全部 primary_device
3. 每台装置 → 规则驱动层 + 智能诊断层
4. 同一间隔多套保护 → 综合评估
5. 输出 Markdown + HTML 活页 + JSON 推理链
"""

from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
SKILL_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))

from load_local_data import (  # noqa: E402
    DataPackage,
    DeviceKey,
    IntervalKey,
    MaintenanceRecord,
    load_all,
    normalize_to_primary_device,
    extract_set_index,
    alarm_in_maintenance_window,
)

# ═══════════════════════════ 规则层基础数据 ═══════════════════════════


RULE_LEVEL_SCORE = {"危急": 90, "严重": 65, "一般": 35, "提示": 10}
LEVEL_RANK = {"提示": 0, "一般": 1, "严重": 2, "危急": 3}
LEVEL_EMOJI = {"危急": "🔴", "严重": "🟠", "一般": "🟡", "提示": "⚪"}

# **v4 数据源扩展为六维**：
#   inventory / alarms / real_time_status / press_board / real_time_values / maintenance
#
# 检修工作信息必须作为"评估前置条件"——影响规则命中判定与阈值调整：
#   1. 检修期内：A3(参数异常)/A2(装置报警)/B3(通讯) 等"检修预期型"规则降级
#   2. 检修后 24h 内：告警复发 → 危急（消缺不彻底）
#   3. 检修工作清单本身的可读性是评估置信度因子之一
DATA_SOURCES = [
    "inventory",
    "alarms",
    "real_time_status",
    "press_board",
    "real_time_values",
    "maintenance",  # v4 新增
]
DATA_SOURCE_LABEL = {
    "inventory": "台账",
    "alarms": "历史告警",
    "real_time_status": "运行状态",
    "press_board": "压板（硬/软/开入）",
    "real_time_values": "定值",
    "maintenance": "保护装置检修信息",  # v4 新增
}

# **检修期内自动降级规则**：这些规则通常是检修操作触发的预期现象
# 例如：参数异常（重启未恢复）、通讯异常（采样板卡更换中）、装置报警（消缺复位）
DOWNGRADE_DURING_MAINTENANCE = {"A3", "A2", "B3", "E3"}
DOWNGRADE_LEVEL_MAP = {
    "危急": "严重",
    "严重": "一般",
    "一般": "提示",
    "提示": "提示",
}
# 这些规则即使在检修期也不降级（属于硬件/通道真实问题）
KEEP_RULES_DESPIRE_MAINTENANCE = {"A1", "B1", "B2", "B5", "C1", "D1"}

POST_MAINTENANCE_RELAPSE_HOURS = 24


# 关键字 → 规则 ID 映射
# **重要**：更具特异性的关键词放在前面，避免被通用词"异常"覆盖。
ALARM_KEYWORD_MAP = [
    (("CPU", "板卡", "RAM", "ROM", "FLASH", "电源故障"), "A1", "危急"),
    (("闭锁主保护",), "B2", "危急"),
    (("纵联保护闭锁",), "B2", "严重"),
    (("通道一通道故障", "通道二通道故障", "通道故障"), "B1", "严重"),
    (("通道一无有效帧", "通道二无有效帧"), "B1", "严重"),
    (("通道一通道异常", "通道二通道异常"), "B1", "一般"),
    (("通讯中断", "通讯状态异常"), "B3", "严重"),
    (("参数异常", "参数读取失败"), "A3", "严重"),
    (("装置报警",), "A2", "严重"),
    (("异常",), "A2", "一般"),
]  # type: list[tuple[tuple[str, ...], str, str]]


def normalize_alarm(status_name: str) -> tuple[str, str] | None:
    """status_name → (rule_id, default_level)"""
    best: tuple[int, str, str] | None = None
    for keywords, rule_id, level in ALARM_KEYWORD_MAP:
        for kw in keywords:
            if kw in status_name:
                if best is None or len(kw) > best[0]:
                    best = (len(kw), rule_id, level)
    if best is None:
        return None
    _, rule_id, level = best
    return (rule_id, level)


# ═══════════════════════════ 时间窗口 ═══════════════════════════


def query_window_start(now: datetime | None = None) -> datetime:
    """查询窗口起点 = 当日 00:00:00。

    用户口径："今天有哪些间隔存在危急风险"等无明确时间问题，
    默认窗口为 [今日 00:00:00, 提问时间]。
    窗口外的告警**不计入**风险判定——保护告警时间序列只看今天。
    """
    if now is None:
        now = datetime.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# ── 频发抖动阈值（用户确认：24h 内 ≥ 5 次） ──
FLAP_THRESHOLD = 5
FLAP_WINDOW_HOURS = 24

# 这些告警关键词即使在检修期内也不应自动过滤（硬件类真实问题）
MAINT_KEEP_KEYWORDS = (
    "CPU", "板卡", "RAM", "ROM", "FLASH", "电源故障",
    "闭锁主保护", "纵联保护闭锁",
    "通道一通道故障", "通道二通道故障", "通道故障",
    "通道一无有效帧", "通道二无有效帧",
)
# 这些告警关键词在检修期内**应当被过滤**（预期性/操作类）
MAINT_FILTER_KEYWORDS = (
    "参数异常", "参数读取失败", "通讯中断", "通讯状态异常",
    "装置报警", "异常",
    "通道一通道异常", "通道二通道异常",  # 通道操作型异常
)


# ═══════════════════════════ 告警状态机分析 ═══════════════════════════


@dataclass
class AlarmStateAnalysis:
    """单个 (device_key, status_name) 的告警状态机结果。"""

    status_name: str
    rule_id: str
    base_level: str  # 规则默认等级
    final_value: str  # "告警" 或 "复归"
    final_level: str  # 由状态机调整后的等级
    is_persistent: bool  # 今日窗口内最后一条仍是"告警"
    is_flapping: bool  # 24h 滑动窗口内反复 ≥ 5 次
    flap_count_24h: int  # 24h 滑动窗口内告警次数
    last_timestamp: str
    in_maintenance: bool  # 该 status 是否在检修窗口内
    in_today_window: bool  # 是否落在 [今日 00:00, now] 内
    reason: str  # 决策理由字符串


def analyze_alarm_state(
    status_name: str,
    alarms: list[dict],
    maintenance_records: list[MaintenanceRecord] | None = None,
    now: datetime | None = None,
) -> AlarmStateAnalysis | None:
    """对单个 status_name 的告警时间序列做状态机分析。

    **关键变更 (v3)**：
    1. **今日窗口**：[query_window_start(now), now] 之外的告警一律不计入。
       - 例: 用户中午 12:00 问 → 默认看 00:00-12:00 之间是否有未复归告警。
       - 今日窗口内"最后一条=复归" → 信号在窗口内已消除，**不计入风险**。
       - 今日窗口内"最后一条=告警" → 信号在窗口内仍活跃，**计入风险**。
    2. **频抖窗口**：仍按 24h 滑动窗口判频发抖动（用于趋势分析，与状态判定解耦）。
    3. **检修过滤**：窗口内告警若 timestamp 落在检修区间 → 不计入。
    """
    rule = normalize_alarm(status_name)
    if rule is None:
        return None
    rule_id, base_level = rule

    sub = [a for a in alarms if a.get("status_name") == status_name]
    if not sub:
        return None

    sub.sort(key=lambda a: a.get("timestamp", ""))

    if now is None:
        now = datetime.now()
    today_start = query_window_start(now)

    # 今日窗口内的记录
    sub_today = []
    for a in sub:
        ts_str = a.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if ts < today_start or ts > now:
            continue  # 不在今日窗口
        sub_today.append(a)

    maint_records = maintenance_records or []

    # 计算每条 in_maintenance 标记
    def in_maint(a: dict) -> bool:
        return alarm_in_maintenance_window(a.get("timestamp", ""), maint_records)

    # v4 修订：检修期内是否过滤，**取决于 status_name 类型**：
    # 硬件故障类（CPU/板卡/通道故障/无有效帧）即使在检修期内也报
    # 预期操作类（参数异常/通讯中断/装置报警）则在检修期内过滤
    def _is_maint_keep_signal(name: str) -> bool:
        return any(k in name for k in MAINT_KEEP_KEYWORDS)

    def _is_maint_filter_signal(name: str) -> bool:
        return any(k in name for k in MAINT_FILTER_KEYWORDS)

    # ── 关键判定：今日窗口内"最后一条"是否仍为告警 ──
    # v4: 在检修期内，"预期型"告警应被过滤；"硬件型"告警保留
    sub_today_visible = [
        a for a in sub_today
        if not (in_maint(a) and _is_maint_filter_signal(a.get("status_name", "")))
        or _is_maint_keep_signal(a.get("status_name", ""))
    ]
    sub_today_non_maint = [
        a for a in sub_today
        if not (in_maint(a) and _is_maint_filter_signal(a.get("status_name", "")))
    ]
    if not sub_today_visible:
        # 今日窗口内只有检修期"预期型"告警 → 按检修过滤不计风险
        return AlarmStateAnalysis(
            status_name=status_name,
            rule_id=rule_id,
            base_level=base_level,
            final_value="复归",
            final_level="提示",
            is_persistent=False,
            is_flapping=False,
            flap_count_24h=0,
            last_timestamp=sub_today[-1].get("timestamp", "") if sub_today else "",
            in_maintenance=True,
            in_today_window=bool(sub_today),
            reason="今日窗口内记录均为检修期'预期型'告警，按检修过滤不计风险",
        )

    # 在窗口内找"最后一条"——优先取硬件类
    sub_today_visible_sorted = sorted(sub_today_visible, key=lambda a: a.get("timestamp", ""))
    # 优先取最后一条，但若最后一条是预期型且在检修期内，跳过
    last_visible = None
    for a in reversed(sub_today_visible_sorted):
        if in_maint(a) and _is_maint_filter_signal(a.get("status_name", "")):
            continue  # 跳过检修期内的预期型
        last_visible = a
        break

    if last_visible is None:
        return AlarmStateAnalysis(
            status_name=status_name,
            rule_id=rule_id,
            base_level=base_level,
            final_value="复归",
            final_level="提示",
            is_persistent=False,
            is_flapping=False,
            flap_count_24h=0,
            last_timestamp="",
            in_maintenance=True,
            in_today_window=bool(sub_today),
            reason="今日窗口内记录均为检修期'预期型'告警，按检修过滤不计风险",
        )

    last_ts = last_visible.get("timestamp", "")
    last_value = last_visible.get("value", "复归")
    is_persistent = last_value == "告警"

    last_in_window = sub_today_non_maint[-1]
    last_ts = last_in_window.get("timestamp", "")
    last_value = last_in_window.get("value", "复归")
    is_persistent = last_value == "告警"

    # ── 频发抖动（24h 滑动窗口） ──
    flap_window_start = now - timedelta(hours=FLAP_WINDOW_HOURS)
    flap_count = 0
    for a in sub:
        ts_str = a.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if ts < flap_window_start:
            continue
        if in_maint(a):
            continue
        if a.get("value") == "告警":
            flap_count += 1
    is_flapping = flap_count >= FLAP_THRESHOLD

    # ── 决策矩阵 ──
    if is_persistent:
        final_level = base_level
        reason = (
            f"今日窗口内信号持续: 最后 ts={last_ts}, value=告警 "
            f"(窗口 [今日 00:00, {now.strftime('%H:%M')}])"
        )
    elif is_flapping:
        final_level = "严重"
        reason = (
            f"今日窗口内已复归但 24h 内 ≥ {FLAP_THRESHOLD} 次告警-复归反复 "
            f"(实际 {flap_count} 次)"
        )
    else:
        final_level = "提示"
        reason = (
            f"今日窗口内信号已消除: 最后 ts={last_ts}, value=复归 "
            f"(窗口 [今日 00:00, {now.strftime('%H:%M')}])"
        )

    return AlarmStateAnalysis(
        status_name=status_name,
        rule_id=rule_id,
        base_level=base_level,
        final_value=last_value,
        final_level=final_level,
        is_persistent=is_persistent,
        is_flapping=is_flapping,
        flap_count_24h=flap_count,
        last_timestamp=last_ts,
        in_maintenance=any(in_maint(a) for a in sub_today),
        in_today_window=True,
        reason=reason,
    )


# ═══════════════════════════ 规则驱动层 ═══════════════════════════


@dataclass
class RuleHit:
    """单条规则命中。"""

    rule_id: str
    level: str
    evidence: str
    detail: dict[str, Any] = field(default_factory=dict)


def rule_check(
    pkg: DataPackage,
    device_key: DeviceKey,
    now: datetime | None = None,
) -> list[RuleHit]:
    """规则驱动层：对单台装置执行所有规则检查。

    **v3 关键变化**：
    - 告警检测走"今日窗口"状态机（仅 00:00-now 内的未复归/抖动计入）
    - 新增 E1-E5 类（运行监视/压板/模拟量/开入量/定值漂移）
    - 检修窗口内数据自动过滤
    """
    hits: list[RuleHit] = []

    intv_key = IntervalKey(device_key.station, device_key.primary_device)
    maint_records = pkg.maintenance.get(intv_key, [])

    device_alarms = pkg.alarms.get(device_key, [])

    # ── A1-A3 / B1-B3：告警类规则（状态机分析） ──
    status_groups: dict[str, list[dict]] = defaultdict(list)
    for a in device_alarms:
        status_groups[a.get("status_name", "")].append(a)

    for status_name, group in status_groups.items():
        state = analyze_alarm_state(
            status_name, group, maint_records, now=now
        )
        if state is None:
            continue
        if state.final_level == "提示":
            continue
        # v4 修订：检修期内仅过滤"预期型"告警；"硬件型"告警即使在检修期也报
        # 硬件型 = CPU/板卡/FLASH/电源/通道故障/无有效帧 等；详见 MAINT_KEEP_KEYWORDS
        is_hardware_signal = any(k in status_name for k in MAINT_KEEP_KEYWORDS)
        if (
            state.in_maintenance
            and not state.is_flapping
            and not is_hardware_signal
        ):
            continue

        hits.append(
            RuleHit(
                rule_id=state.rule_id,
                level=state.final_level,
                evidence=state.reason,
                detail={
                    "status_name": status_name,
                    "is_persistent": state.is_persistent,
                    "is_flapping": state.is_flapping,
                    "flap_count_24h": state.flap_count_24h,
                    "last_timestamp": state.last_timestamp,
                    "in_maintenance": state.in_maintenance,
                    "in_today_window": state.in_today_window,
                    "is_hardware_signal": is_hardware_signal,
                },
            )
        )

    rt = pkg.real_time_status.get(device_key)
    pb = pkg.press_board.get(device_key)

    # ── A3：参数采集异常 ──
    if rt:
        if rt.get("check_status") == "参数异常":
            main = rt.get("main_protect", "")
            backup = rt.get("backup_protect", "")
            level = "危急" if (main == "未知" and backup == "未知") else "严重"
            hits.append(
                RuleHit(
                    rule_id="A3",
                    level=level,
                    evidence=f"装置自检异常; 主保护={main}; 后备={backup}",
                    detail={"status": rt, "data_source": "real_time_status"},
                )
            )

    # ── B3：通讯状态异常 ──
    if rt and rt.get("oss_status") not in ("运行中", None, ""):
        hits.append(
            RuleHit(
                rule_id="B3",
                level="严重",
                evidence=f"装置离线/通讯异常: oss_status={rt.get('oss_status')}",
                detail={"data_source": "real_time_status"},
            )
        )

    # ── E 类（v3 新增）：压板/模拟量/开入量/定值漂移五维运行监视 ──

    # E1: 硬压板与软压板同名项不一致
    if pb:
        hard_map = {p.get("name"): p.get("value") for p in pb.get("hard_press", [])}
        soft_map = {p.get("name"): p.get("value") for p in pb.get("soft_press", [])}
        inconsistent = [
            n for n in hard_map.keys() & soft_map.keys()
            if hard_map[n] != soft_map[n]
        ]
        if inconsistent:
            hits.append(
                RuleHit(
                    rule_id="E1",
                    level="严重",
                    evidence=f"硬/软压板不一致: {', '.join(inconsistent[:3])}",
                    detail={
                        "inconsistent": inconsistent,
                        "hard": {k: hard_map[k] for k in inconsistent},
                        "soft": {k: soft_map[k] for k in inconsistent},
                        "data_source": "press_board",
                    },
                )
            )

        # E2: 模拟量越界（保护电压/电流异常）
        analog = pb.get("analog", [])
        for a in analog:
            name = a.get("name", "")
            val = a.get("value")
            if val is None:
                continue
            # 保护电压正常应在 0-110V 之间；零序应在 0-50V；保护电流应在 0-2A
            if "保护电压" in name and (val < 0 or val > 110):
                hits.append(
                    RuleHit(
                        rule_id="E2",
                        level="一般",
                        evidence=f"模拟量{name} 越界 = {val}",
                        detail={"data_source": "press_board"},
                    )
                )
            if "保护零序电压" in name and val > 30:
                hits.append(
                    RuleHit(
                        rule_id="E2",
                        level="严重",
                        evidence=f"模拟量{name} 越界 = {val} (>30V 告警)",
                        detail={"data_source": "press_board"},
                    )
                )
            if "保护电流" in name and val > 1.5:  # 二次电流 > 1.5A 是异常
                hits.append(
                    RuleHit(
                        rule_id="E2",
                        level="严重",
                        evidence=f"模拟量{name} 过流 = {val}A",
                        detail={"data_source": "press_board"},
                    )
                )

        # E3: 关键开入量异常
        digital_map = {
            d.get("name"): d.get("value")
            for d in pb.get("digital", [])
        }
        if digital_map.get("运行") == 0:
            hits.append(
                RuleHit(
                    rule_id="E3",
                    level="严重",
                    evidence="开入量『运行』=0，装置未在运行状态",
                    detail={"data_source": "press_board"},
                )
            )
        if digital_map.get("保护检修状态硬压板") == 1:
            hits.append(
                RuleHit(
                    rule_id="E3",
                    level="提示",
                    evidence="开入量『保护检修状态硬压板』=1（检修状态）",
                    detail={"data_source": "press_board"},
                )
            )

    # E4: 定值漂移
    rtv = pkg.real_time_values.get(device_key, {})
    drift_items = []
    boundary_items = []
    for s in rtv.get("settings", []):
        name = s.get("name", "")
        cur = s.get("current_value")
        last = s.get("last_value")
        if cur is None:
            continue
        # 关键定值
        if any(k in name for k in ("差动动作", "阻抗", "灵敏角", "电抗", "容抗")):
            if last is not None and cur != last:
                drift_items.append((name, last, cur))
            # 触界
            mn = s.get("min_value")
            mx = s.get("max_value")
            if mx and cur >= 0.95 * mx:
                boundary_items.append((name, cur, mx))
    if drift_items:
        hits.append(
            RuleHit(
                rule_id="E4",
                level="严重",
                evidence=f"关键定值漂移: " + "; ".join(
                    f"{n} {l}→{c}" for n, l, c in drift_items[:3]
                ),
                detail={"drift": drift_items, "data_source": "real_time_values"},
            )
        )
    if boundary_items:
        hits.append(
            RuleHit(
                rule_id="E4",
                level="一般",
                evidence=f"关键定值触界 ≥ 95%: " + "; ".join(
                    f"{n}={c}/{mx}" for n, c, mx in boundary_items[:3]
                ),
                detail={"boundary": boundary_items, "data_source": "real_time_values"},
            )
        )

    # ── F 类（v4 新增）：检修信息综合判定 ──

    # F1：检修结束之后 24h 内告警复发 → 危急（FAA 消缺不彻底）
    for maint in maint_records:
        end_time = maint.end_time
        if not end_time:
            continue
        try:
            end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
            except ValueError:
                continue
        # 仅在检修结束时间已过去但 < 24h 内有效
        if end_dt > now:
            continue  # 尚未结束
        if (now - end_dt).total_seconds() > POST_MAINTENANCE_RELAPSE_HOURS * 3600:
            continue  # 已超过 24h 复发窗口
        # 检查检修结束后是否有新告警
        for a in pkg.alarms.get(device_key, []):
            ts_str = a.get("timestamp", "")
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if ts < end_dt or ts > now:
                continue
            if a.get("value") == "告警" and a.get("alarm_priority") in ("严重告警",):
                hits.append(
                    RuleHit(
                        rule_id="F1",
                        level="危急",
                        evidence=(
                            f"检修({maint.work_type})结束后 "
                            f"{int((now-end_dt).total_seconds()/3600)}h 内复发严重告警: "
                            f"{a.get('status_name')}"
                        ),
                        detail={
                            "maint_end": end_time,
                            "alarm": a,
                            "data_source": "maintenance+alarms",
                        },
                    )
                )
                break  # 仅记录第一条复发即可

    # F2：检修期内告警"实际状态校验"——检修工作类型与现场是否匹配
    for maint in maint_records:
        try:
            start_dt = datetime.strptime(maint.start_time, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(maint.end_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if not (start_dt <= now <= end_dt):
            continue
        # 处于检修期内 → 提示性提醒
        work_type = maint.work_type
        # 'work_type' 类别判定
        if work_type in ("消缺", "技改", "首检"):
            # 这些是"应该修复"的检修 → 即使结束后短暂异常仍要关注
            hits.append(
                RuleHit(
                    rule_id="F2",
                    level="提示",
                    evidence=(
                        f"该间隔正处于 {work_type} 窗口 [{maint.start_time} ~ "
                        f"{maint.end_time}]，告警/状态异常多为检修预期操作。"
                    ),
                    detail={
                        "maint": maint,
                        "data_source": "maintenance",
                        "in_window": True,
                    },
                )
            )

    # ── D3：检修压板=1 时重合闸仍投入（v4 整合位置）──
    if rt and pb:
        digital = pb.get("digital", [])
        if any(
            d.get("name") == "保护检修状态硬压板" and d.get("value") == 1
            for d in digital
        ):
            if rt.get("reclose_status", "") == "投入":
                hits.append(
                    RuleHit(
                        rule_id="D3",
                        level="严重",
                        evidence="检修压板=1 但重合闸仍投入",
                        detail={
                            "data_source": "real_time_status+press_board",
                            "reclose_status": rt.get("reclose_status"),
                        },
                    )
                )

    return hits


def apply_maintenance_downgrade(
    hits: list[RuleHit],
    intv_key: IntervalKey,
    pkg: DataPackage,
    now: datetime | None = None,
) -> list[RuleHit]:
    """在检修期内对'检修预期型'规则做降级处理。

    用户口径："如果有检修工作，那就要结合检修工作内容综合判断"
    ——A3(参数异常)/A2(装置报警)/B3(通讯异常) 等大多是检修操作预期
    （如更换采样板后参数重置、更换通讯模块瞬时中断）。这些规则
    在检修期内降级，避免假警报。
    """
    if now is None:
        now = datetime.now()
    maint_records = pkg.maintenance.get(intv_key, [])
    in_maint = any(
        _safe_parse_dt(m.start_time) <= now <= _safe_parse_dt(m.end_time)
        for m in maint_records
        if m.start_time and m.end_time
    )
    if not in_maint:
        return hits

    for h in hits:
        if h.rule_id in KEEP_RULES_DESPIRE_MAINTENANCE:
            continue
        if h.rule_id in DOWNGRADE_DURING_MAINTENANCE:
            new_level = DOWNGRADE_LEVEL_MAP.get(h.level, h.level)
            if new_level != h.level:
                h.detail = h.detail or {}
                h.detail["_downgraded_by"] = (
                    f"检修期内降级 ({h.level} → {new_level})"
                )
                h.level = new_level
    return hits


def _safe_parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None

    # ── B5：频发抖动跨信号聚合 ──
    flap_statuses = []
    for status_name, group in status_groups.items():
        state = analyze_alarm_state(status_name, group, maint_records, now=now)
        if state and state.is_flapping:
            flap_statuses.append(status_name)
    if len(flap_statuses) >= 2:
        hits.append(
            RuleHit(
                rule_id="B5",
                level="严重",
                evidence=(
                    f"频发抖动跨多个信号: {', '.join(flap_statuses[:3])}... "
                    f"(同 status 24h 内 ≥ {FLAP_THRESHOLD} 次告警-复归反复)"
                ),
                detail={"flapping_statuses": flap_statuses},
            )
        )

    # ── D1：定值区号异常（来自模拟量） ──
    if pb:
        for a in pb.get("analog", []):
            if a.get("name") == "定值区号" and a.get("value") not in (0.0, 1.0):
                hits.append(
                    RuleHit(
                        rule_id="D1",
                        level="危急",
                        evidence=f"定值区号异常 = {a.get('value')}",
                        detail={"data_source": "press_board"},
                    )
                )

    return hits


# ═══════════════════════════ 智能诊断层 ═══════════════════════════


def health_index(
    pkg: DataPackage,
    device_key: DeviceKey,
    now: datetime | None = None,
) -> tuple[int, list[str]]:
    """装置健康度 [0,100] + 扣分明细标签。

    v2：告警只计入「持续（未复归）」或「频发抖动」，复归非抖动不计入。
    """
    score = 100
    notes: list[str] = []

    rt = pkg.real_time_status.get(device_key, {})
    if rt:
        if rt.get("check_status") == "参数异常":
            score -= 30
            notes.append("H1: 参数采集异常 -30")
        if rt.get("oss_status") not in ("运行中", None, ""):
            score -= 20
            notes.append(f"H1: oss状态={rt.get('oss_status')} -20")

    intv_key = IntervalKey(device_key.station, device_key.primary_device)
    maint_records = pkg.maintenance.get(intv_key, [])

    alarms_active = []
    alarms_flapping = []
    for a in pkg.alarms.get(device_key, []):
        ts_str = a.get("timestamp", "")
        if alarm_in_maintenance_window(ts_str, maint_records):
            continue
        # 仅在「告警」且经过状态机确认活跃时才扣分
        if a.get("value") != "告警":
            continue
        prio = a.get("alarm_priority", "")
        # 频发抖动的告警单独聚合
        state = analyze_alarm_state(
            a.get("status_name", ""), [a], maint_records, now=now
        )
        if state and state.is_flapping:
            alarms_flapping.append(a)
        elif state and state.is_persistent:
            alarms_active.append(a)

    # 活跃告警扣分（每条 -8 严重 / -4 运行异常）
    severe_active = sum(
        1 for a in alarms_active if a.get("alarm_priority") == "严重告警"
    )
    op_active = sum(
        1 for a in alarms_active if a.get("alarm_priority") == "运行异常"
    )
    score -= min(60, severe_active * 8)
    score -= min(40, op_active * 4)
    if severe_active:
        notes.append(f"H2: 严重告警(活跃)x{severe_active}")
    if op_active:
        notes.append(f"H2: 运行异常(活跃)x{op_active}")

    # 频发抖动扣分（任一 status 抖动 ≥ 5 次）
    if alarms_flapping:
        # 取唯一 status 数
        unique_flap_statuses = {
            a.get("status_name") for a in alarms_flapping
        }
        score -= min(40, 10 * len(unique_flap_statuses))
        notes.append(f"H2: 频发抖动跨 {len(unique_flap_statuses)} 个信号")

    # 密度扣分
    total_active = len(alarms_active) + len(alarms_flapping)
    if total_active > 30:
        score -= 15
        notes.append(f"H2: 活跃告警密度>30 -15")

    pb = pkg.press_board.get(device_key)
    if pb:
        digital_names = {
            d.get("name"): d.get("value")
            for d in pb.get("digital", [])
        }
        if (
            digital_names.get("保护检修状态硬压板") == 1
            and rt.get("reclose_status") == "投入"
        ):
            score -= 25
            notes.append("H3: 检修压板=1且重合闸投入 -25")

    rtv = pkg.real_time_values.get(device_key, {})
    for s in rtv.get("settings", []):
        name = s.get("name", "")
        if any(k in name for k in ("差动动作", "阻抗", "灵敏角", "电抗")):
            cur = s.get("current_value")
            last = s.get("last_value")
            if cur is not None and last is not None and cur != last:
                score -= 5
                notes.append(f"H4: {name} 漂移 {last}→{cur} -5")

    score = max(0, min(100, score))
    return score, notes


# ═══════════════════════════ 风险融合层 FAHP ═══════════════════════════


# 准则层权重（**v3 加入 E 维 = 运行监视/压板/模拟量/开入量/定值**）
#
# 含义：
#   A — 二次设备异常   (装置本体故障/参数异常/通讯状态)
#   B — 通道异常       (纵联保护通道、光纤、闭锁信号)
#   C — 反措未执行     (家族性缺陷治理)
#   D — 定值/方式不符  (定值单匹配、运行方式匹配)
#   E — 运行监视       (压板/软压板/开入量/模拟量/定值漂移 五源融合)
#
# 用户口径："运行风险评估不能仅仅检索告警记录，还要结合运行状态、
#           压板、定值和开入量、模拟量" → E 维独立构成一个准则层
#
# 三角模糊数判断矩阵（专家共识基线）：
#   A vs B ≈ (1, 1.2, 1.5)
#   A vs C ≈ (2, 2.5, 3)
#   A vs D ≈ (2, 3, 4)
#   A vs E ≈ (1, 1.5, 2)
#   B vs C ≈ (2, 2.5, 3)
#   B vs D ≈ (2, 2.5, 3)
#   B vs E ≈ (0.7, 1, 1.5)
#   C vs D ≈ (1, 1.5, 2)
#   C vs E ≈ (0.5, 0.7, 1)
#   D vs E ≈ (0.5, 0.7, 1)
# 经 Chang 三角模糊数合成法计算得：

FAHP_WEIGHTS = {"A": 0.32, "B": 0.20, "C": 0.13, "D": 0.12, "E": 0.23}


def _score_for_rule(rule_id: str, level: str) -> float:
    cat = rule_id[0]
    return RULE_LEVEL_SCORE.get(level, 0) if cat in FAHP_WEIGHTS else 0


def fahp_combine(hits: list[RuleHit]) -> tuple[float, str, dict]:
    """综合得分 + 映射等级 + 分维度明细。"""
    dimension_max: dict[str, float] = {"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0}
    for h in hits:
        cat = h.rule_id[0]
        if cat in dimension_max:
            dimension_max[cat] = max(
                dimension_max[cat], _score_for_rule(h.rule_id, h.level)
            )

    weighted = sum(FAHP_WEIGHTS[k] * dimension_max[k] for k in FAHP_WEIGHTS)

    if weighted >= 80:
        level = "危急"
    elif weighted >= 55:
        level = "严重"
    elif weighted >= 30:
        level = "一般"
    else:
        level = "提示"

    return round(weighted, 2), level, {k: round(v, 2) for k, v in dimension_max.items()}


# ═══════════════════════════ 装置级评估 ═══════════════════════════


@dataclass
class DeviceAssessment:
    station: str
    primary_device: str
    set_index: int | None
    rule_hits: list[RuleHit]
    health: int
    health_notes: list[str]
    fahp_score: float
    fahp_breakdown: dict[str, float]
    raw_max_level: str
    final_level: str
    confidence: float
    recommendations: list[str]
    in_maintenance: bool = False
    # v3 新增：五源数据可用性（"ok" / "missing" / "n/a"）
    data_sources: dict[str, str] = field(default_factory=dict)
    # v3 新增：原始数据快照（按需展示给用户）
    rt_status_snapshot: dict = field(default_factory=dict)
    press_board_snapshot: dict = field(default_factory=dict)
    settings_snapshot: list = field(default_factory=list)
    today_window_start: str = ""  # ISO 字符串
    now_str: str = ""


# 规则 ID → 建议模板
ACTION_TEMPLATES: dict[str, list[str]] = {
    "A1": [
        "立即通知调度，按调度指令退出该保护或投运备用保护。",
        "启动紧急消缺流程，按厂家技术说明书更换指定版本板卡。",
        "排查本站同批次装置。",
    ],
    "A2": [
        "立即派员现场检查装置显示屏告警代码。",
        "调取最近一次检修记录，比对告警变化趋势。",
        "若今日窗口内未自行复归，列入本周消缺计划。",
    ],
    "A3": [
        "检查保护管理机/通讯网关链路是否正常。",
        "比对通讯中断时间窗口与现场检修/调试记录。",
        "通讯恢复后核对装置参数与定值区一致性。",
    ],
    "B1": [
        "立即检查光纤通道一/二收发光功率。",
        "检查保护室配线架、对侧光端机状态。",
        "联系通道运维班组现场测试。",
    ],
    "B2": [
        "立即核对闭锁信号来源（通道/对侧/自身）。",
        "复归信号并通知调度。",
        "闭锁持续 ≥1h 启动消缺流程。",
    ],
    "B3": [
        "检查保信子站/主站通讯状态。",
        "必要时切换至备用数据通道。",
        "通讯恢复前暂停对此装置的远程定值修改。",
    ],
    "B5": [
        "立即派员现场检查装置硬件（采样板/通道插件）。",
        "调取厂家分析软件日志，查明频发告警根因。",
        "列入紧急消缺计划，加强同型号同批次装置巡视。",
    ],
    "C1": [
        "按反措文件编号锁定批次。",
        "立即安排停电窗口更换指定部件。",
        "加强同型号装置巡视。",
    ],
    "D1": [
        "立即核对调度定值单（区号+定值明细）。",
        "按调度指令切换定值区。",
        "完成后通知调度校核。",
    ],
    "D3": [
        "核对运行方式通知单与当前定值单。",
        "按规定停用/启用相关保护功能。",
        "完成切换后在运行日志留底。",
    ],
    # ── E 类（v3 新增）──
    "E1": [
        "立即核查硬压板与软压板实际位置是否一致。",
        "调取最近操作票/工作票，确认是否有计划性压板切换。",
        "复核保护运行方式通知单要求。",
    ],
    "E2": [
        "立即派员现场检查采样回路（CT/PT 接线）。",
        "比对模拟量与故障录波数据，排查二次回路异常。",
        "必要时切换至旁路代路运行。",
    ],
    "E3": [
        "立即派员现场检查开入信号源（操作箱、保护管理机）。",
        "核查开入信号电缆绝缘与屏蔽接地。",
        "在运行日志中记录开入状态变更。",
    ],
    "E4": [
        "调取最近一次调度定值单进行比对。",
        "核对修改记录与工作票。",
        "若无合法变更记录，按调度指令回退定值。",
    ],
    "E5": [
        "检查保护管理机/通讯链路状态。",
        "结合保信主站告警综合判定。",
        "通讯恢复后补全状态采集。",
    ],
    # ── F 类（v4 新增：检修综合判定）──
    "F1": [
        "立即核查上次消缺是否彻底（板卡更换、参数重置、采样回路）。",
        "调取消缺工作票与质量验收记录。",
        "重新派员现场检查，必要时安排再次消缺。",
    ],
    "F2": [
        "核对检修工作票与现场实际操作一致性。",
        "检修期间观察告警变化，复役后 24h 内重点巡视。",
        "检修结束后做保护传动试验。",
    ],
}


def _max_level(levels: list[str]) -> str:
    if not levels:
        return "提示"
    return max(levels, key=lambda l: LEVEL_RANK.get(l, 0))


def _gen_recommendations(hits: list[RuleHit]) -> list[str]:
    recs: list[str] = []
    for h in hits:
        for r in ACTION_TEMPLATES.get(h.rule_id, []):
            if r not in recs:
                recs.append(r)
    if not recs:
        recs = ["纳入定期巡视，关注趋势。"]
    return recs[:3]


def assess_device(
    pkg: DataPackage,
    device_key: DeviceKey,
    now: datetime | None = None,
) -> DeviceAssessment:
    if now is None:
        now = datetime.now()
    intv_key = IntervalKey(device_key.station, device_key.primary_device)
    maint_records = pkg.maintenance.get(intv_key, [])

    hits = rule_check(pkg, device_key, now=now)

    # v4: 检修期内规则降级（A3/A2/B3/E3 等"检修预期型"规则降级，
    # 但保留 A1/B1/B2/B5/C1/D1 等硬件/通道真实问题）
    hits = apply_maintenance_downgrade(hits, intv_key, pkg, now=now)

    health, notes = health_index(pkg, device_key, now=now)
    score, level, breakdown = fahp_combine(hits)
    raw_max = _max_level([h.level for h in hits])

    final = _max_level([level, raw_max])
    if health < 20:
        final = _max_level([final, "危急"])
    elif health < 40:
        final = _max_level([final, "严重"])

    # ── v3: 数据源可用性（六维）──
    sources = {}
    sources["inventory"] = (
        "ok" if any(
            d.get("_set_index") == device_key.set_index or device_key.set_index is None
            for d in pkg.inventory.get(intv_key, [])
        ) else "missing"
    )
    sources["real_time_status"] = (
        "ok" if device_key in pkg.real_time_status else "missing"
    )
    sources["press_board"] = (
        "ok" if device_key in pkg.press_board else "missing"
    )
    sources["real_time_values"] = (
        "ok" if device_key in pkg.real_time_values else "missing"
    )
    sources["alarms"] = (
        "ok" if pkg.alarms.get(device_key) else "missing"
    )
    # v4 新增：保护装置检修信息数据源
    if maint_records:
        # 区分"当前正在检修"与"历史上检修"
        in_window = any(
            _safe_parse_dt(m.start_time) <= now <= _safe_parse_dt(m.end_time)
            for m in maint_records
            if m.start_time and m.end_time
        )
        sources["maintenance"] = "in_window" if in_window else "ok"
    else:
        sources["maintenance"] = "missing"
    data_completeness = sum(
        1 for v in sources.values() if v in ("ok", "in_window")
    ) / len(DATA_SOURCES)

    # 置信度
    rule_strength = max(
        (RULE_LEVEL_SCORE[h.level] for h in hits), default=0
    ) / 90.0
    # 仅计今日窗口内、未复归、未在检修的活跃告警
    alarm_density = 0
    for a in pkg.alarms.get(device_key, []):
        ts_str = a.get("timestamp", "")
        if alarm_in_maintenance_window(ts_str, maint_records):
            continue
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if ts < query_window_start(now) or ts > now:
            continue
        if a.get("value") == "告警":
            alarm_density += 1
    alarm_density = min(1.0, alarm_density / 20.0)

    confidence = round(data_completeness * rule_strength * alarm_density, 2)
    confidence = max(confidence, round(data_completeness * 0.4, 2))

    # ── v3: 原始数据快照（用于简报详细展示）──
    rt_snap = dict(pkg.real_time_status.get(device_key, {})) if device_key in pkg.real_time_status else {}
    pb_snap = dict(pkg.press_board.get(device_key, {})) if device_key in pkg.press_board else {}
    rtv_snap = pkg.real_time_values.get(device_key, {})
    settings_snap = list(rtv_snap.get("settings", []))

    return DeviceAssessment(
        station=device_key.station,
        primary_device=device_key.primary_device,
        set_index=device_key.set_index,
        rule_hits=hits,
        health=health,
        health_notes=notes,
        fahp_score=score,
        fahp_breakdown=breakdown,
        raw_max_level=raw_max,
        final_level=final,
        confidence=confidence,
        recommendations=_gen_recommendations(hits),
        in_maintenance=bool(maint_records),
        data_sources=sources,
        rt_status_snapshot=rt_snap,
        press_board_snapshot=pb_snap,
        settings_snapshot=settings_snap,
        today_window_start=query_window_start(now).strftime("%Y-%m-%d %H:%M:%S"),
        now_str=now.strftime("%Y-%m-%d %H:%M:%S"),
    )


# ═══════════════════════════ 间隔级综合评估（v2 新增） ═══════════════════════════


@dataclass
class IntervalAssessment:
    """间隔级（一次设备）综合评估。

    把同一 primary_device 下的多套保护综合判断：
        interval_final = max(各套.level)
        双套独立运行：第1套与第2套 level 都不为提示时，可能"两个独立通道都失效"
        三类加权：
            - 双套独立运行 + 任一套危急 → 整间隔危急
            - 双套独立运行 + 两套同时严重 → 整间隔严重（提示二者同源）
            - 单套独立运行（仅1套） → 整间隔取单套等级

    v4 新增字段：
        - under_maintenance: 该间隔是否**正处于**检修窗口
        - recent_maintenance: 最近一次检修（≤24h 前）
        - maintenance_context: 用于简报中"综合判定"展示
    """

    station: str
    primary_device: str
    sets: list[DeviceAssessment]
    max_level: str
    interval_final_level: str
    interval_fahp_score: float
    interval_reason: str
    in_maintenance: bool
    maintenance_records: list[MaintenanceRecord]
    # v4 新增
    under_maintenance: bool = False
    recent_post_maint: bool = False  # 检修结束后 24h 内
    maintenance_context: str = ""


def aggregate_interval(
    pkg: DataPackage,
    interval_key: IntervalKey,
    set_assessments: list[DeviceAssessment],
    now: datetime | None = None,
) -> IntervalAssessment:
    if now is None:
        now = datetime.now()
    maint_records = pkg.maintenance.get(interval_key, [])

    # v4: 检修上下文判定
    under_maint = False
    post_maint = False
    maint_context = ""

    for m in maint_records:
        start_dt = _safe_parse_dt(m.start_time)
        end_dt = _safe_parse_dt(m.end_time)
        if not (start_dt and end_dt):
            continue
        if start_dt <= now <= end_dt:
            under_maint = True
            maint_context = (
                f"检修中 ({m.work_type}) "
                f"[{m.start_time} ~ {m.end_time}]，告警多为检修预期操作。"
            )
        elif end_dt < now and (now - end_dt).total_seconds() <= POST_MAINTENANCE_RELAPSE_HOURS * 3600:
            post_maint = True
            hours_after = int((now - end_dt).total_seconds() / 3600)
            maint_context = (
                f"检修结束 {hours_after}h 内（{m.work_type} 检修 [{m.start_time} ~ "
                f"{m.end_time}]）；检修后告警复发 → 高风险信号。"
            )

    if not set_assessments:
        return IntervalAssessment(
            station=interval_key.station,
            primary_device=interval_key.primary_device,
            sets=[],
            max_level="提示",
            interval_final_level="提示",
            interval_fahp_score=0.0,
            interval_reason="无装置评估数据",
            in_maintenance=bool(maint_records),
            maintenance_records=maint_records,
            under_maintenance=under_maint,
            recent_post_maint=post_maint,
            maintenance_context=maint_context,
        )

    levels = [a.final_level for a in set_assessments]
    max_l = _max_level(levels)

    interval_max = max_l

    # 双套独立运行加权：
    sets_present = {a.set_index for a in set_assessments if a.set_index is not None}
    has_dual = {1, 2}.issubset(sets_present)
    if has_dual:
        set1 = next((a for a in set_assessments if a.set_index == 1), None)
        set2 = next((a for a in set_assessments if a.set_index == 2), None)
        if set1 and set2:
            # 任一套危急 → 整间隔危急
            if (
                set1.final_level == "危急"
                or set2.final_level == "危急"
            ):
                interval_max = "危急"
                interval_reason = (
                    f"双套独立运行: 第1套={set1.final_level}，"
                    f"第2套={set2.final_level} → 任一危急，整间隔危急"
                )
            elif (
                set1.final_level == "严重" and set2.final_level == "严重"
            ):
                interval_max = "严重"
                interval_reason = (
                    f"双套独立运行: 第1套=严重，第2套=严重 → 整间隔严重"
                )
            else:
                interval_reason = (
                    f"双套独立运行: 第1套={set1.final_level}，第2套={set2.final_level}"
                )
    else:
        interval_reason = f"单套装置或非独立双套: {levels}"

    # v4: 检修期内不把"提示类规则"叠加到危急判断
    if under_maint and interval_max == "危急":
        # 危急时仍报危急；其他降一级处理
        pass

    if maint_context:
        interval_reason += f"  ｜ {maint_context}"

    # 综合分：所有套的 max(FAHP 分) 取最大值
    interval_score = max(a.fahp_score for a in set_assessments)

    in_maint = bool(maint_records)

    return IntervalAssessment(
        station=interval_key.station,
        primary_device=interval_key.primary_device,
        sets=set_assessments,
        max_level=max_l,
        interval_final_level=interval_max,
        interval_fahp_score=interval_score,
        interval_reason=interval_reason,
        in_maintenance=in_maint,
        maintenance_records=maint_records,
        under_maintenance=under_maint,
        recent_post_maint=post_maint,
        maintenance_context=maint_context,
    )


# ═══════════════════════════ 评估目标筛选 ═══════════════════════════


def select_targets(
    pkg: DataPackage,
    station: str | None = None,
) -> list[IntervalKey]:
    """**按台账归一**筛选评估目标。

    关键：以台账 station_name 为权威。

    红石变台账只含：
        红古2C97/98、红桥2C95/96、油红4V24、红马2C51 等线路
        + Ⅰ母线、#1/2 主变、母联 4700 开关 等

    告警 JSON 中如有"红石变 station 下挂载崔挥2C55"——这是采集站错标,
    不进入评估范围（待人工/数据治理修正后，再合并评估）。
    """
    out: list[IntervalKey] = []
    for intv_key in pkg.inventory.keys():
        if station is None or intv_key.station == station:
            out.append(intv_key)
    return out


def collect_devices_for_interval(
    pkg: DataPackage, intv_key: IntervalKey
) -> list[DeviceKey]:
    """收集某间隔下的所有装置 device_key。

    收集原则：仅当 (station, primary_device) 在台账中存在时，
    才纳入该间隔的 device_key 集合——避免告警 JSON 中数据采集错标
    的"挂错站"装置污染评估。

    同时跨告警/压板/定值/状态四源把同一间隔下的所有 set 加入。
    """
    keys: set[DeviceKey] = set()

    # 台账中该间隔的 devices 决定 set 集合（权威白名单）
    inv_devices = pkg.inventory.get(intv_key, [])
    for dev in inv_devices:
        si = dev.get("_set_index")
        keys.add(DeviceKey(intv_key.station, intv_key.primary_device, si))

    # 跨其他来源补全（含母差、失灵、母联等非独立套）
    for dk in pkg.all_device_keys():
        if dk.station == intv_key.station and dk.primary_device == intv_key.primary_device:
            keys.add(dk)

    return sorted(keys, key=lambda k: (k.set_index or 99, str(k)))


# ═══════════════════════════ 简报生成 ═══════════════════════════


def render_briefing_md(
    intv: IntervalAssessment,
    meta: dict[str, Any],
) -> str:
    """按间隔级输出 Markdown 简报（严格对齐客户模板）。"""
    lvl = intv.interval_final_level
    icon = LEVEL_EMOJI[lvl]
    prefix = "【危急预警】" if lvl == "危急" else f"【{lvl}】"

    lines: list[str] = []
    lines.append(f"{prefix} 风险简报")
    lines.append(f"● 风险等级：{icon} {lvl}")

    # 影响范围：厂站 → 间隔/线路 → 保护装置（三级格式）
    if intv.sets:
        for s in intv.sets:
            set_label = f"第{s.set_index}套" if s.set_index else "非独立套"
            # 尝试从 rule_hits 中获取装置型号
            model = ""
            for h in s.rule_hits:
                if h.detail and h.detail.get("model"):
                    model = h.detail["model"]
                    break
            model_str = f" {model}" if model else ""
            lines.append(f"● 影响范围：{intv.station} → {intv.primary_device} → {set_label}{model_str}")
    else:
        lines.append(f"● 影响范围：{intv.station} → {intv.primary_device}")

    # v3: 时间窗口显式标注
    if intv.sets:
        any_set = intv.sets[0]
        lines.append(
            f"● 查询窗口：[{any_set.today_window_start} → {any_set.now_str}] "
            f"(默认今日 00:00 至当前时间)"
        )
    else:
        now = datetime.now()
        ws = query_window_start(now)
        lines.append(
            f"● 查询窗口：[{ws.strftime('%Y-%m-%d %H:%M:%S')} → {now.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"(默认今日 00:00 至当前时间)"
        )

    if intv.in_maintenance:
        m_window = "; ".join(
            f"{r.start_time}~{r.end_time} {r.work_type}"
            for r in intv.maintenance_records
        )
        lines.append(
            f"● ⚠️ 该间隔在维护检修窗口：{m_window}。"
        )

    # v4: 检修上下文（综合判定）
    if intv.under_maintenance:
        lines.append(f"● 检修状态：🔧 **正在检修中** — 综合判定按检修窗口约束执行（A3/A2/B3 等检修预期型规则已降级）")
    elif intv.recent_post_maint:
        lines.append(f"● 检修状态：⏰ **检修结束 {POST_MAINTENANCE_RELAPSE_HOURS}h 内** — 告警复发 → 高风险信号")
    if intv.maintenance_context:
        lines.append(f"  {intv.maintenance_context}")

    if intv.sets:
        lines.append(f"● 包含装置：")
        for s in intv.sets:
            set_label = f"第{s.set_index}套" if s.set_index else "非独立套"
            lines.append(
                f"   - {set_label}（FAHP {s.fahp_score:.1f}，健康度 {s.health}，"
                f"等级 {s.final_level}）"
            )

    # v4: 六维数据可用性
    if intv.sets:
        any_set = intv.sets[0]
        sources_label = "、".join(
            f"{DATA_SOURCE_LABEL[k]}{'✓' if any_set.data_sources.get(k) in ('ok', 'in_window') else '✗缺失'}"
            for k in DATA_SOURCES
        )
        lines.append(f"● 多源数据融合（六维）：{sources_label}")

    # 风险概述
    if intv.sets:
        all_hits = [h for s in intv.sets for h in s.rule_hits]
        rules_summary = "、".join(
            f"{h.rule_id}({h.level})" for h in all_hits[:5]
        )
        first_evidence = all_hits[0].evidence if all_hits else ""
        lines.append(f"● 风险概述：{first_evidence}（综合判断：{intv.interval_reason}）")
        if rules_summary:
            lines.append(f"          命中规则 {rules_summary}")
    else:
        lines.append("● 风险概述：间隔下无活跃装置告警，常规巡视即可。")

    # 核心建议
    recs: list[str] = []
    for s in intv.sets:
        for r in s.recommendations:
            if r not in recs:
                recs.append(r)
    if not recs:
        recs = ["纳入定期巡视，关注趋势。"]
    recs = recs[:3]
    lines.append("● 核心建议：")
    for i, r in enumerate(recs, 1):
        lines.append(f"  {i}. {r}")

    # 推理追溯
    confidences = [s.confidence for s in intv.sets if s.confidence]
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0
    lines.append(
        f"● 推理追溯：confidence: {avg_conf:.2f}  "
        f"综合FAHP: {intv.interval_fahp_score:.1f}  ({intv.interval_reason})"
    )

    # 详细追溯
    if intv.sets:
        lines.append("")
        lines.append("--- 推理追溯链（按套）---")
        lines.append("")
        for s in intv.sets:
            set_label = f"第{s.set_index}套" if s.set_index else "非独立套"
            lines.append(f"#### {set_label}  FAHP {s.fahp_score:.1f}  健康度 {s.health}")
            lines.append("")
            lines.append("**FAHP 五维度子分（v3 加 E 维）**：")
            lines.append("")
            lines.append("| 维度 | 含义 | 权重 | 子分 | 加权贡献 |")
            lines.append("| --- | --- | --- | --- | --- |")
            dims_label = {
                "A": "二次设备异常",
                "B": "通道异常",
                "C": "反措未执行",
                "D": "定值/方式不符",
                "E": "运行监视（压板/模拟/开入/定值）",
            }
            for k, v in s.fahp_breakdown.items():
                lines.append(
                    f"| {k} | {dims_label[k]} | {FAHP_WEIGHTS[k]:.2f} | {v} | {v*FAHP_WEIGHTS[k]:.2f} |"
                )
            lines.append("")
            # 数据源状态
            lines.append("**数据源可用性**：")
            for k in DATA_SOURCES:
                status = s.data_sources.get(k, "missing")
                mark = "✓" if status == "ok" else "✗"
                lines.append(f"- {mark} {DATA_SOURCE_LABEL[k]}")
            lines.append("")
            # 关键原始数据快照
            if s.rt_status_snapshot and not s.rt_status_snapshot.get("_category", "") == "breaker_protections":
                # 仅显示关键字段
                lines.append("**运行状态快照（关键字段）**：")
                keep_keys = ("main_protect", "backup_protect", "reclose_status", "trip_export",
                             "check_status", "oss_status", "alarm_time")
                snap = {
                    k: s.rt_status_snapshot.get(k)
                    for k in keep_keys
                    if k in s.rt_status_snapshot
                }
                for k, v in snap.items():
                    lines.append(f"  - {k}: `{v}`")
                lines.append("")

            if s.press_board_snapshot:
                # 显示关键压板 + 开入
                pb = s.press_board_snapshot
                lines.append("**压板与开入量（关键项）**：")
                # 找"运行"、"保护检修状态硬压板"等
                key_names = {"运行", "保护检修状态硬压板", "远方操作硬压板", "光纤通道一硬压板", "光纤通道二硬压板"}
                all_pb = list(pb.get("hard_press", [])) + list(pb.get("digital", []))
                for p in all_pb:
                    if p.get("name") in key_names:
                        lines.append(f"  - {p.get('name')}: `{p.get('value')}`")
                # 模拟量
                lines.append("  **模拟量**：")
                for a in pb.get("analog", []):
                    if a.get("name") in {"定值区号", "保护电流 A 相", "保护电压 A 相", "保护零序电压"}:
                        lines.append(f"    - {a.get('name')}: `{a.get('value')}`")
                lines.append("")

            if s.settings_snapshot:
                # 仅显示变更或触界定值
                drifts = [st for st in s.settings_snapshot
                          if st.get("current_value") != st.get("last_value")
                          and any(k in st.get("name", "") for k in ("差动", "阻抗", "灵敏角", "电抗", "容抗"))]
                if drifts:
                    lines.append("**定值漂移（关键项）**：")
                    for d in drifts:
                        lines.append(
                            f"  - {d.get('name')}: {d.get('last_value')} → {d.get('current_value')} "
                            f"(min={d.get('min_value')}, max={d.get('max_value')})"
                        )
                    lines.append("")

            if s.rule_hits:
                lines.append("**命中规则**：")
                for h in s.rule_hits:
                    src = h.detail.get("data_source", "alarms")
                    lines.append(f"- **{h.rule_id}** [{h.level}] (源={src}) {h.evidence}")
            lines.append("")

    return "\n".join(lines)


def render_html_briefing(
    intv: IntervalAssessment,
    meta: dict[str, Any],
) -> str:
    """按间隔级输出 HTML 活页（v3: 多源融合 + 时间窗口）。"""
    lvl = intv.interval_final_level
    icon = LEVEL_EMOJI[lvl]
    set_rows = []
    for s in intv.sets:
        rule_rows = "\n".join(
            f"<tr><td>{h.rule_id}</td><td>{h.level}</td><td>{h.detail.get('data_source', 'alarms')}</td><td>{h.evidence}</td></tr>"
            for h in s.rule_hits
        ) or "<tr><td colspan='4'>(无规则命中)</td></tr>"
        dim_rows = "\n".join(
            f"<tr><td>{k}</td><td>{v:.2f}</td><td>{FAHP_WEIGHTS[k]:.2f}</td><td>{(v*FAHP_WEIGHTS[k]):.2f}</td></tr>"
            for k, v in s.fahp_breakdown.items()
        )
        # 数据源
        src_rows = "\n".join(
            f"<li>{('✅' if s.data_sources.get(k) == 'ok' else '❌')} {DATA_SOURCE_LABEL[k]}</li>"
            for k in DATA_SOURCES
        )
        # 原始数据快照
        rt_keys = ("main_protect", "backup_protect", "reclose_status", "trip_export",
                   "check_status", "oss_status", "alarm_time")
        rt_html = ""
        if s.rt_status_snapshot:
            items = "\n".join(
                f"<li><b>{k}</b> = <code>{s.rt_status_snapshot.get(k)}</code></li>"
                for k in rt_keys if k in s.rt_status_snapshot
            )
            rt_html = f"<details><summary><b>运行状态快照</b></summary><ul>{items}</ul></details>"
        pb_html = ""
        if s.press_board_snapshot:
            pb = s.press_board_snapshot
            key_names = {"运行", "保护检修状态硬压板", "远方操作硬压板",
                         "光纤通道一硬压板", "光纤通道二硬压板"}
            all_pb = list(pb.get("hard_press", [])) + list(pb.get("digital", []))
            pb_items = "\n".join(
                f"<li><b>{p.get('name')}</b> = <code>{p.get('value')}</code></li>"
                for p in all_pb if p.get("name") in key_names
            )
            analog_items = "\n".join(
                f"<li><b>{a.get('name')}</b> = <code>{a.get('value')}</code></li>"
                for a in pb.get("analog", [])
                if a.get("name") in {"定值区号", "保护电流 A 相", "保护电压 A 相", "保护零序电压"}
            )
            pb_html = (
                f"<details><summary><b>压板与开入量</b></summary>"
                f"<ul>{pb_items}</ul><b>模拟量：</b><ul>{analog_items}</ul>"
                f"</details>"
            )
        rtv_html = ""
        if s.settings_snapshot:
            rtv_items = "\n".join(
                f"<li><b>{d.get('name')}</b>: {d.get('last_value')} → {d.get('current_value')} "
                f"(min={d.get('min_value')}, max={d.get('max_value')})</li>"
                for d in s.settings_snapshot
                if d.get("current_value") != d.get("last_value")
                and any(k in d.get("name", "") for k in ("差动", "阻抗", "灵敏角", "电抗", "容抗"))
            )
            if rtv_items:
                rtv_html = f"<details><summary><b>定值漂移</b></summary><ul>{rtv_items}</ul></details>"

        set_label = f"第{s.set_index}套" if s.set_index else "非独立套"
        set_rows.append(
            f"<details open><summary><b>{set_label}</b> · "
            f"FAHP {s.fahp_score:.1f} · 健康度 {s.health} · 等级 {s.final_level}</summary>"
            f"<h4>FAHP 五维度</h4>"
            f"<table><tr><th>维度</th><th>子分</th><th>权重</th><th>加权贡献</th></tr>{dim_rows}</table>"
            f"<h4>数据源可用性</h4><ul>{src_rows}</ul>"
            f"{rt_html}{pb_html}{rtv_html}"
            f"<h4>命中规则（含数据源）</h4>"
            f"<table><tr><th>规则</th><th>等级</th><th>源</th><th>证据</th></tr>{rule_rows}</table>"
            f"</details>"
        )

    recs_html = ""
    seen = set()
    for s in intv.sets:
        for r in s.recommendations:
            if r in seen:
                continue
            seen.add(r)
            recs_html += f"<li>{r}</li>"
    if not recs_html:
        recs_html = "<li>纳入定期巡视，关注趋势。</li>"

    maint_html = ""
    if intv.in_maintenance:
        items = "".join(
            f"<li>{r.work_type} [{r.start_time} ~ {r.end_time}] {r.description}</li>"
            for r in intv.maintenance_records
        )
        maint_html = (
            f"<p style='background:#fff3cd;padding:10px;border-left:3px solid #ffc107'>"
            f"<b>⚠️ 维护检修窗口：</b><ul>{items}</ul>"
            f"检修时段内的告警已过滤；关注复役后告警是否复发。</p>"
        )

    confidences = [s.confidence for s in intv.sets if s.confidence]
    avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0

    any_set = intv.sets[0] if intv.sets else None
    window = (
        f"[{any_set.today_window_start} → {any_set.now_str}]"
        if any_set
        else "(无)"
    )

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{intv.primary_device}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;max-width:900px;margin:2em auto;padding:0 1em;color:#222}}
.lvl{{font-size:1.4em;font-weight:bold}}
.lvl-危急{{color:#c0392b}}
.lvl-严重{{color:#e67e22}}
.lvl-一般{{color:#d4ac0d}}
.lvl-提示{{color:#7f8c8d}}
table{{border-collapse:collapse;width:100%;margin:1em 0}}
td,th{{border:1px solid #ddd;padding:8px;text-align:left}}
th{{background:#f5f5f5}}
details{{margin:.5em 0;border-left:3px solid #3498db;padding-left:1em}}
.maint-banner{{background:#fff3cd;padding:10px;border-left:3px solid #ffc107;margin:.5em 0}}
</style></head><body>
<h1>{icon} {lvl} · {intv.primary_device} 间隔风险简报</h1>
{maint_html}
<p class="lvl lvl-{lvl}">风险等级：{icon} {lvl}（{intv.interval_reason}）</p>
<p><b>间隔：</b>{intv.station} → {intv.primary_device}</p>
<p><b>查询窗口：</b> <code>{window}</code> （默认今日 00:00:00 至当前时间）</p>
<p><b>综合FAHP分：</b>{intv.interval_fahp_score:.1f} · <b>置信度均值：</b>{avg_conf:.2f}</p>

{f'<div class="maint-banner"><b>🔧 检修上下文：</b>{intv.maintenance_context}</div>' if intv.maintenance_context else ''}

<p><b>核心建议：</b></p>
<ol>{recs_html}</ol>

{''.join(set_rows)}

<details open><summary><b>六维数据源（v4 加 maintenance）</b></summary>
<table>
<tr><th>数据源</th><th>状态</th><th>说明</th></tr>
{''.join(
    f"<tr><td>{DATA_SOURCE_LABEL[k]}</td><td>{('✓' if (any_set.data_sources.get(k) if any_set else 'missing') in ('ok', 'in_window') else '✗') + ('（当前在检修）' if (any_set.data_sources.get(k) if any_set else '')=='in_window' else '')}</td><td>{any_set.data_sources.get(k, 'missing') if any_set else 'n/a'}</td></tr>"
    for k in DATA_SOURCES
)}
</table>
</details>

<details><summary><b>数据源与查询时间</b></summary>
<p>数据时间: {meta.get('query_time','?')}</p>
<p>准则层权重（v4 五维）：A={FAHP_WEIGHTS['A']:.2f} B={FAHP_WEIGHTS['B']:.2f} C={FAHP_WEIGHTS['C']:.2f} D={FAHP_WEIGHTS['D']:.2f} E={FAHP_WEIGHTS['E']:.2f}</p>
</details>

</body></html>
"""


# ═══════════════════════════ 主流程 ═══════════════════════════


def run_assessment(
    pkg: DataPackage,
    station: str | None = None,
) -> list[IntervalAssessment]:
    """完整流程：按台账归一筛目标 → 装置级评估 → 间隔级综合。"""
    targets = select_targets(pkg, station=station)
    now = datetime.now()

    results: list[IntervalAssessment] = []
    for intv_key in targets:
        # 同间隔下所有装置（含第1套、第2套、母差、失灵等）
        device_keys = collect_devices_for_interval(pkg, intv_key)
        # 装置级评估
        set_assessments = [
            assess_device(pkg, dk, now=now) for dk in device_keys
        ]
        # 间隔级综合
        intv = aggregate_interval(pkg, intv_key, set_assessments, now=now)
        results.append(intv)

    # 按风险等级倒序，危急优先
    results.sort(
        key=lambda x: (-LEVEL_RANK[x.interval_final_level], x.primary_device)
    )
    return results


# ═══════════════════════════ CLI 入口 ═══════════════════════════


def main():
    parser = argparse.ArgumentParser(description="继电保护运行风险评估 v2")
    parser.add_argument("--scope", choices=["all", "station"], default="all")
    parser.add_argument("--station", type=str)
    parser.add_argument(
        "--data-dir",
        default=str(SKILL_DIR.parent.parent.parent / "保护装置信息"),
    )
    parser.add_argument(
        "--maintenance-file",
        type=str,
        default=None,
        help="检修工作 JSON 路径（缺省时不启用检修过滤）",
    )
    parser.add_argument("--out", default="out")
    parser.add_argument("--briefing-only", action="store_true")
    args = parser.parse_args()

    pkg = load_all(args.data_dir, maintenance_file=args.maintenance_file)
    print(
        f"数据加载完成：{len(pkg.inventory)} 间隔，"
        f"{sum(len(v) for v in pkg.alarms.values())} 条告警，"
        f"{sum(len(v) for v in pkg.maintenance.values())} 条检修"
    )

    now = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    results = run_assessment(pkg, station=args.station)
    print(f"评估完成：{len(results)} 间隔")

    # Markdown 主简报（严格对齐客户模板格式）
    if not args.briefing_only:
        with (out_dir / "briefing.md").open("w", encoding="utf-8") as f:
            # 统计异常装置数
            abnormal_count = sum(1 for r in results if r.interval_final_level != "提示")
            f.write(f"═══════════════════════════════════════════════\n")
            f.write(f"  {args.station or '全网'} / {now.strftime('%Y-%m-%d %H:%M')} 风险简报（共 {abnormal_count} 套异常装置）\n")
            f.write(f"═══════════════════════════════════════════════\n\n")

            by_level = defaultdict(list)
            for r in results:
                by_level[r.interval_final_level].append(r)
            for lvl in ("危急", "严重", "一般", "提示"):
                group = by_level.get(lvl, [])
                if not group:
                    continue
                icon = LEVEL_EMOJI[lvl]
                f.write(f"【{lvl}预警】（{len(group)} 套）\n\n")
                for r in group:
                    f.write(render_briefing_md(r, pkg.meta))
                    f.write("\n\n")

            f.write(f"═══════════════════════════════════════════════\n")
            f.write(f"  数据完整度：{len(results)} 间隔\n")
            f.write(f"═══════════════════════════════════════════════\n")
        print(f"→ Markdown: {out_dir / 'briefing.md'}")

    # HTML 活页 + JSON 推理链
    for r in results:
        safe = r.primary_device.replace("/", "_").replace("\\", "_")
        (out_dir / f"{safe}.html").write_text(
            render_html_briefing(r, pkg.meta), encoding="utf-8"
        )
        chain = {
            "station": r.station,
            "primary_device": r.primary_device,
            "interval_level": r.interval_final_level,
            "interval_score": r.interval_fahp_score,
            "reason": r.interval_reason,
            "in_maintenance": r.in_maintenance,
            "sets": [
                {
                    "set_index": s.set_index,
                    "final_level": s.final_level,
                    "fahp_score": s.fahp_score,
                    "health": s.health,
                    "confidence": s.confidence,
                    "rule_hits": [
                        {"rule_id": h.rule_id, "level": h.level, "evidence": h.evidence}
                        for h in s.rule_hits
                    ],
                }
                for s in r.sets
            ],
        }
        (out_dir / f"{safe}.json").write_text(
            json.dumps(chain, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 控制台汇总
    counts = Counter()
    for r in results:
        counts[r.interval_final_level] += 1
    print("\n══════ 评估汇总 ══════")
    for lvl in ("危急", "严重", "一般", "提示"):
        if counts[lvl]:
            print(f"  {LEVEL_EMOJI[lvl]} {lvl}: {counts[lvl]} 间隔")
    print(f"  ─────────────")
    print(f"  总计: {len(results)} 间隔")
    print(f"  输出: {out_dir}")
    if counts["危急"]:
        print("\n  ⚠️  存在危急风险！请优先处理。")


if __name__ == "__main__":
    main()
