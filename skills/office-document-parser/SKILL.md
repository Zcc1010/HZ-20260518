---
name: office-document-parser
description: 当运行中的智能体需要读取、检查、总结、提取或比较 pdf、doc、docx、xls、xlsx、ppt、pptx 等文档附件时使用。适用于查看 PDF 或 Office 正文内容、列出 Excel 工作表、预览指定 sheet、以及处理旧版二进制 Office 文件。遇到 OFD 时可先尝试通过 LibreOffice 转换，再根据结果继续处理。
---

# Office 文档解析

## 概览

这个技能用于在运行时容器中处理 PDF 和 Office 附件。

默认流程：
- 先识别文件类型和用户意图
- 再只读取对应类型的参考文档
- 优先复用技能自带脚本和 `markitdown` CLI

## 何时使用

当用户要求你：
- 查看 PDF、Word、Excel、PPT 的内容
- 总结文档或从文档提取正文
- 判断 Excel 有多少个工作表、工作表叫什么
- 提取某个指定 sheet 或工作表的内容
- 兼容处理旧版 `doc/xls/ppt`
- 尝试处理 `ofd`

不要优先用于：
- 纯文本、Markdown、JSON、CSV 之类本来就可直接读取的文件

## 硬性规则

- 严禁在运行时容器内执行任何安装命令。
- 不要直接用 `read_file` 读取 PDF 或二进制 Office 文件。
- 不要为了“列出 sheet”先转 CSV。
- 不要把单个 sheet 的内容当成整个工作簿的结论。
- 如果用户明确要求“把文件发给我 / 给我附件 / 处理完发我 / 导出给我”，完成标准不是口头总结，而是把最终文件保存到工作区，并通过 `message(..., media=[...])` 交付给用户。
- 如果既要总结又要文件，先给简短摘要，再发送附件；不要只返回正文。
- 不要把中间产物误当成最终交付物。优先发送用户真正需要的最终文件；只有用户明确要求中间 markdown/预览文件时才发送它。
- 如果失败，必须说明失败步骤、失败命令，以及是否还有下一条可用回退路径。

## 运行前提

镜像内应已预装：
- `markitdown`
- `soffice`
- `python3`

技能自带脚本：
- `scripts/inspect_workbook.py`
- `scripts/extract_sheet_preview.py`
- `scripts/convert_legacy_office.sh`

## 按类型路由

按文件类型只读取对应参考文档，不要把全部细节都带进上下文：

- `pdf`
  读取 [references/pdf.md](references/pdf.md)
- `xlsx`、`xls`
  读取 [references/excel.md](references/excel.md)
- `doc`、`docx`、`ppt`、`pptx`
  读取 [references/word-ppt.md](references/word-ppt.md)
- `ofd`，或旧格式转换/回退失败
  读取 [references/legacy-and-ofd.md](references/legacy-and-ofd.md)

如果用户问题跨多种类型：
- Excel 先回答结构，再读内容
- 其余文档优先走全文提取

## 交付规则

默认先把内容讲清楚，而不是优先讲处理过程。

当用户的目标是“拿到处理后的文件”时：
1. 确认最终交付文件路径
2. 确认文件位于工作区内
3. 调用 `message(..., media=[...])` 发送文件
4. 如有必要，再补一句简短说明这个文件是什么、有哪些局限

只有在下面这些情况，才需要说明处理路径：
- 用户明确追问“你是怎么处理的”
- 某一步失败了
- 文件是旧格式或 OFD，需要解释为什么只能给出部分结果

