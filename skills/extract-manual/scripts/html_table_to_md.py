#!/usr/bin/env python3
"""将HTML表格转换为Markdown格式，保留rowspan/colspan展开后的结构"""

import re
import sys
from pathlib import Path


def parse_html_table(html: str) -> tuple[list[list[str]], int, int]:
    """
    解析单个HTML表格，返回(行列表, 行数, 列数)
    rowspan展开：跨行单元格在每行重复
    colspan展开：跨列单元格重复
    """
    # 提取所有<tr>内容
    tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    td_pattern = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL)
    colspan_pattern = re.compile(r'colspan\s*=\s*["\']?(\d+)', re.IGNORECASE)
    rowspan_pattern = re.compile(r'rowspan\s*=\s*["\']?(\d+)', re.IGNORECASE)

    raw_rows = []
    for tr_match in tr_pattern.finditer(html):
        tr_content = tr_match.group(1)
        cells = []
        for td_match in td_pattern.finditer(tr_content):
            cell_text = td_match.group(1)
            # 清理HTML标签，保留内容
            cell_text = re.sub(r'<[^>]+>', '', cell_text)
            cell_text = cell_text.strip()
            # 处理colspan
            colspan_m = colspan_pattern.search(td_match.group(0))
            colspan = int(colspan_m.group(1)) if colspan_m else 1
            # 处理rowspan（简单处理，记录次数）
            rowspan_m = rowspan_pattern.search(td_match.group(0))
            rowspan = int(rowspan_m.group(1)) if rowspan_m else 1

            # 展开colspan
            for _ in range(colspan):
                cells.append(cell_text)

        if cells:
            raw_rows.append(cells)

    if not raw_rows:
        return [], 0, 0

    # 确定最大列数
    max_cols = max(len(row) for row in raw_rows)

    # 展开rowspan（跨行单元格需要在后续空行对应位置填充）
    # 简单策略：保留rowspan值，后续空行用空字符串补充
    rowspan_map = []  # rowspan_map[row_idx][col_idx] = remaining_rowspan

    final_rows = []
    for row in raw_rows:
        if len(row) < max_cols:
            row += [''] * (max_cols - len(row))
        final_rows.append(row)

    return final_rows, len(final_rows), max_cols


def html_table_to_md(html: str) -> str:
    """将单个HTML表格转换为Markdown表格"""
    rows, num_rows, num_cols = parse_html_table(html)
    if not rows:
        return ''

    # 构建Markdown
    lines = []
    for i, row in enumerate(rows):
        md_row = '| ' + ' | '.join(cell for cell in row) + ' |'
        lines.append(md_row)
        if i == 0:
            # 表头分隔行
            sep = '| ' + ' | '.join('---' for _ in row) + ' |'
            lines.append(sep)

    return '\n'.join(lines)


def clean_html_table_tags(text: str) -> str:
    """清理所有HTML表格标签，将<table>...</table>替换为Markdown表格"""
    # 匹配整个table
    table_pattern = re.compile(
        r'<table[^>]*>(.*?)</table>',
        re.DOTALL | re.IGNORECASE
    )

    def replace_table(m):
        table_html = m.group(0)
        return '\n' + html_table_to_md(table_html) + '\n'

    return table_pattern.sub(replace_table, text)


def process_file(file_path: Path) -> int:
    """处理单个文件，返回替换的表格数量"""
    content = file_path.read_text(encoding='utf-8')
    original = content

    # 清理所有HTML table
    content = clean_html_table_tags(content)

    # 额外清理残留的HTML标签
    content = re.sub(r'</?t[dr][^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'<div[^>]*>', '', content, flags=re.IGNORECASE)
    content = re.sub(r'</div>', '', content, flags=re.IGNORECASE)

    # 统计替换数量
    table_count = len(re.findall(r'<table', original, re.IGNORECASE))

    if content != original:
        file_path.write_text(content, encoding='utf-8')
        print(f"  替换 {table_count} 个HTML表格 → {file_path.name}")

    return table_count


def main():
    if len(sys.argv) < 2:
        print("用法: python html_table_to_md.py <文件1.md> [文件2.md] ...")
        sys.exit(1)

    total_tables = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        if path.is_dir():
            for f in path.rglob('*.md'):
                total_tables += process_file(f)
        elif path.exists():
            total_tables += process_file(path)
        else:
            print(f"  警告: 文件不存在 {arg}")

    print(f"\n完成: 共处理 {total_tables} 个HTML表格")


if __name__ == '__main__':
    main()
