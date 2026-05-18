import ast
from pathlib import Path


PROMPT_PATCH = Path(__file__).resolve().parents[1] / "webui" / "patches" / "prompt.py"


def _find_nested_function(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in prompt patch")


def test_prompt_patch_accepts_and_forwards_channel_keyword() -> None:
    module = ast.parse(PROMPT_PATCH.read_text(encoding="utf-8"))
    build_prompt = _find_nested_function(module, "_build_system_prompt_patched")

    arg_names = [arg.arg for arg in build_prompt.args.args]
    assert "channel" in arg_names, "patched build_system_prompt must accept channel keyword"

    orig_call = next(
        node for node in ast.walk(build_prompt)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_orig_build_system_prompt"
    )
    forwarded_keywords = {kw.arg for kw in orig_call.keywords if kw.arg is not None}
    assert "channel" in forwarded_keywords, "patched build_system_prompt must forward channel keyword"


def test_identity_patch_accepts_channel_keyword() -> None:
    module = ast.parse(PROMPT_PATCH.read_text(encoding="utf-8"))
    get_identity = _find_nested_function(module, "_get_identity_patched")

    arg_names = [arg.arg for arg in get_identity.args.args]
    assert "channel" in arg_names, "patched _get_identity must accept channel keyword"
