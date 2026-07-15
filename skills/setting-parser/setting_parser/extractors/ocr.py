"""PaddleOCR 表格提取（独立函数，便于测试 monkeypatch）."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_tables_with_ocr(path: str) -> list[list[list[str]]]:
    """从 PDF 提取表格，返回 [ [ [row] ] ] 形式.

    通过 monkeypatch _paddle_ocr_tables 实现真正的 OCR 逻辑。
    """
    return _paddle_ocr_tables(path)


def _paddle_ocr_tables(path: str) -> list[list[list[str]]]:
    """真实 PaddleOCR 调用（v1 占位实现，可后续替换）.

    当前实现：把每页视为一个空表格。
    后续接入 PaddleOCR 的 PPStructure API 后替换此函数体。
    """
    # 占位：返回空表格列表（v1 最小可用）
    # 实际项目可接入 paddleocr.PPStructure 或 docx 的 pdfplumber
    if not Path(path).exists():
        raise FileNotFoundError(path)
    return []
