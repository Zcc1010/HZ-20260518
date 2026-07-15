"""parse 子命令：解析定值单 → JSON."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ..extractors.base import sha256_of_file
from ..extractors.excel import extract_excel
from ..extractors.pdf import extract_pdf_markdown
from ..knowledge.reader import KnowledgeReader
from ..llm.client import LLMConfig
from ..llm.extractor import SettingSheetExtractor
from ..models import (
    ControlWord,
    DeviceMeta,
    EquipmentParams,
    KnowledgeRef,
    ProtectionDeviceMeta,
    SettingItem,
    SettingSheet,
    SourceMeta,
)

logger = logging.getLogger(__name__)
console = Console()

# 保留 Typer app 供未来扩展（如 parse batch 子命令）
app = typer.Typer(help="解析定值单 → 结构化 JSON", invoke_without_command=True)


def _post_process(draft, kb_reader: KnowledgeReader) -> SettingSheet:
    """LLM 抽取的 draft → SettingSheet，补全 knowledge_ref / name_alias."""
    # 知识库路由
    model_raw = draft.protection_device.model_raw
    kb_ref = kb_reader.router.lookup(model_raw)

    # 补全 settings.knowledge_ref
    settings: list[SettingItem] = []
    for s in draft.settings:
        ref: Optional[KnowledgeRef] = None
        if kb_ref is not None:
            # 简化：从说明书中按 name_raw 搜前 100 字内是否出现范围
            dingshi = kb_ref.dingshi_path.read_text(encoding="utf-8") if kb_ref.dingshi_path.exists() else ""
            section, rng = _find_section_and_range(dingshi, s.name_raw)
            if section:
                try:
                    manual_rel = kb_ref.dingshi_path.relative_to(kb_ref.dingshi_path.parents[1])
                except ValueError:
                    manual_rel = kb_ref.dingshi_path
                ref = KnowledgeRef(
                    manual=str(manual_rel),
                    section=section,
                    range_min=rng[0] if rng else None,
                    range_max=rng[1] if rng else None,
                    range_unit=s.unit,
                )
        settings.append(SettingItem(
            item_no=s.item_no,
            name_raw=s.name_raw,
            name_alias=None,  # 后续可从 KB 提取别名（v1 留空）
            value=s.value,
            value_numeric=s.value_numeric,
            unit=s.unit,
            function=s.function,
            knowledge_ref=ref,
        ))

    kb_ref_str: Optional[str] = None
    if kb_ref is not None:
        try:
            kb_ref_str = str(kb_ref.dingshi_path.relative_to(kb_ref.dingshi_path.parents[1]))
        except ValueError:
            kb_ref_str = str(kb_ref.dingshi_path)

    return SettingSheet(
        source=SourceMeta(
            file_path="",  # 由调用方填充
            file_sha256="0" * 64,  # 占位
            parsed_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        ),
        device=DeviceMeta(**draft.device.model_dump()),
        protection_device=ProtectionDeviceMeta(
            **draft.protection_device.model_dump(),
            knowledge_base_ref=kb_ref_str,
        ),
        equipment_params=EquipmentParams(**draft.equipment_params.model_dump()),
        settings=settings,
        control_words=[ControlWord(**cw.model_dump()) for cw in draft.control_words],
        trip_matrix=None,  # v1 简化，不从 LLM 抽取矩阵
        parse_warnings=list(draft.parse_warnings),
    )


def _find_section_and_range(text: str, item_name: str) -> tuple[Optional[str], Optional[tuple[float, float]]]:
    """在说明书文本中查找 item_name 所在 section 与范围.

    简化算法：在文本中查找 item_name 出现的位置，向前回溯最近的 '## N.M.K' 标题，
    向后 200 字符内查找 "范围：min ~ max"。
    """
    if not text or not item_name:
        return None, None
    idx = text.find(item_name)
    if idx < 0:
        return None, None
    # 回溯找标题
    headings = list(re.finditer(r"^(##+\s+[\d.]+[^\n]*)", text[:idx], re.MULTILINE))
    if not headings:
        return None, None
    section = headings[-1].group(0).lstrip("#").strip()
    # 向后查范围
    window = text[idx:idx + 500]
    m = re.search(r"范围[：:]\s*([\d.]+)\s*[~～\-]\s*([\d.]+)", window)
    rng: Optional[tuple[float, float]] = (float(m.group(1)), float(m.group(2))) if m else None
    return section, rng


def parse_cmd(
    files: list[Path] = typer.Argument(..., help="一个或多个 PDF/Excel 定值单"),
    output_dir: Path = typer.Option(..., "--output-dir", "-o", help="JSON 输出目录"),
    kb_path: Optional[Path] = typer.Option(None, "--kb-path", help="说明书知识库根目录（默认复用 setting-check）"),
    model: Optional[str] = typer.Option(None, "--model", help="LLM 模型名（覆盖环境变量）"),
    workers: int = typer.Option(1, "--workers", "-w", help="并行数（v1 固定 1）"),
):
    """解析定值单 PDF/Excel → 结构化 JSON."""
    if not files:
        console.print("[red]未提供文件[/red]")
        raise typer.Exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = LLMConfig.from_env()
    if model:
        cfg.model = model
    kb_root = kb_path or Path(".claude/skills/setting-check/references/knowledge-base")
    kb_reader = KnowledgeReader(kb_root)
    extractor = SettingSheetExtractor(cfg)

    success = 0
    failed = 0
    for file_path in files:
        if not file_path.exists():
            console.print(f"[red]文件不存在: {file_path}[/red]")
            failed += 1
            continue
        try:
            sheet = _parse_one(file_path, extractor, kb_reader)
            out_file = output_dir / f"{file_path.stem}.json"
            out_file.write_text(sheet.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
            console.print(f"[green]✓[/green] {file_path.name} → {out_file.name}")
            success += 1
        except Exception as e:
            console.print(f"[red]✗ {file_path.name}: {e}[/red]")
            failed += 1
            logger.exception("parse failed: %s", file_path)

    if failed > 0:
        console.print(f"[yellow]{failed} 个文件解析失败[/yellow]")
        raise typer.Exit(2)
    console.print(f"[bold green]完成: {success} 个文件成功[/bold green]")


def _parse_one(path: Path, extractor: SettingSheetExtractor, kb_reader: KnowledgeReader) -> SettingSheet:
    """解析单份文件."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        extracted = extract_pdf_markdown(str(path), use_ocr=True)
    elif suf in (".xls", ".xlsx"):
        extracted = extract_excel(str(path))
    else:
        raise ValueError(f"不支持的文件类型: {suf}")

    # 拼装 kb_hint
    model_raw_guess = ""  # 留空，让 LLM 先识别型号
    draft = extractor.extract(
        markdown_text=extracted.markdown,
        model_raw=model_raw_guess,
        kb_hint="",
    )
    sheet = _post_process(draft, kb_reader)
    sheet.source.file_path = str(path)
    sheet.source.file_sha256 = sha256_of_file(str(path))
    return sheet
