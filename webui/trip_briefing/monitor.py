# -*- coding: utf-8 -*-
"""运行监控模块 - Token 用量 + 运行时间"""
import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class StepRecord:
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


@dataclass
class _TrackState:
    """track() 上下文中的临时状态"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class Monitor:
    """运行监控器"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.records: List[StepRecord] = []

    def record(
        self,
        step: str,
        device: str = "",
        model: str = "python_script",
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int = 0,
        duration_ms: int = 0,
        success: bool = True,
        error: str = "",
    ):
        rec = StepRecord(
            step=step, device=device, model=model,
            input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=total_tokens, duration_ms=duration_ms,
            success=success, error=error,
        )
        self.records.append(rec)

    @contextmanager
    def track(self, step: str, device: str = "", model: str = "qwen3.5-flash"):
        """上下文管理器：自动记录步骤运行时间"""
        tracker = _TrackState()
        start = time.monotonic()
        print(f"  [{step}] {device} ...", flush=True)
        try:
            yield tracker
            elapsed = int((time.monotonic() - start) * 1000)
            self.record(
                step=step, device=device, model=model,
                input_tokens=tracker.input_tokens,
                output_tokens=tracker.output_tokens,
                total_tokens=tracker.total_tokens,
                duration_ms=elapsed,
                success=True,
            )
            tokens_str = f", {tracker.total_tokens} tokens" if tracker.total_tokens else ""
            print(f"  [{step}] {device} done ({elapsed}ms{tokens_str})", flush=True)
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            self.record(
                step=step, device=device, model=model,
                duration_ms=elapsed, success=False, error=repr(e),
            )
            print(f"  [{step}] {device} FAILED ({elapsed}ms): {e}", flush=True)
            raise

    def save_log(self) -> Path:
        """保存监控日志为 JSON"""
        total_input = sum(r.input_tokens for r in self.records)
        total_output = sum(r.output_tokens for r in self.records)
        total_tokens = sum(r.total_tokens for r in self.records)
        total_duration = sum(r.duration_ms for r in self.records)

        log_data = {
            "summary": {
                "total_duration_ms": total_duration,
                "total_tokens": total_tokens,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "devices_processed": sum(1 for r in self.records if r.step == "subagent"),
            },
            "steps": [
                {
                    "step": r.step,
                    "device": r.device,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "total_tokens": r.total_tokens,
                    "duration_ms": r.duration_ms,
                    "success": r.success,
                    "error": r.error,
                }
                for r in self.records
            ],
        }

        log_path = self.output_dir / "token_usage.log"
        log_path.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return log_path
