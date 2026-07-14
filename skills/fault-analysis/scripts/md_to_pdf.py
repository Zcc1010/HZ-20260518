# -*- coding: utf-8 -*-
"""
将Markdown文件转换为PDF(支持中文)
使用 reportlab + SimHei 字体
"""
import sys
import io
import re
from pathlib import Path

# 设置stdout为UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
)


# 注册中文字体
def register_chinese_font():
    """注册 SimHei 字体"""
    font_path = r'C:\Windows\Fonts\simhei.ttf'
    try:
        pdfmetrics.registerFont(TTFont('SimHei', font_path))
        return 'SimHei'
    except Exception as e:
        print(f'字体注册失败: {e}', file=sys.stderr)
        return 'Helvetica'


def parse_markdown_table(lines, start_idx):
    """解析Markdown表格,返回(rows, next_idx)"""
    rows = []
    i = start_idx
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith('|'):
            break
        if re.match(r'^\|[\s\-:|]+\|$', line):
            i += 1
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        rows.append(cells)
        i += 1
    return rows, i


def md_to_pdf_elements(md_text, font_name):
    """将Markdown文本转换为reportlab元素列表"""
    styles = getSampleStyleSheet()

    # 标题样式
    h1_style = ParagraphStyle('H1', parent=styles['Heading1'],
                              fontName=font_name, fontSize=20, leading=26,
                              textColor=colors.HexColor('#1a1a1a'),
                              spaceAfter=14, spaceBefore=6, alignment=TA_CENTER)
    h2_style = ParagraphStyle('H2', parent=styles['Heading2'],
                              fontName=font_name, fontSize=15, leading=20,
                              textColor=colors.HexColor('#2c3e50'),
                              spaceAfter=10, spaceBefore=12)
    h3_style = ParagraphStyle('H3', parent=styles['Heading3'],
                              fontName=font_name, fontSize=12, leading=16,
                              textColor=colors.HexColor('#34495e'),
                              spaceAfter=8, spaceBefore=8)
    normal_style = ParagraphStyle('Body', parent=styles['BodyText'],
                                  fontName=font_name, fontSize=9, leading=13,
                                  textColor=colors.black,
                                  spaceAfter=4, alignment=TA_LEFT)
    list_style = ParagraphStyle('List', parent=normal_style,
                                leftIndent=14, bulletIndent=0)
    note_style = ParagraphStyle('Note', parent=normal_style,
                                textColor=colors.HexColor('#7f8c8d'),
                                fontSize=8, leading=11)

    elements = []
    lines = md_text.split('\n')
    i = 0
    in_code = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 代码块
        if stripped.startswith('```'):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue

        # 标题
        if stripped.startswith('# '):
            elements.append(Paragraph(stripped[2:], h1_style))
            elements.append(Spacer(1, 6))
            i += 1
            continue
        if stripped.startswith('## '):
            elements.append(Paragraph(stripped[3:], h2_style))
            i += 1
            continue
        if stripped.startswith('### '):
            elements.append(Paragraph(stripped[4:], h3_style))
            i += 1
            continue

        # 表格
        if stripped.startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s\-:|]+\|$', lines[i+1].strip()):
            rows, next_i = parse_markdown_table(lines, i)
            if rows:
                # 转换为 reportlab Table
                # 转义特殊字符
                clean_rows = []
                for row in rows:
                    clean_row = []
                    for cell in row:
                        # 转义reportlab特殊字符
                        cell = cell.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        # 转换Markdown加粗
                        cell = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', cell)
                        # 转换Markdown标记
                        cell = cell.replace('✅', '<font color="green">✓</font>')
                        cell = cell.replace('❌', '<font color="red">✗</font>')
                        clean_row.append(cell)
                    clean_rows.append(clean_row)
                # 计算列宽
                n_cols = max(len(r) for r in clean_rows)
                page_width = A4[0] - 4*cm
                col_width = page_width / n_cols
                # 第一行作为表头
                t = Table(clean_rows, colWidths=[col_width]*n_cols, repeatRows=1)
                t.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (-1, -1), font_name),
                    ('FONTSIZE', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                     [colors.HexColor('#f8f9fa'), colors.HexColor('#ffffff')]),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#bdc3c7')),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ]))
                elements.append(t)
                elements.append(Spacer(1, 6))
            i = next_i
            continue

        # 水平线
        if stripped == '---':
            elements.append(Spacer(1, 4))
            i += 1
            continue

        # 列表
        if re.match(r'^[\-\*] ', stripped):
            text = re.sub(r'^[\-\*] ', '', stripped)
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            elements.append(Paragraph(f'• {text}', list_style))
            i += 1
            continue

        # 数字列表
        if re.match(r'^\d+\. ', stripped):
            text = re.sub(r'^\d+\. ', '', stripped)
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            elements.append(Paragraph(text, list_style))
            i += 1
            continue

        # 空行
        if not stripped:
            elements.append(Spacer(1, 4))
            i += 1
            continue

        # 普通段落
        text = stripped
        # 加粗
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # 代码
        text = re.sub(r'`(.+?)`', r'<font name="Courier">\1</font>', text)
        # 特殊符号
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = text.replace('✅', '<font color="green">✓</font>')
        text = text.replace('❌', '<font color="red">✗</font>')
        try:
            elements.append(Paragraph(text, normal_style))
        except Exception as e:
            # 转义失败时,使用纯文本
            text_clean = re.sub(r'<[^>]+>', '', text)
            elements.append(Paragraph(text_clean, normal_style))
        i += 1

    return elements


def main():
    if len(sys.argv) < 2:
        print('用法: python md_to_pdf.py <markdown_file> [output_pdf]')
        sys.exit(1)

    md_path = Path(sys.argv[1])
    if not md_path.exists():
        print(f'文件不存在: {md_path}')
        sys.exit(1)

    pdf_path = Path(sys.argv[2]) if len(sys.argv) > 2 else md_path.with_suffix('.pdf')

    # 读取Markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()

    # 注册字体
    font_name = register_chinese_font()
    print(f'使用字体: {font_name}')

    # 创建PDF
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title=md_path.stem
    )

    elements = md_to_pdf_elements(md_content, font_name)
    doc.build(elements)

    size_kb = pdf_path.stat().st_size / 1024
    print(f'已生成: {pdf_path} ({size_kb:.1f} KB)')


if __name__ == '__main__':
    main()
