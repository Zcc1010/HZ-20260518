import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_token_module():
    module_path = Path(__file__).resolve().parents[1] / "webui" / "patches" / "token_estimation.py"
    spec = importlib.util.spec_from_file_location("test_token_estimation_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_collect_prompt_parts_includes_text_and_tools():
    token_patch = _load_token_module()

    parts = token_patch._collect_prompt_parts(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [{"type": "text", "text": "world"}]},
            {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read_file"}}]},
        ],
        tools=[{"type": "function", "function": {"name": "exec"}}],
    )

    joined = "\n".join(parts)
    assert "hello" in joined
    assert "world" in joined
    assert "read_file" in joined
    assert "\"exec\"" in joined


def test_heuristic_count_returns_non_zero_for_payload():
    token_patch = _load_token_module()

    assert token_patch._heuristic_count(["abcd" * 8]) > 0


def test_tiktoken_cache_path_uses_default_tempdir(monkeypatch):
    token_patch = _load_token_module()
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)

    cache_path = token_patch._tiktoken_cache_path()

    assert cache_path is not None
    assert cache_path.endswith("9b5ad71b2ce5302211f9c61530b329a4922fc6a4")


def test_resolve_memory_estimator_handles_missing_consolidator():
    token_patch = _load_token_module()

    consolidator_cls, method = token_patch._resolve_memory_estimator(SimpleNamespace())

    assert consolidator_cls is None
    assert method is None
