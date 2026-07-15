# -*- coding: utf-8 -*-
"""从 .docx 提取纯文本（含表格结构），无需第三方库。
用法：python3 docx_extract.py <file.docx>
表格以 [TABLE] ... [/TABLE] 包裹，单元格以 ' | ' 分隔。
"""
import zipfile, sys
from xml.etree import ElementTree as ET

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

def extract(path):
    out = []
    z = zipfile.ZipFile(path)
    xml = z.read('word/document.xml')
    root = ET.fromstring(xml)
    body = root.find(W+'body')
    def text_of(p):
        return ''.join(t.text or '' for t in p.iter(W+'t'))
    for el in body:
        tag = el.tag
        if tag == W+'p':
            out.append(text_of(el))
        elif tag == W+'tbl':
            out.append('[TABLE]')
            for tr in el.findall(W+'tr'):
                cells = []
                for tc in tr.findall(W+'tc'):
                    cells.append(' '.join(text_of(p) for p in tc.iter(W+'p')).strip())
                out.append(' | '.join(cells))
            out.append('[/TABLE]')
    return '\n'.join(out)

if __name__ == '__main__':
    print(extract(sys.argv[1]))
