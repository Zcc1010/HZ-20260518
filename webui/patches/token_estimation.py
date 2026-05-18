"""Offline-safe token estimation patch for nanobot.

This avoids repeated cold-path stalls when tiktoken has no local cache and
tries to fetch encoder data in restricted environments.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any

_PATCHED = False
_CL100K_BASE_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"


def _collect_prompt_parts(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> list[str]:
    parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        parts.append(text)
                elif part is not None:
                    parts.append(json.dumps(part, ensure_ascii=False))
        elif content is not None:
            parts.append(json.dumps(content, ensure_ascii=False))

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            parts.append(json.dumps(tool_calls, ensure_ascii=False))

        reasoning = msg.get("reasoning_content")
        if isinstance(reasoning, str) and reasoning:
            parts.append(reasoning)

        for key in ("name", "tool_call_id"):
            value = msg.get(key)
            if isinstance(value, str) and value:
                parts.append(value)

    if tools:
        parts.append(json.dumps(tools, ensure_ascii=False))
    return parts


def _collect_message_parts(message: dict[str, Any]) -> list[str]:
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            elif part is not None:
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        parts.append(json.dumps(content, ensure_ascii=False))

    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        parts.append(reasoning)
    return parts


def _heuristic_count(parts: list[str]) -> int:
    payload = "\n".join(parts)
    if not payload:
        return 0
    return max(1, len(payload) // 4)


def _tiktoken_cache_path() -> str | None:
    cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR")
    if cache_dir is None:
        cache_dir = os.environ.get("DATA_GYM_CACHE_DIR")
    if cache_dir is None:
        cache_dir = os.path.join(tempfile.gettempdir(), "data-gym-cache")
    if cache_dir == "":
        return None
    cache_key = hashlib.sha1(_CL100K_BASE_URL.encode()).hexdigest()
    return os.path.join(cache_dir, cache_key)


def _resolve_memory_estimator(memory_module: Any) -> tuple[type | None, Any | None]:
    """Return the class/method pair to patch when the runtime exposes it."""
    consolidator_cls = getattr(memory_module, "MemoryConsolidator", None)
    if consolidator_cls is None:
        return None, None
    original_method = getattr(consolidator_cls, "estimate_session_prompt_tokens", None)
    if original_method is None:
        return None, None
    return consolidator_cls, original_method


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def apply() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    import nanobot.agent.memory as memory_module
    import nanobot.utils.helpers as helpers_module

    original_chain = helpers_module.estimate_prompt_tokens_chain

    offline_safe = _env_flag("WEBUI_TIKTOKEN_OFFLINE_SAFE", True)
    state: dict[str, Any] = {
        "encoding": None,
        "disabled": False,
        "failure": None,
        "cache_path": _tiktoken_cache_path(),
    }

    def _get_encoding():
        if state["encoding"] is not None:
            return state["encoding"]
        if state["disabled"] or not offline_safe:
            return None
        cache_path = state["cache_path"]
        if cache_path is not None and not os.path.exists(cache_path):
            state["disabled"] = True
            state["failure"] = f"missing_tiktoken_cache:{cache_path}"
            return None
        try:
            state["encoding"] = helpers_module.tiktoken.get_encoding("cl100k_base")
            return state["encoding"]
        except Exception as exc:
            state["disabled"] = True
            state["failure"] = repr(exc)
            return None

    def estimate_prompt_tokens_patched(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        parts = _collect_prompt_parts(messages, tools)
        encoding = _get_encoding()
        if encoding is not None:
            return len(encoding.encode("\n".join(parts))) + len(messages) * 4

        return _heuristic_count(parts) + len(messages) * 4

    def estimate_message_tokens_patched(message: dict[str, Any]) -> int:
        parts = _collect_message_parts(message)
        payload = "\n".join(parts)
        if not payload:
            return 4

        encoding = _get_encoding()
        if encoding is not None:
            return max(4, len(encoding.encode(payload)) + 4)

        return max(4, len(payload) // 4 + 4)

    def estimate_prompt_tokens_chain_patched(
        provider: Any,
        model: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[int, str]:
        provider_counter = getattr(provider, "estimate_prompt_tokens", None)
        if callable(provider_counter):
            try:
                tokens, source = provider_counter(messages, tools, model)
                if isinstance(tokens, (int, float)) and tokens > 0:
                    return int(tokens), str(source or "provider_counter")
            except Exception:
                pass

        estimated = estimate_prompt_tokens_patched(messages, tools)
        source = "heuristic" if state["disabled"] else "tiktoken"
        if estimated > 0:
            return int(estimated), source
        return original_chain(provider, model, messages, tools)

    consolidator_cls, original_memory_estimate_session_prompt_tokens = _resolve_memory_estimator(memory_module)

    def estimate_session_prompt_tokens_patched(self, session: Any) -> tuple[int, str]:
        return original_memory_estimate_session_prompt_tokens(self, session)

    helpers_module.estimate_prompt_tokens = estimate_prompt_tokens_patched
    helpers_module.estimate_message_tokens = estimate_message_tokens_patched
    helpers_module.estimate_prompt_tokens_chain = estimate_prompt_tokens_chain_patched

    memory_module.estimate_message_tokens = estimate_message_tokens_patched
    memory_module.estimate_prompt_tokens_chain = estimate_prompt_tokens_chain_patched
    if consolidator_cls is not None and original_memory_estimate_session_prompt_tokens is not None:
        consolidator_cls.estimate_session_prompt_tokens = estimate_session_prompt_tokens_patched
