# -*- coding: utf-8 -*-
"""数据模型定义"""
from pydantic import BaseModel, Field
from typing import Optional


class StepRecord(BaseModel):
    """单个步骤的执行记录"""
    step: str
    device: str = ""
    model: str = "python_script"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration_ms: int = 0
    success: bool = True
    error: str = ""


class PipelineConfig(BaseModel):
    """Pipeline 配置"""
    api_url: str
    api_key: str
    model: str = "qwen3.5-flash"
    timeout: int = 120
    max_retries: int = 3
    subagent_max_tokens: int = 4096
    main_agent_max_tokens: int = 8192
    temperature: float = 0.1
    enable_thinking: bool = False


class DeviceFiles(BaseModel):
    """一套保护装置的文件路径集合"""
    station: str
    set_number: str
    hdr_path: Optional[str] = None
    rms_csv_path: Optional[str] = None
    events_csv_path: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{self.station}_{self.set_number}"


class MonitorSummary(BaseModel):
    """运行监控汇总"""
    total_duration_ms: int = 0
    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    devices_processed: int = 0
