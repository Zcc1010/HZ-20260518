"""risk_assessment_collect tool — 六源数据采集编排工具。

Agent 只需调用此工具一次，即可获取完整的六源数据包，
无需手动逐一调用 ledger_query 和 status_query。
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

_VOLTAGE_DESC = "电压等级，多个用逗号分隔。可选：1000kV、500kV、220kV。默认全部。"
_PROTECT_DESC = "保护类型，多个用逗号分隔。可选：线路保护、母线保护、变压器保护、断路器保护。默认全部。"


@tool_parameters(
    tool_parameters_schema(
        stName=StringSchema("厂站名称，如：皋城变、红石变"),
        voltageTypes=StringSchema(_VOLTAGE_DESC),
        protectTypes=StringSchema(_PROTECT_DESC),
    )
)
class RiskAssessmentCollectTool(Tool):
    """六源数据采集工具 — 一次性获取风险评估所需的全部数据。

    自动执行以下采集步骤：
      1. 台账     — 获取厂站所有保护装置列表（含 uniqueCode）
      2. 运行状态 — 查询校核状态、运行状态、通信状态
      3. 保信定值 — 获取每台装置的实时定值（当前值/标准值/上下限）
      4. 压板     — 获取硬压板、软压板、模拟量数据
      5. 告警     — 获取今日告警记录和保护告警状态
      6. 检修     — 获取检修工作记录

    调用后直接返回结构化六源数据包，Agent 无需再逐一调用 ledger_query 和 status_query。
    """

    @property
    def name(self) -> str:
        return "risk_assessment_collect"

    @property
    def description(self) -> str:
        return (
            "六源数据采集工具 — 一次性获取风险评估所需的全部数据。"
            "调用此工具后，Agent 无需再逐一调用 ledger_query 和 status_query。\n"
            "参数：stName(厂站名,必填), voltageTypes(电压等级,可选,不填则查全部), protectTypes(保护类型,可选,不填则查全部)。\n"
            "用户未指定电压等级和保护类型时，只传 stName 即可，工具自动按全部电压等级和保护类型采集。\n"
            "返回值包含六源完整数据：台账、运行状态、保信定值（装置运行时的实时定值数据，不是定值单文档）、压板/模拟量、告警、检修记录。\n"
            "拿到数据后必须基于数据生成结构化的运行风险评估报告，不要只返回原始数据。\n"
            "注意：此工具采集的是装置运行时的「定值数据」，不是「定值单」PDF文档。如需解析定值单文档，请使用 setting_parse_device 工具。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        from webui.services.risk_assessment.collector import collect_all, format_result_for_agent

        station = (kwargs.get("stName") or "").strip()
        if not station:
            return "错误：请提供厂站名称(stName)。"

        voltage_raw = (kwargs.get("voltageTypes") or "").strip()
        protect_raw = (kwargs.get("protectTypes") or "").strip()

        voltage_types = (
            [v.strip() for v in voltage_raw.replace("，", ",").split(",") if v.strip()]
            if voltage_raw
            else None
        )
        protect_types = (
            [p.strip() for p in protect_raw.replace("，", ",").split(",") if p.strip()]
            if protect_raw
            else None
        )

        result = await collect_all(
            station=station,
            voltage_types=voltage_types,
            protect_types=protect_types,
        )

        return format_result_for_agent(result)
