"""stats 子命令：描述统计 + 异常检测 + LLM 总结."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..stats.anomaly import detect_anomalies
from ..stats.descriptive import group_sheets_by, summarize_sheet

logger = logging.getLogger(__name__)
console = Console()

# 保留 Typer sub-app 以兼容 cli.py 注册
app = typer.Typer(help="对已解析的 JSON 做统计分析")


def _load_sheets(paths: list[Path]) -> list[dict]:
    sheets: list[dict] = []
    for p in paths:
        candidates: list[Path]
        if "*" in p.name or "?" in p.name:
            candidates = sorted(p.parent.glob(p.name))
        else:
            candidates = [p]
        for f in candidates:
            if not f.exists() or f.suffix != ".json":
                continue
            try:
                sheets.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception as e:
                console.print(f"[red]读取失败 {f}: {e}[/red]")
    return sheets


def stats_cmd(
    files: list[Path] = typer.Argument(..., help="一个或多个 JSON 文件（支持 glob）"),
    group_by: Optional[str] = typer.Option(None, "--group-by", help="分组字段: equipment_type | model_base | station | voltage_kv"),
    anomaly_check: bool = typer.Option(False, "--anomaly-check", help="启用异常检测"),
    summary_output: Optional[Path] = typer.Option(None, "--summary-output", help="统计报告输出到 md 文件"),
):
    """对已解析的定值单做统计分析."""
    sheets = _load_sheets(files)
    if not sheets:
        console.print("[red]未加载到任何 JSON[/red]")
        raise typer.Exit(1)

    # 1. 摘要表
    table = Table(title=f"定值单摘要（共 {len(sheets)} 份）")
    table.add_column("站名", style="cyan")
    table.add_column("设备类型", style="magenta")
    table.add_column("基础型号")
    table.add_column("电压等级")
    table.add_column("定值项数", justify="right")
    table.add_column("控制字数", justify="right")
    for sheet in sheets:
        s = summarize_sheet(sheet)
        table.add_row(
            str(s["station"]),
            str(s["equipment_type"]),
            str(s["model_base"]),
            f"{s['voltage_kv']} kV",
            str(s["settings_count"]),
            str(s["control_words_count"]),
        )
    console.print(table)

    # 2. 分组
    if group_by:
        groups = group_sheets_by(sheets, by=group_by)
        console.print(f"\n[bold]按 {group_by} 分组:[/bold]")
        for k, v in groups.items():
            console.print(f"  {k}: {len(v)} 份")

    # 3. 异常检测
    if anomaly_check:
        console.print("\n[bold]异常检测:[/bold]")
        total_oof = 0
        total_near = 0
        total_invalid = 0
        for sheet in sheets:
            report = detect_anomalies(sheet)
            station = sheet.get("device", {}).get("station", "?")
            for item in report["out_of_range"]:
                console.print(f"  [red]✗[/red] {station} | {item['item']}: {item['detail']}")
                total_oof += 1
            for item in report["near_boundary"]:
                console.print(f"  [yellow]⚠[/yellow] {station} | {item['item']}: {item['detail']}")
                total_near += 1
            for item in report["control_word_invalid"]:
                console.print(f"  [red]✗[/red] {station} | 控制字 {item['item']}={item['value']} 非法")
                total_invalid += 1
        console.print(f"\n汇总: 越界 {total_oof} | 接近边界 {total_near} | 控制字非法 {total_invalid}")

    # 4. 报告输出
    if summary_output:
        lines = [f"# 统计报告\n", f"共 {len(sheets)} 份定值单\n"]
        for sheet in sheets:
            s = summarize_sheet(sheet)
            lines.append(f"## {s['station']} - {s['equipment_name']}")
            lines.append(f"- 设备类型: {s['equipment_type']}")
            lines.append(f"- 型号: {s['model_base']} ({sheet.get('protection_device', {}).get('firmware_version', '')})")
            lines.append(f"- 定值项数: {s['settings_count']}")
            lines.append(f"- 控制字数: {s['control_words_count']}")
            if anomaly_check:
                report = detect_anomalies(sheet)
                if report["out_of_range"] or report["near_boundary"] or report["control_word_invalid"]:
                    lines.append(f"  - 越界: {len(report['out_of_range'])}")
                    lines.append(f"  - 接近边界: {len(report['near_boundary'])}")
                    lines.append(f"  - 控制字非法: {len(report['control_word_invalid'])}")
            lines.append("")
        summary_output.write_text("\n".join(lines), encoding="utf-8")
        console.print(f"\n[green]报告已写入: {summary_output}[/green]")


# 在 sub-app 上也注册命令（保持原设计）
app.command(name="stats_cmd")(stats_cmd)
