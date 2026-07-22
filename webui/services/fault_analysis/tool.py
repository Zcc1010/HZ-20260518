# -*- coding: utf-8 -*-
"""fault_analysis_rerun tool — 重新执行故障分析报告生成。

Agent 调用此工具重新运行已有任务的分析流水线（使用已上传的录波文件）。
"""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema

RERUN_TOOL_DESC = (
    "重新执行故障分析报告生成。使用已上传的录波文件重新运行完整的分析流水线（9步）。\n"
    "参数：job_id（任务 ID，必填，从上下文的「故障分析任务信息」中获取）。\n"
    "当用户要求「重新生成报告」「重新分析」「重新生成」时调用此工具。\n"
    "返回值：成功时返回重新分析已启动的确认信息，失败时返回错误原因。"
)


def _get_service():
    """获取 FaultAnalysisService 实例（延迟导入避免循环依赖）。"""
    from webui.services.fault_analysis.service import FaultAnalysisService, APP_ID_FAULT_ANALYSIS
    from webui.services.agentplayground.paths import default_app_root
    from pathlib import Path

    # 与 API 路由保持一致：workspace = ~/.nanobot/workspace
    workspace = Path.home() / ".nanobot" / "workspace"
    app_root = default_app_root(workspace, APP_ID_FAULT_ANALYSIS)
    service = FaultAnalysisService(app_root=app_root)
    service.initialize()
    service._schedule_queue()
    return service


@tool_parameters(
    tool_parameters_schema(
        job_id=StringSchema("任务 ID（从上下文的「故障分析任务信息」中获取）"),
    )
)
class FaultAnalysisRerunTool(Tool):
    """重新执行故障分析报告生成。使用已上传的录波文件重新运行分析流水线。"""

    @property
    def name(self) -> str:
        return "fault_analysis_rerun"

    @property
    def description(self) -> str:
        return RERUN_TOOL_DESC

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        import asyncio

        job_id = (kwargs.get("job_id") or "").strip()
        if not job_id:
            return "错误：请提供 job_id 参数"

        service = _get_service()
        try:
            job = await service.rerun_job(job_id)
        except FileNotFoundError as e:
            return f"错误：{e}"
        except Exception as e:
            return f"错误：重新分析失败：{type(e).__name__}: {e}"

        if not job:
            return f"错误：未找到任务 ID 为 '{job_id}' 的故障分析任务"

        return (
            f"已成功触发任务 {job_id} 的重新分析。\n"
            f"厂站：{job.get('station', '未知')}\n"
            f"设备：{job.get('device', '未知')}\n"
            f"状态：排队等待分析\n"
            f"系统将自动读取已上传的录波文件重新执行完整的分析流水线，请耐心等待。"
        )
