"""型号 → 知识库文件路由表."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# 简化版映射（v1 最小集；后续可从 setting-check SKILL.md 完整表加载）
ROUTING_TABLE: dict[str, dict[str, str]] = {
    # base_model: {厂家目录: "南瑞继保", 知识库子目录: "PCS-931"}
    "PCS-931": {"vendor": "南瑞继保", "dir": "PCS-931"},
    "PCS-915": {"vendor": "南瑞继保", "dir": "PCS-915"},
    "CSC-103": {"vendor": "北京四方", "dir": "CSC-103"},
    "CSC-326": {"vendor": "北京四方", "dir": "CSC-326"},
    "PSL-603": {"vendor": "国电南自", "dir": "PSL-603"},
    "PRS-753": {"vendor": "长园深瑞", "dir": "PRS-753"},
    "WMH-800": {"vendor": "许继电气", "dir": "WMH-800"},
    "WMH-801": {"vendor": "许继电气", "dir": "WMH-801"},
    "BP-2C": {"vendor": "长园深瑞", "dir": "BP-2C"},
}


@dataclass
class KnowledgeRef:
    base_model: str
    vendor: str
    dingshi_path: Path   # _定值说明.md
    baohu_path: Path     # _保护原理.md


class ModelRouter:
    def __init__(self, kb_root: Path):
        self.kb_root = Path(kb_root)

    def _strip_to_base(self, model_raw: str) -> Optional[str]:
        """从 PCS-931A-DG-G-L(V4.10) 提取 PCS-931.

        规则：连续字母数字-，遇到 ( 停止；按路由表前缀匹配最长 base。
        """
        # 去掉括号后缀
        head = model_raw.split("(")[0]
        # 按路由表前缀排序（长的优先），找最长匹配
        for base in sorted(ROUTING_TABLE.keys(), key=len, reverse=True):
            if head.startswith(base):
                return base
        return None

    def lookup(self, model_raw: str) -> Optional[KnowledgeRef]:
        base = self._strip_to_base(model_raw)
        if base is None:
            return None
        info = ROUTING_TABLE[base]
        vendor = info["vendor"]
        d = info["dir"]
        dingshi = self.kb_root / vendor / f"{d}_定值说明.md"
        baohu = self.kb_root / vendor / f"{d}_保护原理.md"
        if not dingshi.exists():
            return None
        return KnowledgeRef(
            base_model=base,
            vendor=vendor,
            dingshi_path=dingshi,
            baohu_path=baohu,
        )
