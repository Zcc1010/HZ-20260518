"""Important warn query tool — query alarm events and chart statistics via external API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

BASE_URL = "http://10.34.38.113:8020"
PAGE_LIST_API = f"{BASE_URL}/baoxin/alarm/getPageList"
ALARM_REPORT_API = f"{BASE_URL}/baoxin/alarm/alarmReport"
PAGE_SIZE = 50
AUTO_PAGE_THRESHOLD = 200

# 告警等级
ALARM_PRIORITY_MAP = {
    "全部": "", "": "",
    "运行异常": "19", "19": "19",
    "严重告警": "17", "17": "17",
}

# 通信状态
IED_STATUS_MAP = {"正常": "1", "断开": "0", "1": "1", "0": "0"}

# 设备状态
OSS_STATUS_LIST = ["检修中", "运行中", "待投运", "已退运", "无状态"]

# 告警/复归
VALUE_MAP = {"告警": "告警", "复归": "复归"}


def _norm_alarm_priority(val: str | None) -> str:
    if not val or not val.strip():
        return "17"  # 默认严重告警
    return ALARM_PRIORITY_MAP.get(val.strip(), val.strip())


def _norm_ied_status(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    return IED_STATUS_MAP.get(val.strip(), "")


def _norm_oss_status(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    v = val.strip()
    return v if v in OSS_STATUS_LIST else ""


def _norm_value(val: str | None) -> str:
    if not val or not val.strip():
        return ""
    return VALUE_MAP.get(val.strip(), "")


def _default_date_range() -> tuple[str, str]:
    """返回最近30天的时间范围。"""
    now = datetime.now()
    start = now - timedelta(days=30)
    return start.strftime("%Y-%m-%d 00:00:01"), now.strftime("%Y-%m-%d 23:59:59")


TOOL_DESC = """查询重要告警事件数据和图表统计数据。数据来自保信系统的告警事件页面。

查询模式（mode）：
- list（默认）：查询告警事件列表，返回分页记录
- chart：查询图表统计数据，返回近一周/近一月/总计的装置告警排名

筛选参数说明（均为可选）：
- alarmPriority: 告警等级，默认"严重告警"，可选：全部、运行异常、严重告警
- startTime / endTime: 时间范围，格式"YYYY-MM-DD HH:MM:SS"，默认最近30天
- stName: 厂站名称，如"安庆"、"古泉"
- iedName: 装置名称
- statusName: 描述/告警名称
- value: 告警或复归，可选：告警、复归
- iedStatus: 通信状态，可选：正常、断开
- ossStatus: 设备状态，可选：运行中、检修中、待投运、已退运
- onceVoltageTypeList: 一次设备电压等级，多个用逗号分隔，如"500kV,220kV"
- unitName: 所属公司/运维单位

示例用法：
- 查安庆的严重告警：mode=list, stName=安庆
- 查运行异常的告警统计：mode=chart, alarmPriority=运行异常
- 查500kV设备的告警：mode=list, onceVoltageTypeList=500kV
- 查装置"安庆变1号主变保护"的告警：mode=list, iedName=安庆变1号主变保护
"""


@tool_parameters(
    tool_parameters_schema(
        mode=StringSchema("查询模式：list（告警列表，默认）或 chart（图表统计）"),
        alarmPriority=StringSchema("告警等级：全部、运行异常、严重告警（默认严重告警）"),
        startTime=StringSchema("开始时间，格式YYYY-MM-DD HH:MM:SS，默认最近30天"),
        endTime=StringSchema("结束时间，格式YYYY-MM-DD HH:MM:SS"),
        stName=StringSchema("厂站名称，支持模糊匹配，如：安庆、古泉"),
        iedName=StringSchema("装置名称"),
        statusName=StringSchema("描述/告警名称"),
        value=StringSchema("告警或复归：告警、复归"),
        iedStatus=StringSchema("通信状态：正常、断开"),
        ossStatus=StringSchema("设备状态：运行中、检修中、待投运、已退运"),
        onceVoltageTypeList=StringSchema("一次设备电压等级，多个用逗号分隔，如：500kV,220kV"),
        unitName=StringSchema("所属公司/运维单位"),
    )
)
class ImportantWarnQueryTool(Tool):
    """查询重要告警事件数据和图表统计数据。按条件筛选告警事件，支持列表查询和图表统计。"""

    @property
    def name(self) -> str:
        return "important_warn_query"

    @property
    def description(self) -> str:
        return TOOL_DESC

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        mode = (kwargs.get("mode") or "list").strip().lower()
        if mode not in ("list", "chart"):
            return f"查询模式'{mode}'不正确，可选：list（列表）、chart（图表统计）"

        # 构建公共参数
        params = self._build_params(kwargs)

        if mode == "chart":
            return await self._query_chart(params)
        return await self._query_list(params)

    def _build_params(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}

        # 告警等级
        params["alarmPriority"] = _norm_alarm_priority(kwargs.get("alarmPriority"))

        # 时间范围
        start_time = (kwargs.get("startTime") or "").strip()
        end_time = (kwargs.get("endTime") or "").strip()
        if not start_time and not end_time:
            start_time, end_time = _default_date_range()
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        # 通用筛选
        st_name = (kwargs.get("stName") or "").strip()
        ied_name = (kwargs.get("iedName") or "").strip()
        status_name = (kwargs.get("statusName") or "").strip()
        unit_name = (kwargs.get("unitName") or "").strip()
        if st_name:
            params["stName"] = st_name
        if ied_name:
            params["iedName"] = ied_name
        if status_name:
            params["statusName"] = status_name
        if unit_name:
            params["unitName"] = unit_name

        # 告警/复归
        val = _norm_value(kwargs.get("value"))
        if val:
            params["value"] = val

        # 通信状态
        ied_status = _norm_ied_status(kwargs.get("iedStatus"))
        if ied_status:
            params["iedStatus"] = ied_status

        # 设备状态
        oss_status = _norm_oss_status(kwargs.get("ossStatus"))
        if oss_status:
            params["ossStatus"] = oss_status

        # 电压等级（多选）
        voltage_raw = (kwargs.get("onceVoltageTypeList") or "").strip()
        if voltage_raw:
            parts = [p.strip() for p in voltage_raw.replace("、", ",").replace("，", ",").split(",") if p.strip()]
            if parts:
                params["onceVoltageTypeList"] = parts

        return params

    async def _query_list(self, base_params: dict[str, Any]) -> str:
        all_records: list[dict] = []
        page_num = 1
        total: int | None = None

        params = {**base_params, "limit": PAGE_SIZE, "page": 1}

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params["page"] = page_num
                try:
                    resp = await client.post(PAGE_LIST_API, json=params)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.error("ImportantWarn list API error on page {}: {}", page_num, exc)
                    if page_num == 1:
                        return f"告警事件查询接口请求失败：{exc}"
                    break

                body = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(body, dict):
                    records = body.get("list") or body.get("records") or []
                    if total is None:
                        total = body.get("total") or 0
                elif isinstance(body, list):
                    records = body
                    if total is None:
                        total = len(body)
                else:
                    return f"告警事件查询返回了未知格式：{str(data)[:500]}"

                all_records.extend(records)

                if not records:
                    break
                if total is not None and len(all_records) >= total:
                    break
                if len(all_records) >= AUTO_PAGE_THRESHOLD:
                    break
                page_num += 1

        count = len(all_records)
        if count == 0:
            return "未找到匹配的告警记录。请检查查询条件后重试。"

        # 格式化输出
        priority_name = {"17": "严重告警", "19": "运行异常"}.get(
            base_params.get("alarmPriority", ""), "全部"
        )
        header = f"共 {count} 条告警记录"
        if total and total > count:
            header += f"（共{total}条，已返回前{count}条）"
        header += f" | {priority_name}\n"

        columns = ["序号", "stName", "iedName", "timestamp", "receiveTime",
                    "unitName", "alarmPriorityDesc", "statusName", "value"]

        lines = [header]
        lines.append(" | ".join(columns))
        lines.append("-" * 100)

        for i, rec in enumerate(all_records, 1):
            row_parts = [str(i)]
            for col in columns[1:]:  # skip 序号
                val = rec.get(col, "")
                if val is None:
                    val = ""
                row_parts.append(str(val))
            lines.append(" | ".join(row_parts))

        return "\n".join(lines)

    async def _query_chart(self, base_params: dict[str, Any]) -> str:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(ALARM_REPORT_API, json=base_params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("ImportantWarn chart API error: {}", exc)
            return f"告警统计图表接口请求失败：{exc}"

        body = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(body, dict):
            return f"告警统计返回了未知格式：{str(data)[:500]}"

        count7 = body.get("count7") or {}
        count30 = body.get("count30") or {}
        count_all = body.get("count") or {}
        start_time7 = body.get("startTime7", "")
        start_time = body.get("startTime", "")
        end_time = body.get("endTime", "")

        priority_name = {"17": "严重告警", "19": "运行异常"}.get(
            base_params.get("alarmPriority", ""), "全部"
        )

        lines = [f"告警统计 | {priority_name}"]
        if start_time and end_time:
            lines.append(f"统计周期：{start_time} ~ {end_time}")
        lines.append("")

        # 周统计
        lines.append("=== 近一周告警统计 ===")
        if count7:
            sorted_items = sorted(count7.items(), key=lambda x: x[1], reverse=True)
            for name, cnt in sorted_items:
                lines.append(f"  {name}: {cnt} 次")
        else:
            lines.append("  无数据")

        # 月统计
        lines.append("")
        lines.append("=== 近一月告警统计 ===")
        if count30:
            sorted_items = sorted(count30.items(), key=lambda x: x[1], reverse=True)
            for name, cnt in sorted_items:
                lines.append(f"  {name}: {cnt} 次")
        else:
            lines.append("  无数据")

        # 总计
        lines.append("")
        lines.append("=== 全部告警统计 ===")
        if count_all:
            sorted_items = sorted(count_all.items(), key=lambda x: x[1], reverse=True)
            for name, cnt in sorted_items:
                lines.append(f"  {name}: {cnt} 次")
        else:
            lines.append("  无数据")

        return "\n".join(lines)
