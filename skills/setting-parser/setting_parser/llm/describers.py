"""描述生成器：基于说明书知识库 + LLM."""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .client import LLMClient, LLMConfig
from ..knowledge.reader import KnowledgeReader

PROMPTS_DIR = Path(__file__).parent / "prompts"


class ItemDescriber:
    def __init__(self, cfg: LLMConfig, reader: KnowledgeReader):
        self.client = LLMClient(cfg)
        self.reader = reader
        self._env = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=False)

    def describe(self, item_name: str, model_raw: str, function: str = "") -> str:
        # 取说明书相关段落（粗略：取前 3 个 section 的内容）
        kb_context = self._collect_context(model_raw)
        system = self._env.get_template("describe_item.j2").render(
            item_name=item_name,
            model_raw=model_raw,
            function=function or "（未指定）",
            kb_context=kb_context or "（说明书知识库无内容）",
        )
        return self.client.complete(system, "请生成专业描述。")

    def _collect_context(self, model_raw: str, max_chars: int = 3000) -> str:
        ref = self.reader.router.lookup(model_raw)
        if ref is None or not ref.dingshi_path.exists():
            return ""
        text = ref.dingshi_path.read_text(encoding="utf-8")
        return text[:max_chars]