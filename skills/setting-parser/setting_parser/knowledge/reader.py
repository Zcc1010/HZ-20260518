"""读取说明书知识库：定值说明 / 保护原理."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .router import ModelRouter


class KnowledgeReader:
    def __init__(self, kb_root: str | Path):
        self.kb_root = Path(kb_root)
        self.router = ModelRouter(self.kb_root)

    def read_section(self, model_raw: str, section: str) -> str:
        """读取定值说明中指定小节（## 5.2.1 或 ### 5.2.1.x 形式）的内容."""
        ref = self.router.lookup(model_raw)
        if ref is None or not ref.dingshi_path.exists():
            return ""
        text = ref.dingshi_path.read_text(encoding="utf-8")
        return _extract_section(text, section)

    def extract_aliases(self, model_raw: str, section: str) -> list[str]:
        """从 '- 别名：A、B、C' 行提取别名列表."""
        section_text = self.read_section(model_raw, section)
        m = re.search(r"别名[：:]\s*([^\n]+)", section_text)
        if not m:
            return []
        return [a.strip() for a in re.split(r"[、,，]", m.group(1)) if a.strip()]

    def extract_range(self, model_raw: str, section: str) -> Optional[tuple[float, float]]:
        """从 '- 范围：0.10 ~ 50.00 A' 行提取范围."""
        section_text = self.read_section(model_raw, section)
        m = re.search(r"范围[：:]\s*([\d.]+)\s*[~～\-]\s*([\d.]+)", section_text)
        if not m:
            return None
        return float(m.group(1)), float(m.group(2))


def _extract_section(text: str, section: str) -> str:
    """提取 ## 5.2.1 形式的小节内容（直到下一个同级或上级标题）."""
    lines = text.splitlines()
    in_section = False
    section_depth = section.count(".")
    collected: list[str] = []
    pattern = re.compile(rf"^#{{{section_depth + 1}}}\s+{re.escape(section)}\b")
    next_pattern = re.compile(r"^#+\s+[\d.]+")
    for line in lines:
        if not in_section and pattern.match(line):
            in_section = True
            collected.append(line)  # 保留标题行（含小节名）便于后续断言
            continue
        if in_section:
            if next_pattern.match(line):
                # 检查深度
                if line.count(".") <= section.count("."):
                    break
            collected.append(line)
    return "\n".join(collected)
