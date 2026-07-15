"""LLM 结构化抽取器：从 markitdown + KB hint 抽取 LLMSheetDraft."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from .client import LLMClient, LLMConfig
from .schemas import LLMSheetDraft

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


class SettingSheetExtractor:
    def __init__(self, cfg: LLMConfig):
        self.client = LLMClient(cfg)
        self._env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=False)

    def _render_prompt(self, markdown_text: str, model_raw: str, kb_hint: str) -> tuple[str, str]:
        system = self._env.get_template("parse_setting_sheet.j2").render(
            markdown_text=markdown_text,
            model_raw=model_raw,
            kb_hint=kb_hint or "（无）",
        )
        user = "请按 schema 输出 JSON。"
        return system, user

    def _retry_with_feedback(self, system: str, user: str, bad_output: str) -> LLMSheetDraft:
        """反馈错误给 LLM 让其重试."""
        feedback = f"{user}\n\n上一次输出不是合法 JSON: {bad_output[:200]}\n请重新输出严格 JSON。"
        raw = self.client.complete(system, feedback, response_format_json=True)
        return LLMSheetDraft.model_validate_json(raw)

    def extract(self, markdown_text: str, model_raw: str, kb_hint: str = "") -> LLMSheetDraft:
        system, user = self._render_prompt(markdown_text, model_raw, kb_hint)
        raw = self.client.complete(system, user, response_format_json=True)
        try:
            return LLMSheetDraft.model_validate_json(raw)
        except Exception as e:
            logger.warning("LLM 输出 JSON 解析失败: %s, 触发重试", e)
            return self._retry_with_feedback(system, user, raw)