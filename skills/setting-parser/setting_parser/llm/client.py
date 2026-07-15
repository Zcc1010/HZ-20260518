"""OpenAI 兼容 LLM 客户端，含退避重试."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import openai
from openai import OpenAI
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    max_retries: int = 3
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.environ.get("SETTING_PARSER_LLM_API_KEY")
        if not api_key:
            raise ValueError(
                "环境变量 SETTING_PARSER_LLM_API_KEY 未设置。"
                "请设置 API key（参考 README）。"
            )
        return cls(
            api_key=api_key,
            base_url=os.environ.get("SETTING_PARSER_LLM_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("SETTING_PARSER_LLM_MODEL", "gpt-4o-mini"),
            max_retries=int(os.environ.get("SETTING_PARSER_LLM_MAX_RETRIES", "3")),
            timeout_s=float(os.environ.get("SETTING_PARSER_LLM_TIMEOUT", "60")),
        )


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._openai = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=cfg.timeout_s)

    def _call(self, system: str, user: str, response_format_json: bool) -> str:
        kwargs = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format_json:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._openai.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def complete(
        self,
        system: str,
        user: str,
        response_format_json: bool = False,
    ) -> str:
        """带指数退避重试的调用."""
        backoff = 1.0
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.max_retries):
            try:
                return self._call(system, user, response_format_json)
            except (RateLimitError, APITimeoutError, APIConnectionError, APIError) as e:  # 限流/超时/网络错误
                last_exc = e
                if attempt == self.cfg.max_retries - 1:
                    break
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError(f"LLM 调用失败（{self.cfg.max_retries} 次重试用尽）: {last_exc}")
