# -*- coding: utf-8 -*-
"""配置加载模块 - 集成到 webui 配置系统"""
from webui.trip_briefing.models import PipelineConfig


def create_config_from_provider(
    api_url: str,
    api_key: str,
    model: str = "qwen3.5-flash",
) -> PipelineConfig:
    """
    从 provider 信息创建 PipelineConfig。

    Args:
        api_url: API URL
        api_key: API Key
        model: 模型名称

    Returns:
        PipelineConfig 实例
    """
    return PipelineConfig(
        api_url=api_url,
        api_key=api_key,
        model=model,
        timeout=180,
        max_retries=3,
        subagent_max_tokens=4096,
        subagent_timeout=120,
        main_agent_max_tokens=16384,
        main_agent_timeout=300,
        temperature=0.1,
        enable_thinking=False,
    )
