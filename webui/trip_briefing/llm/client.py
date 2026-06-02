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
        model: str = "qwen3.5-flash",
        timeout: int = 60,
        max_retries: int = 3,
        enable_thinking: bool = False,
    ):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
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
        """调用 LLM chat completion API，支持重试，使用流式模式防止挂起"""
        for attempt in range(self.max_retries):
            try:
                # 使用流式模式，防止 API 挂起
                stream = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body={"enable_thinking": self.enable_thinking},
                )

                content_parts = []
                prompt_tokens = 0
                completion_tokens = 0
                total_tokens = 0
                last_chunk_time = time.time()

                for chunk in stream:
                    current_time = time.time()
                    # 检查 chunk 间超时（60秒无数据视为挂起）
                    if current_time - last_chunk_time > 60:
                        logger.warning(f"LLM 流式响应超时 (60秒无数据)")
                        break
                    last_chunk_time = current_time

                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            content_parts.append(delta.content)

                    # 获取 usage 信息（最后一个 chunk 包含）
                    if hasattr(chunk, 'usage') and chunk.usage:
                        prompt_tokens = chunk.usage.prompt_tokens or 0
                        completion_tokens = chunk.usage.completion_tokens or 0
                        total_tokens = chunk.usage.total_tokens or 0

                content = "".join(content_parts)
                if content:
                    return LLMResponse(
                        success=True,
                        content=content,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
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
