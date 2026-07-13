---
name: extract-manual
description: >
  从保护装置说明书 PDF 提取结构化知识库，合并输出 1 个 Markdown 文件（概述+保护原理+定值说明）
  到 references/{厂家}/{设备类型}/{型号}/ 目录。
  触发词：解析说明书、extract manual、说明书入库。
  当用户提供保护装置说明书 PDF，要求提取/解析/入库说明书时使用。
---

# 保护装置说明书提取

由 Claude/pi 协调外部工具（markitdown / MinerU）将保护装置说明书 PDF 转为结构化 Markdown，按本流程处理。
本 SKILL.md 主讲流程；章节排除规则、格式规范、质量审查等见 `references/`。

## ⚠️ 文件名安全规则

- 路径必须用双引号包裹
- 英数字与中文之间不加空格：`220kV变压器` 正确，`220kV 变压器` 错误
- **禁止直接用 Read 工具读 PDF**（当前模型不支持 PDF 输入），必须先转 md

## 工作流

```
PDF → markitdown（纯文本md）   ─┐
                                 ├→ 子代理读取两份md → 按 references/ 规则重写合并为 1 份 md → 输出
      → MinerU（md + 图片）     ─┘
```

### 阶段 1：双源提取到 temp

```bash
mkdir -p "temp/{型号}"

# 1. markitdown：文字准确，无图片，表格格式差
markitdown "<pdf路径>" -o "temp/{型号}/markitdown.md"

# 2. MinerU：图片完整，LaTeX公式，HTML表格
mineru-open-api extract "<pdf路径>" -o "temp/{型号}/mineru/" -f md
```

两个 md 都放在 `temp/{型号}/` 下。**不要删除**，供后续审核。

### 阶段 2：子代理合并重写

派一个 **general 子代理**，读取两份 md（markitdown + MinerU），按 `references/` 下的规则重新生成一份 md。

**子代理任务**：
1. 读取 `temp/{型号}/markitdown.md` 和 `temp/{型号}/mineru/*.md`
2. 找到三个章节边界：概述、保护原理、定值说明
3. 以 MinerU 版为主体（图片、公式、表格更完整），用 markitdown 版纠错（OCR 错别字）
4. 只提取这三个章节，合并为一个 md 文件
5. 应用所有规则（见 `references/`）

### 阶段 3：输出与复制

输出目标：

```
manuals/{厂家}/{设备类型}/{型号}/{型号}{类型}说明书.md
manuals/{厂家}/{设备类型}/{型号}/images/
manuals/{厂家}/{设备类型}/{型号}/{原版PDF}.pdf  ← 可选
```

示例路径：
```
manuals/南瑞继保/线路保护/PCS-9611A/PCS-9611A线路保护说明书.md
manuals/南瑞继保/线路保护/PCS-9611A/images/
manuals/金智科技/变压器保护/UDL-531-GCN/UDL-531-GCN变压器保护说明书.md
```

- 图片只复制被 md 引用的文件（有图号的），从 `temp/{型号}/mineru/images/` 复制
- md 中用相对路径 `![](images/xxx.jpg)` 引用
- **原版 PDF 建议一起复制到输出目录**——作为图/表的溯源依据，方便人工核对"图和文字是否对得上"

### 阶段 4：质量审查

按 `references/质量审查.md` 逐项检查（内容完整性 / 排除正确 / 格式 / 图片）。

## 辅助脚本

`scripts/extract-manual.ts`：把 MinerU 输出的 `full.md` 按本 SKILL 规则裁剪、转换、输出到 `manuals/` 目录。**已实现所有自动转换**（标题层次、HTML 表格、details 块清理等），不必手写。

```bash
# 用法：
npx tsx scripts/extract-manual.ts <pdf-base-name> [原版PDF路径]

# 示例：
npx tsx scripts/extract-manual.ts PAC-8211A
npx tsx scripts/extract-manual.ts PAC-8211A "/path/to/PAC-8211A-GZK(提升)线路保护测控装置技术说明书.pdf"
```

**自动做的转换**（详见 `references/格式规范.md`）：
1. 章节裁剪：只保留 1 概述、3.1 保护功能、5.1 保护定值 + 5.4 出口设置
2. 删除 `## 1）...` 误标的列表项
3. 删除 `<details><summary>flowchart</summary>...mermaid...</details>` 块
4. 删除 `<details><summary>text_image</summary>...</details>` 块（OCR 文字备份）
5. 标题层次：按编号位数重映射（`## N.M.K` → `#### N.M.K`）+ 纯文本章节标签补 `##`
6. HTML `<table>` 转 markdown 表格（rowspan/colspan 展开为重复单元格）
7. 只复制 md 引用的图片（节省大量不相关的图）
8. 复制原版 PDF（如提供）

## 引用文档

- `references/排除原则.md` — 章节保留/删除规则（第1/3/5 章保留，其余删除）
- `references/格式规范.md` — 标题层级、表格、列表、图片、mermaid 等格式规则
- `references/质量审查.md` — 合并完成后的审查清单

## 辅助脚本

`scripts/` 目录下提供 **TypeScript 工具（新）+ 历史遗留 Python 脚本**：

### TypeScript（推荐）

| 脚本 | 用途 |
| --- | --- |
| `extract-manual.ts` | **核心**：MinerU 输出按 SKILL 规则裁剪、格式转换、输出到 `manuals/` 目录。已实现所有自动转换 |
| `strip-details.ts` | 一键清掉 md 里的 `<details>` 块（flowchart + text_image），用于手动清理 |

### Python（历史遗留，保留可用）

| 脚本 | 用途 |
| --- | --- |
| `extract_manual.py` | 早期版本 MinerU 提取脚本 |
| `html_table_to_md.py` | HTML 表格转 Markdown（含 rowspan） |
| `qwen_vlm.py` | 阿里云百炼 VLM 图片描述（可选） |
| `paddleocr_vl_parse.py` | PaddleOCR-VL 解析（备选） |
| 其他 | 分段、批量处理、VLM 描述/替换等辅助 |

## 跨 skill：校核时查找说明书

`setting-check` 校核维度三（保护原理）、维度四（定值项）需要说明书支撑。查找方式：

```bash
find resources/manuals -name "*{型号}*说明书.md"
```

找到后，将说明书 md + images/ 目录复制到当前工作区（records/ 文件夹）。
