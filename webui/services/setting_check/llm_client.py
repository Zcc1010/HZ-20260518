# -*- coding: utf-8 -*-
"""LLM API 客户端 - OpenAI 兼容"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict

import openai

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 响应"""
    success: bool
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_message: str = ""


class LLMClient:
    """OpenAI 兼容 LLM 客户端"""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout: int = 60,
        max_retries: int = 3,
        enable_thinking: bool = True,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.enable_thinking = enable_thinking
        self.client = openai.OpenAI(
            base_url=api_url,
            api_key=api_key,
            timeout=timeout,
        )

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """调用 LLM chat completion API，支持重试"""
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"enable_thinking": self.enable_thinking},
                )

                if response.choices and len(response.choices) > 0:
                    msg = response.choices[0].message
                    content = msg.content or ""
                    reasoning = getattr(msg, "reasoning_content", None) or ""
                    if reasoning:
                        logger.info(f"LLM reasoning ({len(reasoning)} chars) discarded")
                    return LLMResponse(
                        success=True,
                        content=content,
                        prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                        completion_tokens=response.usage.completion_tokens if response.usage else 0,
                        total_tokens=response.usage.total_tokens if response.usage else 0,
                    )
                else:
                    logger.warning(f"LLM 返回空响应 (尝试 {attempt + 1}/{self.max_retries})")

            except Exception as e:
                logger.warning(f"LLM 调用失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        error_msg = f"LLM 调用失败，已重试 {self.max_retries} 次"
        logger.error(error_msg)
        return LLMResponse(success=False, error_message=error_msg)
