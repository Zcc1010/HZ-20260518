# -*- coding: utf-8 -*-
"""monthly_plan_process tool — 月度计划 Excel 关键词标记工具。

Agent 调用此工具处理用户上传的月度计划 Excel 文件，
自动搜索"工作内容"列中的关键词，标记匹配行黄色，生成汇总。
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        filePath=StringSchema("月度计划 Excel 文件的绝对路径（.xls 或 .xlsx）"),
    )
)
class MonthlyPlanProcessTool(Tool):
    """月度计划处理工具 — 搜索关键词、标记黄色行、生成汇总表。

    当用户上传月度计划 Excel 文件时调用此工具。
    自动搜索"工作内容"列中的关键词（启动、流变、更换、改造、迁改、通道、扩容、升高、改接、开断、CT、送电、扩建），
    将匹配的行标记黄色背景，并返回匹配行汇总表。
    """

    @property
    def name(self) -> str:
        return "monthly_plan_process"

    @property
    def description(self) -> str:
        return (
            "月度计划处理工具 — 处理用户上传的月度计划 Excel 文件。\n"
            '自动搜索"工作内容"列中的关键词（启动、流变、更换、改造、迁改、通道、扩容、升高、改接、开断、CT、送电、扩建），\n'
            "将匹配的行标记黄色背景，返回匹配行汇总表和标记后的文件路径。\n"
            "参数：filePath（Excel 文件绝对路径，必填）。\n"
            "返回值包含：总行数、匹配行数、关键词命中统计、匹配明细、标记后文件路径。\n"
            "拿到结果后，以清晰的表格展示匹配统计和明细。如果用户要求发送文件，用 message(media=[标记文件路径]) 发送。"
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        from webui.services.monthly_plan import process_monthly_plan, format_result_for_agent

        file_path = (kwargs.get("filePath") or "").strip()
        if not file_path:
            return "错误：请提供 Excel 文件路径(filePath)。"

        try:
            result = process_monthly_plan(file_path)
            return format_result_for_agent(result)
        except FileNotFoundError as e:
            return f"错误：{e}"
        except ValueError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"处理失败：{type(e).__name__}: {e}"
