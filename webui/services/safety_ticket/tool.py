"""safety_ticket tools — 二次安措票审查 agent tools。

Tool 1: safety_ticket_review_extract
  输入 .doc/.docx 安措票路径 → 返回票面文本 + 知识库内容，供 agent 审查分析。

Tool 2: safety_ticket_review_generate_report
  输入审查结果 JSON → 生成审查意见书 .docx。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


def _resolve_skill_dir() -> Path:
    """查找 safety-ticket-review skill 目录。"""
    import os
    candidates = [
        Path(os.environ.get("NANOBOT_SKILLS_DIR", "")) / "safety-ticket-review" if os.environ.get("NANOBOT_SKILLS_DIR") else None,
        Path(__file__).parent.parent.parent / "skills" / "safety-ticket-review",
        Path.home() / ".nanobot" / "skills" / "safety-ticket-review",
        Path.cwd() / "skills" / "safety-ticket-review",
    ]
    for d in candidates:
        if d and d.is_dir():
            return d
    raise FileNotFoundError("找不到 skills/safety-ticket-review 目录")


def _extract_docx_text(file_path: str) -> str:
    """从 .docx 提取纯文本（含表格），复用 docx_extract.py 的逻辑。"""
    import zipfile
    from xml.etree import ElementTree as ET

    W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    out = []
    z = zipfile.ZipFile(file_path)
    xml = z.read('word/document.xml')
    root = ET.fromstring(xml)
    body = root.find(W + 'body')

    def text_of(p):
        return ''.join(t.text or '' for t in p.iter(W + 't'))

    for el in body:
        tag = el.tag
        if tag == W + 'p':
            out.append(text_of(el))
        elif tag == W + 'tbl':
            out.append('[TABLE]')
            for tr in el.findall(W + 'tr'):
                cells = []
                for tc in tr.findall(W + 'tc'):
                    cells.append(' '.join(text_of(p) for p in tc.iter(W + 'p')).strip())
                out.append(' | '.join(cells))
            out.append('[/TABLE]')
    return '\n'.join(out)


def _extract_doc_text(file_path: str) -> str:
    """从 .doc 提取纯文本（含表格），复用 converter.py 的逻辑。"""
    import subprocess
    from pathlib import Path

    path = Path(file_path)

    # Try antiword first (fast, accurate for MS Word .doc)
    try:
        result = subprocess.run(
            ["antiword", str(path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            if lines and lines[0].startswith("convert "):
                lines = lines[1:]
            return "\n".join(lines)
    except FileNotFoundError:
        pass  # antiword not installed, fall through

    # Fallback: pure Python OLE2 text extraction (works with WPS .doc)
    return _extract_doc_text_olefile(path)


def _extract_doc_text_olefile(path: Path) -> str:
    """从 .doc 提取纯文本（OLE2 格式）。"""
    import struct
    import re

    try:
        import olefile
    except ImportError:
        raise RuntimeError(
            "antiword 不可用且未安装 olefile。"
            "请安装 antiword 或运行: pip install olefile"
        )

    ole = olefile.OleFileIO(str(path))
    wd = ole.openstream("WordDocument").read()

    wIdent = struct.unpack_from("<H", wd, 0)[0]
    if wIdent != 0xA5EC:
        ole.close()
        raise ValueError(f"不是有效的 Word 文档: {path.name}")

    # Scan WordDocument stream for UTF-16LE encoded text
    results = []
    i = 0x200  # skip FIB header
    current: list[str] = []
    while i < len(wd) - 1:
        char = struct.unpack_from("<H", wd, i)[0]
        if (
            (0x20 <= char <= 0x7E)
            or (0x4E00 <= char <= 0x9FFF)  # CJK Unified
            or (0x3000 <= char <= 0x303F)  # CJK Symbols
            or (0xFF00 <= char <= 0xFFEF)  # Fullwidth Forms
            or char in (0x000A, 0x000D, 0x0009)
        ):
            current.append(chr(char))
        else:
            if len(current) >= 5:
                results.append("".join(current))
            current = []
        i += 2

    if len(current) >= 5:
        results.append("".join(current))

    ole.close()

    text = "\n".join(results)
    # Remove control characters except newline/tab
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text


def _extract_word_text(file_path: str) -> str:
    """从 .doc 或 .docx 提取纯文本（含表格）。"""
    from pathlib import Path
    p = Path(file_path)
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return _extract_docx_text(file_path)
    elif suffix == ".doc":
        return _extract_doc_text(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}")


def _read_references(skill_dir: Path) -> dict[str, str]:
    """读取所有知识库参考文件。"""
    refs = {}
    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for f in sorted(refs_dir.glob("*.md")):
            refs[f.stem] = f.read_text(encoding="utf-8")
    return refs


@tool_parameters(
    tool_parameters_schema(
        filePath=StringSchema("安措票 .doc 或 .docx 文件的绝对路径"),
    )
)
class SafetyTicketReviewExtractTool(Tool):
    """提取安措票文本并读取审查知识库。输入 .doc 或 .docx 文件路径，返回票面文本和审查参考知识库内容。"""

    @property
    def name(self) -> str:
        return "safety_ticket_review_extract"

    @property
    def description(self) -> str:
        return (
            "提取二次安措票 .doc/.docx 文本并读取审查知识库。"
            "输入 .doc 或 .docx 文件绝对路径，返回：1) 安措票全文（含表格）；2) 技术细则第5章；3) 审查要点知识库；4) 人工审查经验补充；5) 审查意见书示例。\n"
            "重要：调用此工具后，你必须在同一轮对话中立即完成以下全部工作，不要中途停下来回复用户：\n"
            "1. 分析返回的票面文本，判定作业类型（检验/改造）和设备类型（主变/母差/线路）\n"
            "2. 对照返回的知识库和审查意见书示例，逐条逐行审查（票面→原始状态→联跳→电流→电压→信号→交直流→过程安措）\n"
            "3. 审查精度要求（必须达到示例同等细致程度）：\n"
            "   - 逐行核对每个端子号是否正确（如A330 vs N330中性线标错）\n"
            "   - 交叉比对不同电压等级的端子号，相同即为复制粘贴错误（如110kV与220kV端子号完全相同）\n"
            "   - 检查端子号正负端标号是否成对对称（如SL102 vs SL103）\n"
            "   - 对照5.2.1~5.2.6逐节检查措施完整性，缺任何一节都必须标注\n"
            "   - 改造类电流回路必须检查端子箱+屏后双点处理\n"
            "   - 断开空开/解线后必须检查是否标注红胶布封挡\n"
            "4. 将问题分为必须整改(M)和建议核实(S)，标注高危项（可能导致误拆/误动运行设备的错误）\n"
            "5. 调用 safety_ticket_review_generate_report 工具生成审查意见书\n"
            "6. 最后将审查结果和报告路径告知用户"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        file_path = (kwargs.get("filePath") or "").strip()
        if not file_path:
            return "错误：请提供安措票 .doc 或 .docx 文件路径(filePath)。"

        p = Path(file_path)
        if not p.exists():
            return f"错误：文件不存在：{file_path}"
        if p.suffix.lower() not in (".doc", ".docx"):
            return f"错误：文件不是 .doc 或 .docx 格式：{p.suffix}"

        try:
            skill_dir = _resolve_skill_dir()

            # 提取票面文本
            ticket_text = _extract_word_text(str(p))
            logger.info("[safety-ticket] 提取票面文本完成，{} 字符", len(ticket_text))

            # 读取知识库
            references = _read_references(skill_dir)
            logger.info("[safety-ticket] 读取知识库 {} 个文件", len(references))

            # 组装结果
            result_parts = [
                "=== 安措票文本 ===",
                f"文件：{p.name}",
                f"字符数：{len(ticket_text)}",
                "",
                ticket_text,
                "",
            ]

            for name, content in references.items():
                result_parts.append(f"=== {name} ===")
                result_parts.append(content)
                result_parts.append("")

            result = "\n".join(result_parts)

            # 截断过长结果（知识库+示例+票面文本可能较长）
            if len(result) > 60000:
                result = result[:60000] + "\n\n... (内容过长，已截断)"

            return result

        except Exception as exc:
            logger.error("[safety-ticket] extract 失败: {}", exc)
            return f"提取失败：{exc}"


@tool_parameters(
    tool_parameters_schema(
        reviewData=StringSchema(
            "审查结果 JSON 字符串，格式：{\"conclusion\": \"结论\", "
            "\"must_fix\": [{\"id\": \"M1\", \"location\": \"位置\", \"desc\": \"问题\", \"basis\": \"依据\", \"suggestion\": \"建议\"}], "
            "\"suggest\": [{\"id\": \"S1\", \"location\": \"位置\", \"desc\": \"问题\", \"suggestion\": \"建议\"}], "
            "\"detail\": [{\"chapter\": \"章节名\", \"issues\": [\"问题1\"], \"pass\": [\"合格1\"]}], "
            "\"stats\": {\"must_fix\": 0, \"suggest\": 0, \"high_risk\": 0}}"
        ),
        outputFile=StringSchema("输出 .docx 文件的绝对路径（可选，默认在源文件同目录生成）"),
        sourceFile=StringSchema("被审安措票原文件名（用于报告封面显示）"),
        deviceInfo=StringSchema("设备/作业类型描述，如：220kV菊江变 2号主变保护装置更换（常规站·主变保护改造）"),
    )
)
class SafetyTicketReviewGenerateReportTool(Tool):
    """根据审查结果 JSON 生成审查意见书 .docx。"""

    @property
    def name(self) -> str:
        return "safety_ticket_review_generate_report"

    @property
    def description(self) -> str:
        return (
            "根据审查结果生成二次安措票审查意见书 .docx。"
            "参数：reviewData(审查结果JSON,必填), outputFile(输出路径,可选), sourceFile(原票文件名,必填), deviceInfo(设备作业类型,必填)。\n"
            "审查分析完成后调用此工具生成正式审查意见书。"
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(self, **kwargs: Any) -> str:
        review_data_str = (kwargs.get("reviewData") or "").strip()
        output_file = (kwargs.get("outputFile") or "").strip()
        source_file = (kwargs.get("sourceFile") or "").strip()
        device_info = (kwargs.get("deviceInfo") or "").strip()

        if not review_data_str:
            return "错误：请提供审查结果 JSON (reviewData)。"
        if not source_file:
            return "错误：请提供被审安措票原文件名(sourceFile)。"
        if not device_info:
            return "错误：请提供设备/作业类型(deviceInfo)。"

        try:
            data = json.loads(review_data_str)
        except json.JSONDecodeError as exc:
            return f"错误：reviewData JSON 格式错误：{exc}"

        try:
            skill_dir = _resolve_skill_dir()
            # 动态导入 docx_helpers
            import sys
            sys.path.insert(0, str(skill_dir / "scripts"))
            from docx_helpers import Doc

            # 确定输出路径
            if not output_file:
                # 如果 source_file 包含目录，输出到同目录；否则输出到 workspace 根目录
                src_path = Path(source_file)
                stem = src_path.stem
                if src_path.parent != Path("."):
                    output_file = str(src_path.parent / f"{stem}_审查意见.docx")
                else:
                    # source_file 只是文件名，尝试找到实际源文件所在目录
                    workspace = Path.home() / ".nanobot" / "workspace"
                    # 搜索源文件实际位置
                    matches = list(workspace.rglob(f"*{stem}*"))
                    if matches:
                        output_file = str(matches[0].parent / f"{stem}_审查意见.docx")
                    else:
                        output_file = str(workspace / f"{stem}_审查意见.docx")

            d = Doc(output_file)

            # 封面
            d.title("继电保护二次安措票\n审 查 意 见 书")
            d.subtitle(f"被审文件：{source_file}")
            d.spacer()

            # 元信息表
            conclusion = data.get("conclusion", "")
            meta_rows = [
                ["被审文件", source_file],
                ["设备/作业类型", device_info],
                ["审查依据", "《220kV常规变电站继电保护安全措施票技术细则》第5章及《常规站二次安措票审查要点》"],
                ["审查结论", conclusion],
            ]
            d.table(header=["项目", "内容"], rows=meta_rows, header_fill="D9E2F3", widths=[3.2, 13.5])

            # 统计
            stats = data.get("stats", {})
            must_count = stats.get("must_fix", 0)
            suggest_count = stats.get("suggest", 0)
            high_risk_count = stats.get("high_risk", 0)
            d.spacer()
            d.p(
                f"问题统计：必须整改 {must_count} 项 ｜ 建议核实 {suggest_count} 项 ｜ 其中高危 {high_risk_count} 项。",
                bold=True, color=(0xC0, 0x00, 0x00),
            )

            # 一、必须整改项
            must_fix = data.get("must_fix", [])
            if must_fix:
                d.h("一、必须整改项（签发前须闭环）", 1)
                rows = [
                    [item.get("id", ""), item.get("location", ""), item.get("desc", ""),
                     item.get("basis", ""), item.get("suggestion", "")]
                    for item in must_fix
                ]
                d.table(
                    header=["编号", "位置/条款", "问题描述", "依据", "整改建议"],
                    rows=rows, header_fill="1F4E79",
                    widths=[1.0, 2.6, 6.0, 2.0, 4.0],
                )

            # 二、建议核实项
            suggest = data.get("suggest", [])
            if suggest:
                d.spacer()
                d.h("二、建议核实项（须对照本站图纸/信息流图确认）", 1)
                rows = [
                    [item.get("id", ""), item.get("location", ""), item.get("desc", ""),
                     item.get("suggestion", "")]
                    for item in suggest
                ]
                d.table(
                    header=["编号", "位置/条款", "问题描述", "核实/建议"],
                    rows=rows, header_fill="2E5C8A",
                    widths=[1.0, 2.8, 7.5, 5.5],
                )

            # 三、逐章审查明细
            detail = data.get("detail", [])
            if detail:
                d.spacer()
                d.h("三、逐章审查明细", 1)
                for chapter in detail:
                    ch_name = chapter.get("chapter", "")
                    d.h(ch_name, 3)
                    for issue in chapter.get("issues", []):
                        d.p(f"■ 问题：{issue}")
                    for ok in chapter.get("pass", []):
                        d.p(f"✓ {ok}")

            # 四、审查结论
            if conclusion:
                d.spacer()
                d.h("四、审查结论", 1)
                d.p(f"结论：{conclusion}", bold=True, color=(0xC0, 0x00, 0x00))

            # 签字表
            d.spacer()
            sign_rows = [
                ["编制自审", "", "", ""],
                ["技术负责人审核", "", "", ""],
                ["签发人签发", "", "", ""],
            ]
            d.table(
                header=["审查岗位", "审查人", "审查日期", "结论"],
                rows=sign_rows, header_fill="D9E2F3",
            )

            d.save()
            abs_path = str(Path(output_file).resolve())
            logger.info("[safety-ticket] 审查意见书已生成: {}", abs_path)
            return (
                f"审查意见书已生成。\n"
                f"文件路径：{abs_path}\n"
                f"请使用 message 工具发送审查结果摘要，并将上述完整文件路径作为 media 参数发送附件。"
            )

        except Exception as exc:
            logger.error("[safety-ticket] generate_report 失败: {}", exc)
            return f"生成审查意见书失败：{exc}"
