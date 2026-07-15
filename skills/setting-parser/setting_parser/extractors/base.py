"""提取器抽象接口."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ExtractedText:
    """提取结果."""
    source_path: str
    markdown: str
    tables: list[list[list[str]]]  # 二维数组的列表（每个元素是一个表格）
    warnings: list[str]


class Extractor(Protocol):
    def extract(self, path: str) -> ExtractedText:
        ...


def sha256_of_file(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
