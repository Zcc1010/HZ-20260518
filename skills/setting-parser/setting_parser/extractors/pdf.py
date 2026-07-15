"""PDF 提取器：markitdown 文字 + PaddleOCR 表格."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .base import ExtractedText, sha256_of_file
from .ocr import extract_tables_with_ocr

logger = logging.getLogger(__name__)


def markitdown_call(path: str) -> str:
    """调用 markitdown 库（独立函数，便于 monkeypatch 测试）."""
    from markitdown import MarkItDown

    md = MarkItDown()
    result = md.convert(path)
    return result.text_content


def extract_pdf_markdown(
    path: str,
    *,
    use_ocr: bool = True,
) -> ExtractedText:
    """从 PDF 提取 markdown 文字 + 表格.

    Args:
        path: PDF 文件路径
        use_ocr: 是否额外跑 PaddleOCR 提取表格（耗时但更准）
    """
    if not Path(path).exists():
        raise FileNotFoundError(f"PDF 不存在: {path}")

    warnings: list[str] = []

    # 1. markitdown 主路径
    try:
        markdown = markitdown_call(path)
    except Exception as e:
        logger.warning("markitdown 失败: %s", e)
        markdown = ""
        warnings.append(f"markitdown 抽取失败: {e}")

    # 2. PaddleOCR 表格补充
    tables: list[list[list[str]]] = []
    if use_ocr:
        try:
            tables = extract_tables_with_ocr(path)
        except Exception as e:
            logger.warning("PaddleOCR 失败: %s", e)
            warnings.append(f"PaddleOCR 表格抽取失败: {e}")

    return ExtractedText(
        source_path=path,
        markdown=markdown,
        tables=tables,
        warnings=warnings,
    )
