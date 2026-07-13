#!/usr/bin/env python3
"""
按子代理输出的章节行号 JSON 切分 markitdown.md 为 3 个子文件。

用法:
    python split_sections.py <markitdown.md> <sections.json> -o <output_dir>

sections.json 格式:
{
  "model": "UDL-531-GCN",
  "overview":     {"start_line": 119, "end_line": 303, "title": "..."},
  "protection":   {"start_line": 304, "end_line": 900, "title": "..."},
  "settings":     {"start_line": 901, "end_line": 1500, "title": "..."}
}
"""

import argparse
import json
import re
import sys
from pathlib import Path


SECTION_MAP = {
    "overview": "概述",
    "protection": "保护原理",
    "settings": "定值说明",
}


def clean_header_footer(lines: list[str]) -> list[str]:
    """删除页眉页脚行（频次>5的完整行 + 前后的页码行）"""
    from collections import Counter

    counts = Counter(l.strip() for l in lines if l.strip())
    # 找出出现>5次且长度>3的行（排除表格分隔符）
    headers = {
        line
        for line, cnt in counts.items()
        if cnt > 5 and len(line) > 3 and not line.startswith("|")
    }

    cleaned = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 跳过页眉行
        if stripped in headers:
            continue
        # 跳过页码行（页眉前一行为纯数字 或 "- N -" 格式）
        if re.match(r"^-?\s*\d+\s*-?$", stripped) and len(stripped) < 8:
            continue
        cleaned.append(line)

    return cleaned


def clean_toc_and_front_matter(lines: list[str], first_chapter_line: int) -> list[str]:
    """删除目录页和封面内容（第一个正文章节之前的目录部分）"""
    # 保留从 first_chapter_line 开始的内容
    return lines[first_chapter_line:]


def main():
    parser = argparse.ArgumentParser(description="按行号切分 markitdown 提取结果")
    parser.add_argument("md_file", help="markitdown.md 文件路径")
    parser.add_argument("json_file", help="章节行号 JSON 文件路径")
    parser.add_argument("-o", "--output-dir", default=".", help="输出目录")
    args = parser.parse_args()

    md_path = Path(args.md_file)
    json_path = Path(args.json_file)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 读取文件（行号1-indexed，转0-indexed）
    all_lines = md_path.read_text(encoding="utf-8").split("\n")

    # 读取 JSON
    sections = json.loads(json_path.read_text(encoding="utf-8"))
    model = sections.get("model", md_path.stem)

    for key, label in SECTION_MAP.items():
        if key not in sections:
            print(f"跳过 {key}（未在 JSON 中定义）")
            continue

        sec = sections[key]
        start = sec["start_line"] - 1  # 转 0-indexed
        end = sec["end_line"]          # 1-indexed end_line，Python切片正好不包含它

        raw_lines = all_lines[start:end]

        # 清理页眉页脚
        cleaned = clean_header_footer(raw_lines)

        # 清理末尾空行
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        # 写文件
        out_name = f"{model}_{label}.md"
        out_path = out_dir / out_name
        out_path.write_text("\n".join(cleaned), encoding="utf-8")

        print(f"  {label}: 行 {sec['start_line']}-{sec['end_line']} → {out_name} ({len(cleaned)} 行)")


if __name__ == "__main__":
    main()
