"""kb 子命令：知识库管理."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..knowledge.router import ROUTING_TABLE, ModelRouter

console = Console()

app = typer.Typer(help="知识库管理")


def _resolve_kb(kb_path: Optional[Path]) -> Path:
    return kb_path or Path(".claude/skills/setting-check/references/knowledge-base")


@app.command("list")
def list_cmd(
    kb_path: Optional[Path] = typer.Option(None, "--kb-path"),
):
    """列出已入库的厂家 / 型号."""
    root = _resolve_kb(kb_path)
    if not root.exists():
        console.print(f"[red]知识库路径不存在: {root}[/red]")
        raise typer.Exit(1)

    table = Table(title=f"知识库: {root}")
    table.add_column("厂家", style="cyan")
    table.add_column("基础型号", style="magenta")
    table.add_column("定值说明", style="green")
    table.add_column("保护原理", style="green")

    router = ModelRouter(root)
    for base, info in sorted(ROUTING_TABLE.items()):
        vendor = info["vendor"]
        d = info["dir"]
        dingshi = root / vendor / f"{d}_定值说明.md"
        baohu = root / vendor / f"{d}_保护原理.md"
        table.add_row(
            vendor,
            base,
            "✓" if dingshi.exists() else "✗",
            "✓" if baohu.exists() else "✗",
        )
    console.print(table)


@app.command("lookup")
def lookup_cmd(
    model: str = typer.Argument(..., help="型号字符串，如 PCS-931A-DG-G-L"),
    kb_path: Optional[Path] = typer.Option(None, "--kb-path"),
):
    """反查某型号对应的知识库文件."""
    root = _resolve_kb(kb_path)
    router = ModelRouter(root)
    ref = router.lookup(model)
    if ref is None:
        console.print(f"[red]未匹配到型号: {model}[/red]")
        raise typer.Exit(1)
    console.print(f"基础型号: {ref.base_model}")
    console.print(f"厂家: {ref.vendor}")
    console.print(f"定值说明: {ref.dingshi_path}")
    console.print(f"保护原理: {ref.baohu_path}")


@app.command("index")
def index_cmd(
    kb_path: Optional[Path] = typer.Option(None, "--kb-path"),
):
    """重建型号→文件映射缓存（v1 占位，后续可持久化）."""
    root = _resolve_kb(kb_path)
    console.print(f"扫描 {root} ...")
    count = 0
    for vendor_dir in root.iterdir():
        if not vendor_dir.is_dir():
            continue
        for f in vendor_dir.glob("*_定值说明.md"):
            count += 1
    console.print(f"[green]已索引 {count} 份说明书（v1 不持久化，每次启动重建）[/green]")