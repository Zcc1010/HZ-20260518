"""Trip briefing read/write tools — read and modify trip briefing reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


_AGENTPLAYGROUND_DIR = (Path.home() / ".nanobot" / "agentplayground").resolve()


def _check_path(path: Path) -> None:
    """确保文件路径在 agentplayground 目录下，防止越权写入。"""
    resolved = path.resolve()
    try:
        resolved.relative_to(_AGENTPLAYGROUND_DIR)
    except ValueError:
        raise PermissionError(f"路径 {path} 不在 agentplayground 目录下，拒绝操作")


def _get_service():
    from webui.services.wave_record_parser.service import WaveRecordParserService
    return WaveRecordParserService()


def _find_report_file(job_root: Path) -> Path | None:
    """在 job output 目录中查找报告 .md 文件。"""
    output_dir = job_root / "output"
    if not output_dir.exists():
        return None
    # 优先匹配 跳闸简报.md
    preferred = output_dir / "跳闸简报.md"
    if preferred.exists():
        return preferred
    # 回退：任意 .md
    md_files = list(output_dir.glob("*.md"))
    return md_files[0] if md_files else None


def _replace_section(full_content: str, section_keyword: str, new_section_body: str) -> str | None:
    """替换 Markdown 文档中指定章节的内容。

    Args:
        full_content: 完整的 Markdown 文档
        section_keyword: 章节标题关键字（部分匹配）
        new_section_body: 该章节的新内容（不含 ## 标题行）

    Returns:
        替换后的完整内容，未找到章节时返回 None
    """
    import re

    # 按 ## 标题分割，保留标题行
    parts = re.split(r"(?=^## )", full_content, flags=re.MULTILINE)

    for i, part in enumerate(parts):
        lines = part.strip().split("\n", 1)
        if not lines:
            continue
        title_line = lines[0]
        if not title_line.startswith("## "):
            continue
        if section_keyword in title_line:
            # 找到目标章节，替换内容
            new_part = title_line + "\n\n" + new_section_body.strip() + "\n"
            parts[i] = new_part
            return "\n".join(parts)

    return None


READ_TOOL_DESC = """读取跳闸简报报告内容。可通过 job_id 直接读取，或通过站点名称搜索匹配的任务。

参数说明：
- job_id: 任务 ID，直接指定要读取的任务
- station: 站点名称，模糊搜索该站点下的所有跳闸简报任务
- external_id: 外部事件 ID，通过故障事件 ID 查找任务

至少需要提供 job_id、station、external_id 其中一个参数。
"""

WRITE_TOOL_DESC = """改写跳闸简报报告的指定章节。只替换目标章节内容，其余章节保持不变。

参数说明：
- job_id: 任务 ID（必填）
- section: 要修改的章节标题（必填），例如"故障基本情况"、"保护配置情况"等，支持部分匹配
- content: 该章节的新内容（必填，Markdown 格式，不含 ## 标题行）

使用流程：先用 trip_briefing_read 读取报告，找到要修改的章节标题，再用本工具只替换该章节。
"""


@tool_parameters(
    tool_parameters_schema(
        job_id=StringSchema("任务 ID，直接指定要读取的任务"),
        station=StringSchema("站点名称，模糊搜索该站点下的跳闸简报"),
        external_id=StringSchema("外部事件 ID，通过故障事件 ID 查找任务"),
    )
)
class TripBriefingReadTool(Tool):
    """读取跳闸简报报告内容。支持按 job_id、站点名称或外部事件 ID 查询。"""

    @property
    def name(self) -> str:
        return "trip_briefing_read"

    @property
    def description(self) -> str:
        return READ_TOOL_DESC

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        job_id = (kwargs.get("job_id") or "").strip()
        station = (kwargs.get("station") or "").strip()
        external_id = (kwargs.get("external_id") or "").strip()

        if not job_id and not station and not external_id:
            return "请至少提供一个参数：job_id、station 或 external_id"

        service = _get_service()

        # 按 external_id 查找
        if external_id and not job_id:
            job = service.get_job_by_external_id(external_id)
            if not job:
                return f"未找到外部事件 ID 为 '{external_id}' 的跳闸简报任务"
            return self._read_report(service, job)

        # 按 job_id 直接读取
        if job_id:
            job = service.get_job(job_id)
            if not job:
                return f"未找到任务 ID 为 '{job_id}' 的跳闸简报"
            return self._read_report(service, job)

        # 按 station 搜索
        jobs = service.search_jobs(station)
        if not jobs:
            return f"未找到站点 '{station}' 相关的跳闸简报任务"

        completed = [j for j in jobs if j.get("status") == "completed"]
        if not completed:
            names = [f"  - {j.get('station', '')} / {j.get('device', '')}（{j['id']}）状态: {j.get('status', '')}" for j in jobs]
            return f"找到 {len(jobs)} 个任务，但均未完成：\n" + "\n".join(names)

        # 如果只有一个已完成任务，直接返回报告
        if len(completed) == 1:
            return self._read_report(service, completed[0])

        # 多个任务，返回列表供选择
        lines = [f"找到 {len(completed)} 个已完成的跳闸简报任务："]
        for j in completed:
            lines.append(f"  - ID: {j['id']}  站点: {j.get('station', '')}  设备: {j.get('device', '')}  时间: {j.get('created_at', '')}")
        lines.append("\n请使用 job_id 参数指定要读取的任务。")
        return "\n".join(lines)

    def _read_report(self, service, job: dict) -> str:
        job_id = job["id"]
        report_path = _find_report_file(service.app_root / "jobs" / job_id)
        if not report_path:
            return f"任务 {job_id} 已完成但未找到报告文件"

        _check_path(report_path)

        try:
            content = report_path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"读取报告文件失败：{exc}"

        station = job.get("station", "未知")
        device = job.get("device", "未知")
        header = f"跳闸简报 | {station} / {device}\n任务 ID: {job_id}\n"
        header += "=" * 60 + "\n\n"
        footer = f"\n\n---\n如需修改此报告，请使用 trip_briefing_write 工具。只需指定要修改的章节，其余章节自动保留。示例：trip_briefing_write(job_id=\"{job_id}\", section=\"故障基本情况\", content=\"该章节的新内容\")。不要使用 edit_file 或 write_file。"
        return header + content + footer


@tool_parameters(
    tool_parameters_schema(
        job_id=StringSchema("任务 ID（必填）"),
        section=StringSchema("要修改的章节标题关键字（必填），例如：故障基本情况、保护配置情况、动作基本情况"),
        content=StringSchema("该章节的新内容（必填），Markdown 格式，不含 ## 标题行"),
    )
)
class TripBriefingWriteTool(Tool):
    """改写跳闸简报报告的指定章节。只替换目标章节，其余章节保持不变。"""

    @property
    def name(self) -> str:
        return "trip_briefing_write"

    @property
    def description(self) -> str:
        return WRITE_TOOL_DESC

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        job_id = (kwargs.get("job_id") or "").strip()
        section = (kwargs.get("section") or "").strip()
        content = kwargs.get("content") or ""

        if not job_id:
            return "请提供 job_id 参数"
        if not section:
            return "请提供 section 参数（要修改的章节标题关键字）"
        if not content.strip():
            return "请提供 content 参数（该章节的新内容）"

        service = _get_service()
        job = service.get_job(job_id)
        if not job:
            return f"未找到任务 ID 为 '{job_id}' 的跳闸简报"

        report_path = _find_report_file(service.app_root / "jobs" / job_id)
        if not report_path:
            return f"任务 {job_id} 未找到报告文件，无法写入"

        _check_path(report_path)

        try:
            existing = report_path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"读取报告文件失败：{exc}"

        new_full = _replace_section(existing, section, content)
        if new_full is None:
            # 列出可用章节帮助 AI
            import re
            headers = re.findall(r"^## .+", existing, re.MULTILINE)
            header_list = "\n".join(f"  {h}" for h in headers) if headers else "  （无）"
            return f"未找到包含 '{section}' 的章节。可用章节：\n{header_list}"

        try:
            report_path.write_text(new_full, encoding="utf-8")
        except Exception as exc:
            return f"写入报告文件失败：{exc}"

        # 同步更新 .docx
        docx_path = report_path.with_suffix(".docx")
        try:
            from webui.utils.md_to_docx import MdToDocxConverter
            converter = MdToDocxConverter()
            converter.convert(new_full, docx_path)
        except Exception:
            pass

        station = job.get("station", "未知")
        device = job.get("device", "未知")
        return f"跳闸简报「{section}」章节已更新：{station} / {device}（{job_id}）"
