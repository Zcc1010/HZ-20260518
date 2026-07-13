#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保护说明书 PDF 结构化知识库提取脚本

从保护装置说明书 PDF 中提取结构化知识库：
1. 双源提取 (markitdown + PaddleOCR 并行)
2. 章节边界检测
3. 图片编目与分类
4. VLM 批处理 (可选)
5. 清单生成

用法:
    uv run python .claude/skills/setting-check/scripts/extract_manual.py <pdf_path> [--skip-vlm] [--vlm-model <model>]
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# ============ 配置 ============

VLM_CANDIDATE_KEYWORDS = [
    "逻辑框图", "保护逻辑", "动作逻辑", "跳闸逻辑",
    "比率差动", "比率制动", "差动保护", "距离保护",
    "CT断线", "PT断线", "零序保护", "过流保护",
    "复合电压", "电压闭锁", "谐波制动", "波形识别",
    "跳闸矩阵", "出口矩阵", "启动元件", "重合闸",
    "继电保护", "保护投退", "控制字", "软压板", "硬压板",
    "动作特性", "特性曲线", "阻抗元件", "方向元件",
]

# 章节号 -> 输出 section 映射
CHAPTER_SECTION_MAP = {
    1: "overview",
    2: "overview",
    3: "protection",
    5: "settings",
}

SECTION_FILENAMES = {
    "overview": "概述.md",
    "protection": "保护原理.md",
    "settings": "定值说明.md",
}

VLM_PROMPT_TEMPLATE = """这是来自 {model_name} 保护说明书的 {image_type}。

上下文信息：
{context}

请将此图片转换为详细的文本描述，包括：
1. 所有标注的数值、参数、坐标值
2. 动作边界和区域的数学定义
3. 坐标轴含义和刻度范围
4. 关键逻辑分支和判断条件（如果是逻辑流程图）
5. 曲线函数关系（如果是特性曲线）"""


# ============ 工具函数 ============

def log(msg: str):
    """打印日志到 stderr"""
    print(f"[extract-manual] {msg}", file=sys.stderr)


def find_project_root() -> Path:
    """从 cwd 向上查找包含 .claude 目录的根目录"""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / ".claude").exists():
            return parent
    return current


def extract_model_name(pdf_path: Path) -> str:
    """从 PDF 文件名提取型号前缀

    规则: 南瑞继保 PCS 系列提取基础型号+变体后缀，
    其他按实际情况处理，确保不同文件不互相覆盖。
    """
    stem = pdf_path.stem

    # ===== PCS 系列处理 =====
    if stem.startswith("PCS-"):
        # 提取第一段（下划线分隔），如 "PCS-978T5-G(G9)_X_..." -> "PCS-978T5-G(G9)"
        first_seg = stem.split("_")[0]

        # 匹配: 基础型号 + 可选变体后缀
        # 后缀包括: -G, -G(G9), -DA, -DA(FA), -DG, -DG(G9), -D, -(FA) 等
        m = re.match(r"^(PCS-\d+[A-Z]*)(-[A-Z]+(?:[A-Z()]*))?(-\d+)?$", first_seg)
        if m:
            base = m.group(1)          # e.g. PCS-978T5
            suffix1 = m.group(2) or ""  # e.g. -G(G9)
            return base + suffix1

        # Fallback: 取第一段
        return first_seg

    # ===== NSR 系列: 提取型号编号 =====
    if stem.startswith("NSR-"):
        # 匹配 NSR-数字+字母数字型号编号 (允许字母+数字组合，如 T2, DA, 302G)
        m = re.match(r"^(NSR-\d+[A-Za-z0-9^()]+)", stem)
        if m:
            return m.group(1)

    # ===== PRINT_CSC-* 文件 (北京四方打印版): 提取 CSC 型号 =====
    stripped = stem
    if stripped.startswith("PRINT"):
        # 循环去掉 PRINT_ 或 PRINT__ 前缀（可能有多余下划线）
        while True:
            matched = False
            for prefix in ["PRINT__", "PRINT_"]:
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):]
                    matched = True
                    break
            if not matched:
                break
        # 现在 stripped 应以 CSC- 开头
        if stripped.startswith("CSC-"):
            m = re.match(r"^(CSC-\d+[A-Za-z]*)", stripped)
            if m:
                return m.group(1)

    # ===== SG B750 系列 (国电南自): 处理空格分隔 =====
    # 匹配: SG B750, SGB-750, SG-B750, SG B750母差... 等多种写法
    m = re.search(r"SG[B]?\s*[-]?\s*B\s*75[01]", stem, re.IGNORECASE)
    if m:
        found = m.group(0).upper().replace(" ", "").replace("-", "")
        # 统一为 SGB-750 格式
        if found.startswith("SGB"):
            return found[:3] + "-" + found[3:] if "-" not in found else found
        return "SGB-" + found.lstrip("SG")

    # ===== 国电南自 / 许继 / 长圆深瑞 等: 取第一段下划线或减号前的内容 =====
    for sep in ["_", "-"]:
        if sep in stem:
            return stem.split(sep)[0]
    return stem


# ============ 1. 双源提取 ============

def run_markitdown(pdf_path: Path, output_path: Path) -> dict:
    """使用 markitdown 提取 PDF 文本"""
    try:
        from markitdown import MarkItDown

        md = MarkItDown()
        result = md.convert(str(pdf_path))
        text = result.text_content or ""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")

        return {"path": str(output_path), "chars": len(text), "status": "ok"}
    except Exception as e:
        log(f"markitdown 失败: {e}")
        return {"path": str(output_path), "chars": 0, "status": "failed", "error": str(e)}


def convert_to_pdf(doc_path: Path) -> Path | None:
    """使用 win32com 将 DOC/DOCX 转换为 PDF，返回 PDF 路径"""
    try:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            import win32com.client
            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            doc = word.Documents.Open(str(doc_path.resolve()), ConfirmConversions=False)
            pdf_path = doc_path.with_suffix(".pdf")
            doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)  # wdFormatPDF = 17
            doc.Close(False)
            word.Quit()
            log(f"DOC→PDF 转换成功: {pdf_path.name}")
            return pdf_path
        finally:
            pythoncom.CoUninitialize()
    except Exception as e:
        log(f"DOC→PDF 转换失败: {e}")
        return None


def run_paddleocr(pdf_path: Path, output_md_path: Path, images_dir: Path) -> dict:
    """调用 paddleocr.py 脚本进行版面解析"""
    try:
        paddleocr_script = Path.home() / ".claude/skills/doc-to-md/scripts/paddleocr.py"
        if not paddleocr_script.exists():
            return {
                "path": str(output_md_path),
                "chars": 0,
                "status": "failed",
                "error": f"paddleocr.py not found: {paddleocr_script}",
            }

        # DOC/DOCX 需要先转 PDF
        actual_pdf_path = pdf_path
        temp_pdf_created = False
        if pdf_path.suffix.lower() in [".doc", ".docx"]:
            converted = convert_to_pdf(pdf_path)
            if converted and converted.exists():
                actual_pdf_path = converted
                temp_pdf_created = True
            else:
                return {
                    "path": str(output_md_path),
                    "chars": 0,
                    "status": "failed",
                    "error": "DOC转PDF失败，PaddleOCR无法处理",
                }

        result = subprocess.run(
            [sys.executable, str(paddleocr_script), str(actual_pdf_path),
             "-o", str(output_md_path), "--keep-images"],
            capture_output=True,
            timeout=600,
        )

        # 清理临时 PDF
        if temp_pdf_created:
            try:
                actual_pdf_path.unlink()
            except Exception:
                pass

        if result.returncode != 0:
            stderr_text = result.stderr.decode("utf-8", errors="replace")[:300]
            log(f"PaddleOCR 脚本返回非零: {stderr_text[:200]}")
            return {
                "path": str(output_md_path),
                "chars": 0,
                "status": "failed",
                "error": stderr_text,
            }

        # 读取输出
        text = ""
        if output_md_path.exists():
            text = output_md_path.read_text(encoding="utf-8")

        # 统计图片数量
        img_count = 0
        if images_dir.exists():
            for jpg in images_dir.rglob("*.jpg"):
                img_count += 1

        return {
            "path": str(output_md_path),
            "chars": len(text),
            "status": "ok",
            "images_dir": str(images_dir),
            "images_count": img_count,
        }
    except subprocess.TimeoutExpired:
        log("PaddleOCR 超时")
        return {"path": str(output_md_path), "chars": 0, "status": "failed", "error": "timeout"}
    except Exception as e:
        log(f"PaddleOCR 异常: {e}")
        return {"path": str(output_md_path), "chars": 0, "status": "failed", "error": str(e)}


def dual_extract(pdf_path: Path, model_name: str, temp_dir: Path) -> dict:
    """并行执行 markitdown 和 PaddleOCR"""
    md_output = temp_dir / f"{model_name}_markitdown.md"
    ocr_output = temp_dir / f"{model_name}_paddleocr.md"
    ocr_images = temp_dir / f"{model_name}_paddleocr_images"

    log("双源提取中...")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_md = executor.submit(run_markitdown, pdf_path, md_output)
        future_ocr = executor.submit(run_paddleocr, pdf_path, ocr_output, ocr_images)

        md_result = future_md.result()
        ocr_result = future_ocr.result()

    # 日志
    if md_result["status"] == "ok":
        log(f"markitdown: 完成 ({md_result['chars']} 字符)")
    else:
        log(f"markitdown: 失败 ({md_result.get('error', 'unknown')})")

    if ocr_result["status"] == "ok":
        log(f"PaddleOCR: 完成 ({ocr_result['chars']} 字符, {ocr_result.get('images_count', 0)} 图片)")
    else:
        log(f"PaddleOCR: 失败 ({ocr_result.get('error', 'unknown')})")

    return {"markitdown": md_result, "paddleocr": ocr_result}


# ============ 2. 章节边界检测 ============

def detect_chapters(md_text: str) -> list[dict]:
    """
    扫描 markitdown 输出检测章节边界。

    匹配模式: 行首出现 '第N章 标题' (不在目录中，即后面不跟 .... 和页码)
    """
    lines = md_text.split("\n")

    # 候选行: 匹配两种格式:
    #   格式1: "第N章 标题" (如 "第1章 概述", "第 1  章 保护原理")
    #   格式2: "N  标题" (如 "1  概述", "3  保护原理") - 无"第"/"章"
    chapter_pattern = re.compile(r"^#{0,3}\s*(?:第\s*)?(\d+)\s*(?:章\s+)?(.+)")
    # 目录行特征: 同一行内有点号+页码 (如 '第1章 概述 ......... 5')
    toc_pattern = re.compile(r"\.{3,}\s*\d+\s*$")

    candidates = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        m = chapter_pattern.match(stripped)
        if m:
            # 检查是否在目录中 (后面跟 .... 和页码)
            if toc_pattern.search(stripped):
                continue
            ch_num = int(m.group(1))
            ch_title = m.group(2).strip()
            candidates.append({"line": i, "num": ch_num, "title": f"第{ch_num}章 {ch_title}"})

    if not candidates:
        log("章节检测: 未找到章节标题")
        return []

    # 去重: 同一章号可能多次出现 (页眉/页脚), 保留第一个作为章节开始
    seen = set()
    unique = []
    for c in candidates:
        if c["num"] not in seen:
            seen.add(c["num"])
            unique.append(c)

    # 计算 end_line
    chapters = []
    for idx, c in enumerate(unique):
        start_line = c["line"]
        if idx + 1 < len(unique):
            end_line = unique[idx + 1]["line"] - 1
        else:
            end_line = len(lines) - 1

        ch_num = c["num"]
        section = CHAPTER_SECTION_MAP.get(ch_num, "null")

        chapters.append({
            "idx": len(chapters),
            "title": c["title"],
            "start_line": start_line,
            "end_line": end_line,
            "chapter_num": ch_num,
            "section": section,
        })

    log(f"章节检测: {len(chapters)} 章")
    return chapters


# ============ 3. 图片编目与分类 ============

def catalog_images(
    ocr_images_dir: Path,
    ocr_md_text: str,
    chapters: list[dict],
    md_lines: list[str],
) -> list[dict]:
    """
    扫描 PaddleOCR 输出图片，编目并分类。

    返回图片列表，每个图片包含:
    - path, page, type (vlm_candidate / general),
    - figure_label, context_snippet, chapter_idx
    """
    if not ocr_images_dir.exists():
        log("图片编目: 图片目录不存在")
        return []

    # 1. 收集所有 jpg 文件
    all_images = []
    for jpg in sorted(ocr_images_dir.rglob("*.jpg")):
        # 从路径提取 page index: page_N/imgs/xxx.jpg
        page_match = re.search(r"page_(\d+)", str(jpg))
        page = int(page_match.group(1)) if page_match else -1
        all_images.append({"path": str(jpg), "page": page, "filename": jpg.name})

    if not all_images:
        log("图片编目: 未找到图片文件")
        return []

    # 2. 从 PaddleOCR markdown 中提取图片引用及上下文
    img_ref_pattern = re.compile(r"(img_in_\w+_\d+_\d+_\d+_\d+\.jpg)")
    lines = ocr_md_text.split("\n")

    # 建立 filename -> context 的映射
    # 上下文包括: 当前行 + 前后各 5 行 (共 ~11 行)
    CONTEXT_LINE_RANGE = 5
    img_contexts: dict[str, str] = {}
    for i, line in enumerate(lines):
        for m in img_ref_pattern.finditer(line):
            fname = m.group(1)
            # 收集前后多行的文本作为上下文
            ctx_start = max(0, i - CONTEXT_LINE_RANGE)
            ctx_end = min(len(lines), i + CONTEXT_LINE_RANGE + 1)
            context_lines = lines[ctx_start:ctx_end]
            context = " ".join(context_lines)
            # 清理 HTML 标签和图片引用
            context = re.sub(r"<[^>]+>", " ", context)
            context = re.sub(r"img_in_\w+_\d+_\d+_\d+_\d+\.jpg", " ", context)
            context = re.sub(r"\s+", " ", context).strip()
            # 截取 500 字符
            context = context[:500]
            if fname not in img_contexts:
                img_contexts[fname] = context

    # 3. 为每张图片分类
    results = []
    vlm_count = 0

    # 构建章节到行号的映射 (用于 page -> chapter 的近似映射)
    # 使用 markitdown 行数估计 page -> line 的关系
    total_md_lines = len(md_lines)

    for img_info in all_images:
        fname = img_info["filename"]
        page = img_info["page"]
        context = img_contexts.get(fname, "")

        # 跳过 header 图片 (页面头部 logo 类小图)
        if "header_image" in fname:
            continue

        # 分类: 检查上下文中是否包含 VLM 候选关键词
        is_vlm_candidate = False
        for kw in VLM_CANDIDATE_KEYWORDS:
            if kw in context:
                is_vlm_candidate = True
                break

        img_type = "vlm_candidate" if is_vlm_candidate else "general"
        if is_vlm_candidate:
            vlm_count += 1

        # 提取图号标签 (允许 "图" 后有空格, 如 "图 3.10-1")
        figure_label = ""
        label_match = re.search(r"图\s*\d+\.\d+(?:-\d+)?", context)
        if label_match:
            figure_label = label_match.group(0).replace(" ", "")

        # 映射到章节 (基于 page 近似)
        chapter_idx = _map_page_to_chapter(page, chapters, md_lines, ocr_md_text)

        results.append({
            "path": img_info["path"],
            "page": page,
            "type": img_type,
            "figure_label": figure_label,
            "context_snippet": context[:300] if context else "",
            "chapter_idx": chapter_idx,
        })

    log(f"图片编目: {len(all_images)} 图片, {vlm_count} VLM候选")
    return results


def _map_page_to_chapter(
    page: int,
    chapters: list[dict],
    md_lines: list[str],
    ocr_md_text: str = "",
) -> int:
    """
    基于 page index 近似映射到章节。

    策略: 在 PaddleOCR markdown 中查找每个章节标题的首次出现位置,
    以该行号为分界点。然后找到图片引用在 PaddleOCR markdown 中的行号。
    """
    if not chapters or page < 0:
        return -1

    # 如果没有 PaddleOCR 文本, fallback 到 markitdown 估算
    if not ocr_md_text:
        return _map_page_to_chapter_fallback(page, chapters, md_lines)

    ocr_lines = ocr_md_text.split("\n")

    # 在 PaddleOCR markdown 中查找章节标题
    chapter_pattern = re.compile(r"第(\d+)章\s+(.+)")
    toc_pattern = re.compile(r"\.{3,}\s*\d+\s*$")

    # 记录每个章节号在 PaddleOCR 中的首次出现行号
    ocr_chapter_lines: dict[int, int] = {}
    seen_ch = set()
    for i, line in enumerate(ocr_lines):
        m = chapter_pattern.search(line)
        if m and not toc_pattern.search(line):
            ch_num = int(m.group(1))
            if ch_num not in seen_ch:
                seen_ch.add(ch_num)
                ocr_chapter_lines[ch_num] = i

    if not ocr_chapter_lines:
        return _map_page_to_chapter_fallback(page, chapters, md_lines)

    # 查找此 page 的图片引用在 ocr_lines 中的行号
    # 扫描包含 page_N/imgs/ 的行
    page_ref = f"page_{page}/"
    img_line_in_ocr = -1
    for i, line in enumerate(ocr_lines):
        if page_ref in line and "img_in_" in line and "header" not in line:
            img_line_in_ocr = i
            break

    if img_line_in_ocr < 0:
        # 尝试更宽泛的搜索
        for i, line in enumerate(ocr_lines):
            if page_ref in line:
                img_line_in_ocr = i
                break

    if img_line_in_ocr < 0:
        return -1

    # 根据 img_line_in_ocr 落在哪两个章节边界之间确定章节
    sorted_ch_nums = sorted(ocr_chapter_lines.keys())
    matched_ch_num = -1
    for idx, ch_num in enumerate(sorted_ch_nums):
        ch_start = ocr_chapter_lines[ch_num]
        if img_line_in_ocr >= ch_start:
            matched_ch_num = ch_num
        else:
            break

    if matched_ch_num < 0:
        return -1

    # 找到 chapters 列表中对应 chapter_num 的 idx
    for ch in chapters:
        if ch["chapter_num"] == matched_ch_num:
            return ch["idx"]

    return -1


def _map_page_to_chapter_fallback(page: int, chapters: list[dict], md_lines: list[str]) -> int:
    """Fallback: 基于 markitdown 行数估算 page -> chapter"""
    if not chapters or page < 0:
        return -1

    total_lines = len(md_lines)
    if total_lines == 0:
        return -1

    est_lines_per_page = max(total_lines / max(page + 1, 1), 10)
    est_line = int(page * est_lines_per_page)

    for ch in chapters:
        if ch["start_line"] <= est_line <= ch["end_line"]:
            return ch["idx"]

    if chapters and est_line > chapters[-1]["end_line"]:
        return chapters[-1]["idx"]

    return -1


# ============ 4. VLM 批处理 ============

def detect_vlm_backend(cli_model: str = None) -> tuple[str | None, str | None, str | None, str | None]:
    """
    检测 VLM 后端，优先级:
    1. 环境变量 VLM_API_KEY + VLM_API_BASE + VLM_MODEL
    2. ~/.claude.json 中 MiniMax MCP 配置 (MINIMAX_API_KEY + MINIMAX_API_HOST)
    3. ~/.nanobot/config.json 的 providers.dashscope
    """
    # 1. 环境变量
    api_key = os.getenv("VLM_API_KEY")
    api_base = os.getenv("VLM_API_BASE")
    model = cli_model or os.getenv("VLM_MODEL")

    if api_key and api_base:
        if not model:
            model = "qwen-vl-max"
        return "env", api_key, api_base, model

    # 2. MiniMax MCP 配置 (~/.claude.json)
    # 配置可能在顶层 mcpServers 或 projects.<path>.mcpServers 下
    claude_config_path = Path.home() / ".claude.json"
    if claude_config_path.exists():
        try:
            config = json.loads(claude_config_path.read_text(encoding="utf-8"))
            # 搜索所有可能的位置
            minimax_env = None
            # 顶层
            top_mm = config.get("mcpServers", {}).get("MiniMax", {}).get("env", {})
            if top_mm.get("MINIMAX_API_KEY"):
                minimax_env = top_mm
            # projects 下
            if not minimax_env:
                for proj_cfg in config.get("projects", {}).values():
                    proj_mm = proj_cfg.get("mcpServers", {}).get("MiniMax", {}).get("env", {})
                    if proj_mm.get("MINIMAX_API_KEY"):
                        minimax_env = proj_mm
                        break
            if minimax_env:
                mm_key = minimax_env["MINIMAX_API_KEY"]
                mm_host = minimax_env.get("MINIMAX_API_HOST", "https://api.minimaxi.com")
                return "minimax-mcp", mm_key, mm_host, "minimax-vlm"
        except Exception:
            pass

    # 3. nanobot config (dashscope / zhipu)
    config_path = Path.home() / ".nanobot" / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            providers = config.get("providers", {})

            ds = providers.get("dashscope", {})
            if ds.get("apiKey"):
                api_key = ds["apiKey"]
                api_base = ds.get("apiBase", "https://dashscope.aliyuncs.com/compatible-mode/v1")
                model = cli_model or os.getenv("VLM_MODEL", "qwen-vl-max")
                return "nanobot-dashscope", api_key, api_base, model

            zhipu = providers.get("zhipu", {})
            if zhipu.get("apiKey"):
                api_key = zhipu["apiKey"]
                api_base = zhipu.get("apiBase", "https://open.bigmodel.cn/api/paas/v4")
                model = cli_model or os.getenv("VLM_MODEL", "GLM-4.6V-Flash")
                return "nanobot-zhipu", api_key, api_base, model
        except Exception:
            pass

    return None, None, None, None


def vlm_analyze_image(
    backend: str,
    api_base: str,
    api_key: str,
    model: str,
    img_path: str,
    model_name: str,
    context: str,
    figure_label: str,
) -> str:
    """调用 VLM API 分析单张图片，返回文本描述"""
    img_bytes = Path(img_path).read_bytes()
    b64 = base64.b64encode(img_bytes).decode()

    # 构建图片类型描述
    image_type = "图片"
    if figure_label:
        image_type = f"图片 ({figure_label})"

    prompt = VLM_PROMPT_TEMPLATE.format(
        model_name=model_name,
        image_type=image_type,
        context=context[:500] if context else "(无上下文信息)",
    )

    if backend == "minimax-mcp":
        # MiniMax /v1/coding_plan/vlm 接口
        url = f"{api_base.rstrip('/')}/v1/coding_plan/vlm"
        payload = {
            "prompt": prompt,
            "image_url": f"data:image/jpeg;base64,{b64}",
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
    else:
        # OpenAI 兼容接口 (dashscope / zhipu / env)
        url = f"{api_base.rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
            "max_tokens": 4096,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
        if backend == "minimax-mcp":
            # MiniMax 返回格式: {"content": "...", "base_resp": {...}}
            if "content" in result:
                return result["content"]
            if "text" in result:
                return result["text"]
            if "choices" in result:
                return result["choices"][0]["message"]["content"]
            return json.dumps(result, ensure_ascii=False)
        else:
            return result["choices"][0]["message"]["content"]


def vlm_batch_process(
    images: list[dict],
    model_name: str,
    cache_path: Path,
    skip_vlm: bool,
    cli_model: str = None,
) -> tuple[list[dict], dict]:
    """
    VLM 批处理: 对 vlm_candidate 图片调用 VLM API。

    返回 (更新后的图片列表, VLM 统计信息)
    """
    vlm_stats = {"total_candidates": 0, "processed": 0, "failed": 0, "skipped": 0}

    candidates = [img for img in images if img["type"] == "vlm_candidate"]
    vlm_stats["total_candidates"] = len(candidates)

    if skip_vlm or not candidates:
        if skip_vlm:
            vlm_stats["skipped"] = len(candidates)
        for img in images:
            if img["type"] == "vlm_candidate":
                img["vlm_status"] = "skipped" if skip_vlm else "pending"
                img["vlm_description"] = ""
        return images, vlm_stats

    # 检测后端
    backend, api_key, api_base, model = detect_vlm_backend(cli_model)
    if not backend:
        log("VLM: 无可用后端, 跳过")
        vlm_stats["skipped"] = len(candidates)
        for img in images:
            if img["type"] == "vlm_candidate":
                img["vlm_status"] = "no_backend"
                img["vlm_description"] = ""
        return images, vlm_stats

    log(f"VLM 使用 {backend} ({model})")

    # 加载缓存
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    # 处理每个候选
    processed = 0
    for img in images:
        if img["type"] != "vlm_candidate":
            continue

        img_key = Path(img["path"]).name

        # 检查缓存
        if img_key in cache and cache[img_key].get("status") == "success":
            img["vlm_description"] = cache[img_key]["description"]
            img["vlm_status"] = "cached"
            vlm_stats["processed"] += 1
            continue

        processed += 1
        label = img.get("figure_label", img_key[:40])
        log(f"VLM批处理: [{processed}/{vlm_stats['total_candidates']}] {label}...")

        try:
            description = vlm_analyze_image(
                backend=backend,
                api_base=api_base,
                api_key=api_key,
                model=model,
                img_path=img["path"],
                model_name=model_name,
                context=img.get("context_snippet", ""),
                figure_label=img.get("figure_label", ""),
            )
            img["vlm_description"] = description
            img["vlm_status"] = "success"
            vlm_stats["processed"] += 1

            # 更新缓存
            cache[img_key] = {"status": "success", "description": description}

        except Exception as e:
            log(f"VLM 失败 ({img_key}): {e}")
            img["vlm_description"] = ""
            img["vlm_status"] = "failed"
            vlm_stats["failed"] += 1

            cache[img_key] = {"status": "failed", "error": str(e)}

        # 保存缓存 (每张图后保存, 支持中断恢复)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        # 限速
        time.sleep(1)

    return images, vlm_stats


# ============ 5. 清单生成 ============

def build_output_mapping(chapters: list[dict]) -> dict:
    """根据章节列表构建输出映射"""
    mapping = {}
    for ch in chapters:
        section = ch["section"]
        if section == "null":
            continue
        if section not in mapping:
            mapping[section] = {
                "chapters": [],
                "filename": SECTION_FILENAMES.get(section, f"{section}.md"),
            }
        mapping[section]["chapters"].append(ch["idx"])
    return mapping


def generate_manifest(
    model_name: str,
    pdf_path: Path,
    sources: dict,
    chapters: list[dict],
    images: list[dict],
    vlm_stats: dict,
) -> dict:
    """生成 manifest.json"""
    output_mapping = build_output_mapping(chapters)

    # 清理 images 中的 chapter_idx 引用, 保持 manifest 简洁
    clean_images = []
    for img in images:
        clean_img = {
            "path": img["path"],
            "page": img["page"],
            "type": img["type"],
        }
        if img.get("figure_label"):
            clean_img["figure_label"] = img["figure_label"]
        if img.get("context_snippet"):
            clean_img["context_snippet"] = img["context_snippet"][:200]
        if img.get("chapter_idx", -1) >= 0:
            clean_img["chapter_idx"] = img["chapter_idx"]
        if img.get("vlm_description"):
            clean_img["vlm_description"] = img["vlm_description"]
        if img.get("vlm_status"):
            clean_img["vlm_status"] = img["vlm_status"]
        clean_images.append(clean_img)

    manifest = {
        "model": model_name,
        "pdf_path": str(pdf_path.resolve()),
        "timestamp": datetime.now().isoformat(),
        "sources": sources,
        "chapters": [
            {
                "idx": ch["idx"],
                "title": ch["title"],
                "start_line": ch["start_line"],
                "end_line": ch["end_line"],
                "section": ch["section"],
            }
            for ch in chapters
        ],
        "output_mapping": output_mapping,
        "images": clean_images,
        "vlm_stats": vlm_stats,
    }
    return manifest


# ============ 主流程 ============

def main():
    parser = argparse.ArgumentParser(
        description="保护说明书 PDF 结构化知识库提取",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("pdf_path", help="PDF 文件路径")
    parser.add_argument("--skip-vlm", action="store_true", help="跳过 VLM 图片分析")
    parser.add_argument("--vlm-model", default=None, help="VLM 模型名称")
    args = parser.parse_args()

    pdf_path = Path(args.pdf_path)
    if not pdf_path.exists():
        print(f"错误: 文件不存在: {pdf_path}", file=sys.stderr)
        sys.exit(1)
    if pdf_path.suffix.lower() not in [".pdf", ".docx", ".doc"]:
        print(f"错误: 不支持的文件类型: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # 1. 项目根目录
    project_root = find_project_root()
    temp_dir = project_root / "output" / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 2. 型号名称
    model_name = extract_model_name(pdf_path)
    log(f"型号: {model_name}")

    # 3. 双源提取
    sources = dual_extract(pdf_path, model_name, temp_dir)

    # 4. 章节边界检测 (基于 markitdown)
    md_text = ""
    md_path = Path(sources["markitdown"]["path"])
    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")

    chapters = detect_chapters(md_text)

    # 5. 图片编目与分类
    ocr_md_text = ""
    ocr_md_path = Path(sources["paddleocr"]["path"])
    if ocr_md_path.exists():
        ocr_md_text = ocr_md_path.read_text(encoding="utf-8")

    ocr_images_dir = temp_dir / f"{model_name}_paddleocr_images"
    md_lines = md_text.split("\n") if md_text else []

    images = catalog_images(ocr_images_dir, ocr_md_text, chapters, md_lines)

    # 6. VLM 批处理
    vlm_cache_path = temp_dir / f"{model_name}_vlm_cache.json"
    images, vlm_stats = vlm_batch_process(
        images=images,
        model_name=model_name,
        cache_path=vlm_cache_path,
        skip_vlm=args.skip_vlm,
        cli_model=args.vlm_model,
    )

    # 7. 清单生成
    manifest = generate_manifest(
        model_name=model_name,
        pdf_path=pdf_path,
        sources=sources,
        chapters=chapters,
        images=images,
        vlm_stats=vlm_stats,
    )

    manifest_path = temp_dir / f"{model_name}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    log(f"完成! 清单: {manifest_path}")


if __name__ == "__main__":
    main()
