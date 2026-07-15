"""describe subcommand: query professional description for a setting item."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown

from ..knowledge.reader import KnowledgeReader
from ..llm.client import LLMConfig
from ..llm.describers import ItemDescriber

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(help="查询定值项的专业描述")


def _find_item(sheet: dict, item_name: str) -> Optional[dict]:
    for item in sheet.get("settings", []):
        if item.get("name_raw") == item_name or item.get("name_alias") == item_name:
            return item
    for cw in sheet.get("control_words", []):
        if cw.get("name_raw") == item_name or cw.get("name_alias") == item_name:
            return {"name_raw": cw.get("name_raw"), "function": "控制字"}
    return None


@app.callback(invoke_without_command=True)
def describe_cmd(
    ctx: typer.Context,
    item_name: str = typer.Argument(..., help="定值项名（原名或别名）"),
    from_file: Path = typer.Option(..., "--from", help="已解析的 JSON 文件"),
    kb_path: Optional[Path] = typer.Option(None, "--kb-path"),
    model: Optional[str] = typer.Option(None, "--model"),
):
    if ctx.invoked_subcommand is not None:
        return
    """根据已解析的定值单 + 说明书知识库，生成定值项的专业描述."""
    if not from_file.exists():
        console.print(f"[red]文件不存在: {from_file}[/red]")
        raise typer.Exit(1)

    sheet = json.loads(from_file.read_text(encoding="utf-8"))
    item = _find_item(sheet, item_name)
    if item is None:
        console.print(f"[red]定值单中未找到定值项: {item_name}[/red]")
        raise typer.Exit(1)

    model_raw = sheet.get("protection_device", {}).get("model_raw", "")
    function = item.get("function", "")

    cfg = LLMConfig.from_env()
    if model:
        cfg.model = model
    kb_root = kb_path or Path(".claude/skills/setting-check/references/knowledge-base")
    reader = KnowledgeReader(kb_root)
    describer = ItemDescriber(cfg, reader)

    description = describer.describe(item_name, model_raw, function=function)
    console.print(Markdown(description))