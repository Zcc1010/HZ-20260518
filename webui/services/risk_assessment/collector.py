"""risk_assessment collector — 六源数据采集编排器。

自动串联 ledger_query + status_query 的全部 HTTP 调用，
一次性采集台账、运行状态、定值、压板/模拟量、告警、检修六源数据，
返回与离线脚本 DataPackage 结构一致的结果。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger

# ── API 基础地址（与 ledger_query / status_query 工具保持一致）──
LEDGER_BASE = "http://10.34.38.113:8020"
OUT_API_BASE = "http://10.34.38.113:8050"
LEDGER_API = f"{LEDGER_BASE}/ledger/equipment/secondary"
STATUS_API = f"{LEDGER_BASE}/baoXin/mulStatusNew/getPageList"
PAGE_SIZE = 50
DETAIL_TIMEOUT = 30.0
COLLECT_TIMEOUT = 300.0


# ── 归一化工具函数（从 load_local_data.py 移植）──
import re as _re

_VOLTAGE_RE = _re.compile(r"^\s*\d+\s*[kK]?[vV]\s*")
_MODEL_TAIL_RE = _re.compile(r"(保护|装置|微机.+?保护)\s*$")
_TAIL_PUNCT_RE = _re.compile(
    r"(?:第\s*)?[一二三四五\d]+\s*套"
    r"(?:[一-龥]+)?"
    r"(?:保护|装置)"
    r"(?:\s*[A-Z]+)?"
    r"[-\dA-Za-z]*"
    r"$"
)


def normalize_to_primary_device(name: str) -> str:
    """从 device_name 提取间隔级 primary_device。"""
    s = name.strip()
    s = _VOLTAGE_RE.sub("", s)
    s = _TAIL_PUNCT_RE.sub("", s)
    s = _re.sub(r"[A-Z]+-?\d+[A-Z\d-]*$", "", s)
    s = _MODEL_TAIL_RE.sub("", s)
    s = _re.sub(r"\s+", "", s)
    if not s.endswith("线") and not s.endswith("变") and not s.endswith("母线") and not s.endswith("开关"):
        if "线" in s and s.rfind("线") > len(s) - 3:
            s = s[: s.rfind("线") + 1]
    return s


def extract_set_index(name: str) -> int | None:
    """提取第 N 套。"""
    m = _re.search(r"第\s*(\d+)\s*套", name)
    if m:
        return int(m.group(1))
    cn_map = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}
    m = _re.search(r"第\s*([一二三四五])\s*套", name)
    if m:
        return cn_map.get(m.group(1))
    return None


# ── 数据模型 ──


@dataclass
class CollectResult:
    """六源数据采集结果。"""
    station: str = ""
    query_time: str = ""
    # 六源数据
    inventory: list[dict] = field(default_factory=list)          # 台账设备列表
    real_time_status: list[dict] = field(default_factory=list)   # 运行状态
    real_time_values: list[dict] = field(default_factory=list)   # 保信定值
    setting_comparison: list[dict] = field(default_factory=list) # 定值比对（来自基本信息 settingValueList）
    press_board: dict[str, list] = field(default_factory=lambda: {"hard_press": [], "soft_press": [], "analog": []})  # 压板/模拟量
    alarms: list[dict] = field(default_factory=list)             # 历史告警
    maintenance: list[dict] = field(default_factory=list)        # 检修记录
    # 元信息
    device_count: int = 0
    sources_collected: list[str] = field(default_factory=list)
    sources_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # 逐设备数据源可用性
    device_sources: dict[str, dict[str, bool]] = field(default_factory=dict)  # {uniqueCode: {source: True/False}}


# ── HTTP 辅助 ──


async def _post_json(client: httpx.AsyncClient, url: str, body: dict, timeout: float = DETAIL_TIMEOUT) -> Any:
    try:
        resp = await client.post(url, json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data
    except Exception as exc:
        logger.warning("POST {} failed: {}", url, exc)
        return None


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None, timeout: float = DETAIL_TIMEOUT) -> Any:
    try:
        resp = await client.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data
    except Exception as exc:
        logger.warning("GET {} failed: {}", url, exc)
        return None


# ── 六源采集 ──


async def _collect_inventory(
    client: httpx.AsyncClient, station: str
) -> tuple[list[dict], list[dict]]:
    """第1源：台账 — 获取厂站保护装置列表，返回 (all_records, devices_with_code)。"""
    all_records: list[dict] = []
    page = 1
    while True:
        data = await _post_json(
            client,
            f"{LEDGER_API}/getPageList",
            {"stName": station, "limit": PAGE_SIZE, "page": page, "includeOutSysDevice": "0"},
        )
        if data is None:
            break
        records = data.get("records") or data.get("list") or []
        if not records:
            break
        all_records.extend(records)
        if len(all_records) >= 500:
            break
        page += 1

    devices = []
    for rec in all_records:
        code = rec.get("uniqueCode", "")
        if code:
            devices.append({
                "uniqueCode": code,
                "onceDeviceId": rec.get("onceDeviceId", ""),
                "deviceName": rec.get("onceDeviceName", ""),
                "station": rec.get("stName", station),
                "stVoltageType": rec.get("stVoltageType", ""),
                "protectType": rec.get("protectType", ""),
                "protectModel": rec.get("protectModel", ""),
                "protectCover": rec.get("protectCover", ""),
                "manufacturer": rec.get("manufacturer", ""),
                "yearCategory": rec.get("yearCategory", ""),
            })
    return all_records, devices


async def _collect_status(
    client: httpx.AsyncClient, station: str, voltage_type: str, protect_type: str
) -> list[dict]:
    """第2源：运行状态 — 查询保护设备运行状态。"""
    all_records: list[dict] = []
    page = 1
    while True:
        body = {
            "voltageType": voltage_type,
            "protectType": protect_type,
            "stName": station,
            "limit": 100,
            "page": page,
        }
        data = await _post_json(client, STATUS_API, body)
        if data is None:
            break
        records = data.get("list") or data.get("records") or []
        if not records:
            break
        all_records.extend(records)
        if len(all_records) >= 500:
            break
        page += 1
    return all_records


async def _get_basic_info(
    client: httpx.AsyncClient, unique_code: str
) -> tuple[str, str, dict]:
    """获取设备基本信息，返回 (baoXinId, tongFenId, full_response)。

    full_response 包含 settingValueList（定值比对数据）等完整信息。
    """
    data = await _get_json(
        client,
        f"{LEDGER_API}/getDzDetailByUniqueCode/{unique_code}",
    )
    if data is None:
        return "", "", {}
    detail_list = data.get("dingZhiDetail", []) if isinstance(data, dict) else []
    equipment = detail_list[0] if detail_list else (data if isinstance(data, dict) else {})
    bao_xin_id = str(equipment.get("baoXinId", "") or "")
    tong_fen_id = str(equipment.get("tongFenId", "") or "")
    return bao_xin_id, tong_fen_id, data


async def _collect_device_detail(
    client: httpx.AsyncClient,
    unique_code: str,
    once_device_id: str,
    bao_xin_id: str,
    basic_info: dict | None = None,
) -> dict[str, Any]:
    """采集单设备的 bx_setting + hard/soft/analog + history + protect_alarm + maintenance + setting_comparison。"""

    async def _qj_last(method_name: str, bao_id: str) -> Any:
        if not bao_id:
            return None
        return await _get_json(
            client,
            f"{OUT_API_BASE}/open.api/dispatch/defence/device/qj/last",
            {"methodName": method_name, "onceDeviceId": bao_id},
        )

    result: dict[str, Any] = {
        "uniqueCode": unique_code,
        "bx_setting": None,
        "hard_press": None,
        "soft_press": None,
        "analog": None,
        "history": None,
        "protect_alarm": None,
        "maintenance": None,
        "setting_comparison": None,
        "errors": [],
    }

    # 从基本信息中提取定值比对数据（settingValueList）
    if basic_info and isinstance(basic_info, dict):
        detail_list = basic_info.get("dingZhiDetail", [])
        equipment = detail_list[0] if detail_list else basic_info
        sv_list = basic_info.get("settingValueList") or equipment.get("settingValueList")
        if isinstance(sv_list, list) and sv_list:
            result["setting_comparison"] = sv_list

    # 并行查询 qj/last 系列（都需要 baoXinId）
    if bao_xin_id:
        tasks = []
        task_keys = ["bx_setting", "hard_press", "soft_press", "analog"]
        method_names = ["lastSetting", "lastEnableForhard", "lastEnable", "lastAnalog"]
        for key, mn in zip(task_keys, method_names):
            tasks.append(_qj_last(mn, bao_xin_id))

        bx_val, hard_val, soft_val, analog_val = await asyncio.gather(*tasks)
        result["bx_setting"] = bx_val
        result["hard_press"] = hard_val
        result["soft_press"] = soft_val
        result["analog"] = analog_val
    else:
        result["errors"].append("baoXinId为空，跳过保信定值/压板/模拟量查询")

    # history 告警（近7天窗口）
    if bao_xin_id:
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        history_body = {
            "id": bao_xin_id,
            "pageSize": 100,
            "pageIndex": 0,
            "sortField": "soeTime",
            "sortOrder": "desc",
            "starttime": f"{week_ago} 00:00:00",
            "endtime": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        history_data = await _post_json(
            client, f"{LEDGER_BASE}/baoxin/alarm/listAllTypeIedAlarm", history_body
        )
        result["history"] = history_data

    # protect_alarm
    if bao_xin_id:
        alarm_data = await _post_json(
            client, f"{LEDGER_BASE}/baoxin/alarm/lastAlarm",
            {"iedid": bao_xin_id, "value": 1},
        )
        result["protect_alarm"] = alarm_data

    # maintenance（使用 uniqueCode）
    maint_data = await _post_json(
        client, f"{LEDGER_BASE}/oss/jhjx/getJhjxListByUniqueCode",
        {"uniqueCode": unique_code, "isProtectDev": 2},
    )
    result["maintenance"] = maint_data

    return result


async def collect_all(
    station: str,
    voltage_types: list[str] | None = None,
    protect_types: list[str] | None = None,
    today_start: str | None = None,
    today_end: str | None = None,
) -> CollectResult:
    """编排采集六源数据。

    Parameters
    ----------
    station : str
        厂站名称。
    voltage_types : list[str] | None
        电压等级列表，默认 ["1000kV", "500kV", "220kV"]。
    protect_types : list[str] | None
        保护类型列表，默认 ["线路保护", "母线保护", "变压器保护", "断路器保护"]。

    Returns
    -------
    CollectResult
        包含六源数据的完整采集结果。
    """
    if voltage_types is None:
        voltage_types = ["1000kV", "500kV", "220kV"]
    if protect_types is None:
        protect_types = ["线路保护", "母线保护", "变压器保护", "断路器保护"]

    result = CollectResult(
        station=station,
        query_time=datetime.now(timezone.utc).isoformat(),
    )

    async with httpx.AsyncClient(timeout=httpx.Timeout(COLLECT_TIMEOUT)) as client:
        # ── 第 1 源：台账 ──
        try:
            all_records, devices = await _collect_inventory(client, station)
            result.inventory = devices
            result.device_count = len(devices)
            if devices:
                result.sources_collected.append("inventory")
            else:
                result.sources_missing.append("inventory")
                result.errors.append(f"台账查询无结果: 厂站 '{station}' 未找到设备")
                # 不再 early return，继续尝试其他源
        except Exception as exc:
            result.sources_missing.append("inventory")
            result.errors.append(f"台账采集失败: {exc}")

        # ── 第 2 源：运行状态 ──
        try:
            all_status: list[dict] = []
            for vt in voltage_types:
                for pt in protect_types:
                    status_records = await _collect_status(client, station, vt, pt)
                    all_status.extend(status_records)
            result.real_time_status = all_status
            if all_status:
                result.sources_collected.append("real_time_status")
            else:
                result.sources_missing.append("real_time_status")
                result.errors.append("运行状态查询无结果")
        except Exception as exc:
            result.sources_missing.append("real_time_status")
            result.errors.append(f"运行状态采集失败: {exc}")

        # ── 并发采集每台设备的详细信息 ──
        device_details: list[dict] = []

        if devices:
            # 先批量获取 baoXinId + 基本信息
            async def _get_device_with_baoxin(dev: dict) -> dict:
                code = dev.get("uniqueCode", "")
                if not code:
                    return {**dev, "baoXinId": "", "detail": None}
                bao_id, _, basic_info = await _get_basic_info(client, code)
                detail = await _collect_device_detail(
                    client, code, dev.get("onceDeviceId", ""), bao_id,
                    basic_info=basic_info,
                )
                return {**dev, "baoXinId": bao_id, "detail": detail}

            sem = asyncio.Semaphore(5)  # 限制并发数

            async def _collect_one(dev: dict) -> dict:
                async with sem:
                    return await _get_device_with_baoxin(dev)

            tasks = [_collect_one(d) for d in devices]
            device_details = await asyncio.gather(*tasks)

        # ── 拆解到六源 ──
        bx_settings: list[dict] = []
        setting_comparisons: list[dict] = []
        hard_presses: list[dict] = []
        soft_presses: list[dict] = []
        analogs: list[dict] = []
        all_alarms: list[dict] = []
        all_maints: list[dict] = []

        has_settings = False
        has_setting_cmp = False
        has_press = False
        has_alarms = False
        has_maint = False

        for dev in device_details:
            detail = dev.get("detail") or {}
            code = dev.get("uniqueCode", "")

            # 记录每台设备的数据源可用性
            dev_sources: dict[str, bool] = {}

            # 收集该设备的错误信息
            dev_errors = detail.get("errors", [])
            if dev_errors:
                for err in dev_errors:
                    result.errors.append(f"[{code}] {err}")

            # 定值比对（来自基本信息 settingValueList）
            sv_list = detail.get("setting_comparison")
            if sv_list:
                has_setting_cmp = True
                setting_comparisons.append({"uniqueCode": code, "data": sv_list})
                dev_sources["setting_comparison"] = True
            else:
                dev_sources["setting_comparison"] = False

            # 保信定值（来自 qj/last 接口）
            sx = detail.get("bx_setting")
            if sx:
                has_settings = True
                bx_settings.append({"uniqueCode": code, "data": sx})
                dev_sources["real_time_values"] = True
            else:
                dev_sources["real_time_values"] = False

            # 压板
            hp = detail.get("hard_press")
            sp = detail.get("soft_press")
            an = detail.get("analog")
            if hp or sp or an:
                has_press = True
                hard_presses.append({"uniqueCode": code, "data": hp})
                soft_presses.append({"uniqueCode": code, "data": sp})
                analogs.append({"uniqueCode": code, "data": an})
                dev_sources["press_board"] = True
            else:
                dev_sources["press_board"] = False

            # 告警
            hist = detail.get("history")
            alarm = detail.get("protect_alarm")
            if hist or alarm:
                has_alarms = True
                all_alarms.append({
                    "uniqueCode": code,
                    "history": hist,
                    "protect_alarm": alarm,
                })
                dev_sources["alarms"] = True
            else:
                dev_sources["alarms"] = False

            # 检修
            maint = detail.get("maintenance")
            if maint:
                has_maint = True
                all_maints.append({"uniqueCode": code, "data": maint})
                dev_sources["maintenance"] = True
            else:
                dev_sources["maintenance"] = False

            result.device_sources[code] = dev_sources

        result.real_time_values = bx_settings
        result.setting_comparison = setting_comparisons
        if has_settings:
            result.sources_collected.append("real_time_values")
        else:
            result.sources_missing.append("real_time_values")

        if has_setting_cmp:
            result.sources_collected.append("setting_comparison")
        else:
            result.sources_missing.append("setting_comparison")

        result.press_board = {
            "hard_press": hard_presses,
            "soft_press": soft_presses,
            "analog": analogs,
        }
        if has_press:
            result.sources_collected.append("press_board")
        else:
            result.sources_missing.append("press_board")

        result.alarms = all_alarms
        if has_alarms:
            result.sources_collected.append("alarms")
        else:
            result.sources_missing.append("alarms")

        result.maintenance = all_maints
        if has_maint:
            result.sources_collected.append("maintenance")
        else:
            result.sources_missing.append("maintenance")

    return result


def format_result_for_agent(result: CollectResult) -> str:
    """将 CollectResult 格式化为 Agent 可消费的文本。"""
    lines = [
        f"=== 六源数据采集结果：{result.station} ===",
        f"采集时间: {result.query_time}",
        f"设备数量: {result.device_count}",
        f"已采集数据源: {', '.join(result.sources_collected) if result.sources_collected else '无'}",
    ]

    if result.sources_missing:
        lines.append(f"缺失数据源: {', '.join(result.sources_missing)}")
    if result.errors:
        lines.append(f"采集错误: {len(result.errors)} 条")
        for err in result.errors[:10]:
            lines.append(f"  - {err}")
        if len(result.errors) > 10:
            lines.append(f"  ... 还有 {len(result.errors) - 10} 条")

    lines.append("")

    # ── 台账 ──
    if result.inventory:
        lines.append(f"## 1. 台账 (共 {len(result.inventory)} 台装置)")
        for i, dev in enumerate(result.inventory, 1):
            lines.append(
                f"  {i}. {dev.get('deviceName', '?')} | "
                f"类型: {dev.get('protectType', '?')} | "
                f"型号: {dev.get('protectModel', '?')} | "
                f"套别: 第{dev.get('protectCover', '?')}套 | "
                f"uniqueCode: {dev.get('uniqueCode', '?')}"
            )
    else:
        lines.append("## 1. 台账: 无数据")

    # ── 运行状态 ──
    if result.real_time_status:
        lines.append(f"\n## 2. 运行状态 (共 {len(result.real_time_status)} 条)")
        for rec in result.real_time_status[:20]:
            name = rec.get("iedName", "")
            st = rec.get("stName", "")
            check = rec.get("checkStatus", "")
            oss = rec.get("ossStatus", "")
            lines.append(f"  - {st} / {name} | 校核: {check} | 设备: {oss}")
        if len(result.real_time_status) > 20:
            lines.append(f"  ... 还有 {len(result.real_time_status) - 20} 条")
    else:
        lines.append("\n## 2. 运行状态: 无数据")

    # ── 定值比对（来自基本信息 settingValueList） ──
    if result.setting_comparison:
        lines.append(f"\n## 3. 定值比对 (共 {len(result.setting_comparison)} 台)")
        for item in result.setting_comparison[:10]:
            data = item.get("data") or []
            code = item.get("uniqueCode", "?")
            if isinstance(data, list):
                lines.append(f"  uniqueCode={code}: {len(data)} 项定值")
                for sv in data[:5]:
                    name = sv.get("name", "")
                    expected = sv.get("expectedValue", sv.get("standardValue", ""))
                    actual = sv.get("actualValue", sv.get("currentValue", ""))
                    status = sv.get("status", "")
                    lines.append(f"    - {name}: 标准值={expected}, 实际值={actual}, 状态={status}")
                if len(data) > 5:
                    lines.append(f"    ... 还有 {len(data) - 5} 项")
        if len(result.setting_comparison) > 10:
            lines.append(f"  ... 还有 {len(result.setting_comparison) - 10} 台装置")
    else:
        lines.append("\n## 3. 定值比对: 无数据")

    # ── 保信定值（来自 qj/last 接口） ──
    if result.real_time_values:
        lines.append(f"\n## 4. 保信定值 (共 {len(result.real_time_values)} 台)")
        for item in result.real_time_values[:10]:
            data = item.get("data") or {}
            if isinstance(data, list):
                lines.append(f"  uniqueCode={item['uniqueCode']}: {len(data)} 项定值")
                for sv in data[:5]:
                    lines.append(f"    - {sv.get('name', '?')}: 当前={sv.get('value', '?')}, 标准={sv.get('stdvalue', '?')}")
            elif isinstance(data, dict):
                lines.append(f"  uniqueCode={item['uniqueCode']}: {json.dumps(data, ensure_ascii=False)[:200]}")
    else:
        lines.append("\n## 4. 保信定值: 无数据")

    # ── 压板/模拟量 ──
    pb = result.press_board if isinstance(result.press_board, dict) else {}
    if pb.get("hard_press") or pb.get("soft_press") or pb.get("analog"):
        hpc = sum(1 for x in pb.get("hard_press", []) if x.get("data"))
        spc = sum(1 for x in pb.get("soft_press", []) if x.get("data"))
        anc = sum(1 for x in pb.get("analog", []) if x.get("data"))
        lines.append(f"\n## 5. 压板/模拟量 (硬压板: {hpc}台, 软压板: {spc}台, 模拟量: {anc}台)")
    else:
        lines.append("\n## 5. 压板/模拟量: 无数据")

    # ── 告警 ──
    if result.alarms:
        lines.append(f"\n## 6. 告警 (共 {len(result.alarms)} 台装置有告警数据)")
        for item in result.alarms[:10]:
            hist = item.get("history") or {}
            pal = item.get("protect_alarm") or {}
            hist_count = len(hist.get("list", hist)) if isinstance(hist, dict) else 0
            lines.append(f"  uniqueCode={item['uniqueCode']}: history={hist_count}条, protect_alarm={'有' if pal else '无'}")
    else:
        lines.append("\n## 6. 告警: 无数据")

    # ── 检修 ──
    if result.maintenance:
        lines.append(f"\n## 7. 检修记录 (共 {len(result.maintenance)} 台装置)")
        for item in result.maintenance[:10]:
            data = item.get("data") or {}
            if isinstance(data, dict):
                records = data.get("list", data.get("records", []))
                lines.append(f"  uniqueCode={item['uniqueCode']}: {len(records)} 条检修记录")
    else:
        lines.append("\n## 7. 检修记录: 无数据")

    # ── 逐设备数据源可用性 ──
    if result.device_sources:
        lines.append("\n## 逐设备数据源可用性")
        for code, sources in result.device_sources.items():
            missing = [k for k, v in sources.items() if not v]
            if missing:
                lines.append(f"  {code}: 缺失 {', '.join(missing)}")

    # ── 总结 ──
    collected = len(result.sources_collected)
    total = 7
    lines.append(f"\n[数据采集完成。已采集: {collected}/{total} 源。")
    if result.sources_missing:
        lines.append(f"缺失: {', '.join(result.sources_missing)}。")
        lines.append("注意：缺失数据源对应的评估规则将无法检测，评估结果可能不完整。]")
    else:
        lines.append("六源齐全，可以进入风险评估阶段。]")

    return "\n".join(lines)
