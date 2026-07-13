// 把 MinerU 输出的 full.md 按 SKILL 排除原则裁剪，输出干净的说明书
// 用法: npx tsx scripts/extract-manual.ts <pdf-base-name> [原版PDF路径]

import { readFileSync, writeFileSync, copyFileSync, existsSync, mkdirSync, readdirSync, statSync, rmSync } from 'fs'
import { join, basename } from 'path'

const base = process.argv[2]
const pdfSrc = process.argv[3]  // 可选：原版 PDF 路径
if (!base) {
  console.error('Usage: npx tsx scripts/extract-manual.ts <pdf-base-name> [原版PDF路径]')
  process.exit(1)
}

const TEMP_BASE = join(process.cwd(), 'temp', base)
const MD = join(TEMP_BASE, 'mineru', 'full.md')
const IMG_SRC = join(TEMP_BASE, 'mineru', 'images')

// 排除原则（来自 references/排除原则.md）：
// - 保留 1 概述（应用范围 + 功能配置），去掉 1.3 产品特点
// - 保留 3 工作原理（仅 3.X 保护功能），去掉 3.X 测控/时间管理/辅助
// - 保留 5 定值及参数（5.1 保护定值 + 5.4 出口设置），去掉 5.2 测控/5.3 辅助/装置设置
// - 整章删除：2 技术参数、4 硬件描述、6 人机接口、7 安装调试、8 维护、9 报废、10 订货

// 输出位置
const MANUFACTURER = '许继电气'  // 用户提供型号所在厂家
const DEVICE_TYPE = '线路保护'
const MODEL = 'PAC-8211A'  // 用户提供型号
const OUT_DIR = join(process.cwd(), 'workspace', 'manuals', MANUFACTURER, DEVICE_TYPE, MODEL)

const text = readFileSync(MD, 'utf-8')
const lines = text.split('\n')

// 找出每个一级章节的起止行（跳过目录，目录含".."）
function findSectionRange(name: string): [number, number] | null {
  // 用 " " 或行尾作为边界（避免 \b 在行尾不匹配的坑）
  const startRe = new RegExp(`^## ${name}(?: |$)`)
  let start = -1
  for (let i = 0; i < lines.length; i++) {
    if (startRe.test(lines[i]) && !lines[i].includes('..')) { start = i; break }
  }
  if (start < 0) return null
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    if (/^## \d+ /.test(lines[i]) && !lines[i].includes('..')) { end = i; break }
  }
  return [start, end]
}

const sec1 = findSectionRange('1 概述')
const sec3 = findSectionRange('3 工作原理')
const sec5 = findSectionRange('5 定值及参数')

if (!sec1 || !sec3 || !sec5) {
  console.error('找不到关键章节')
  process.exit(1)
}

const [s1Start, s1End] = sec1
const [s3Start, s3End] = sec3
const [s5Start, s5End] = sec5

// 章节 1：取到 1.3 之前
function cutAtSubsection(start: number, end: number, subsecName: string): number {
  const re = new RegExp(`^## ${subsecName.replace(/\./g, '\\.')}(?: |$)`)
  for (let i = start + 1; i < end; i++) {
    if (re.test(lines[i]) && !lines[i].includes('..')) return i
  }
  return end
}

const s1Cut = cutAtSubsection(s1Start, s1End, '1.3')

// 章节 3：取 3.1，截到 3.2
const s3Cut = cutAtSubsection(s3Start, s3End, '3.2')

// 章节 5：取 5.1（所有 5.1.x），到 5.2 之前
const s5Cut = cutAtSubsection(s5Start, s5End, '5.2')

// 5.1 内部还要包括 5.4 出口设置（保留）
// 找到 5.4 的开始
function findSubsection(start: number, end: number, subsecName: string): number {
  const re = new RegExp(`^## ${subsecName.replace(/\./g, '\\.')}(?: |$)`)
  for (let i = start; i < end; i++) {
    if (re.test(lines[i]) && !lines[i].includes('..')) return i
  }
  return -1
}

const s5_4Start = findSubsection(s5Start, s5End, '5.4')

// 删除 mermaid 代码块（PDF 图的 OCR 中间表示，web 不渲染）
// 模式：<details><summary>flowchart</summary>\n\n```mermaid\n...\n```\n</details>
// 整块删，但保留前面的 ![](images/...) 图片引用
// 必须严格匹配 summary=flowchart 的 details 块，避免非贪婪 .* 跨块匹配到下面的 flowchart
function stripMermaid(input: string): string {
  const blockRe = /<details>\s*<summary>flowchart<\/summary>[\s\S]*?<\/details>\s*/g
  return input.replace(blockRe, '')
}

// 同步删除 text_image 块（OCR 文字备份，实际图片已在前面渲染过）
function stripTextImage(input: string): string {
  const blockRe = /<details>\s*<summary>text_image<\/summary>[\s\S]*?<\/details>\s*/g
  return input.replace(blockRe, '')
}

// mermaid 源里有些特殊字符（&、<、>）未转义会导致解析失败
// web 端渲染时会 sanitize（Markdown.tsx），这里不再做
// function sanitizeMermaid(src: string): string {
//   return src.replace(/&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)/g, '&amp;')
// }

// 修复标题层次：MinerU 把所有章节都标成 ##，根据编号位数重映射
// ## N → ## N （h2，章）
// ## N.M → ### N.M （h3，节）
// ## N.M.K → #### N.M.K （h4，小节）
// ## N.M.K.L → ##### N.M.K.L （h5）
function fixHeadings(text: string): string {
  // 处理 ## 标题
  text = text.replace(/^(#{2,6}) (\d+(?:\.\d+)+)\b/gm, (_, _hashes, num) => {
    const dots = (num.match(/\./g) || []).length
    return '#'.repeat(dots + 2) + ' ' + num
  })
  // 处理纯文本章节标签（如 "5.1.1 设备参数"——源里漏了 ##）
  // 只匹配独立行的"N.M.K 标题"，避免误中表格/列表里的内容
  text = text.replace(/^(\d+\.\d+\.\d+)\s+(.+)$/gm, (_, num, title) => {
    return '#### ' + num + ' ' + title
  })
  // N.M 标签（如 "3.1 保护功能" 没 ## 的也补上）
  text = text.replace(/^(\d+\.\d+)\s+([^\.\d].+)$/gm, (_, num, title) => {
    return '### ' + num + ' ' + title
  })
  // 清理误标成 ## 的列表项（如 "## 1）重合闸..." 应该是列表项不是标题）
  text = text.replace(/^#{2,6}\s+(\d+）)/gm, '$1')
  return text
}

// HTML 表格转 Markdown 表格（处理 rowspan/colspan，展开为重复单元格）
function htmlTableToMd(input: string): string {
  return input.replace(/<table>([\s\S]*?)<\/table>/g, (_, inner) => {
    const rowRe = /<tr>([\s\S]*?)<\/tr>/g
    const rawRows: Array<Array<{ content: string; rowspan: number; colspan: number }>> = []
    for (const rowMatch of inner.matchAll(rowRe)) {
      const cells: Array<{ content: string; rowspan: number; colspan: number }> = []
      for (const cellMatch of rowMatch[1].matchAll(/<t[dh]([^>]*)>([\s\S]*?)<\/t[dh]>/g)) {
        const attrs = cellMatch[1]
        const content = cellMatch[2].trim()
        const rowspan = parseInt(attrs.match(/rowspan="(\d+)"/)?.[1] || '1', 10)
        const colspan = parseInt(attrs.match(/colspan="(\d+)"/)?.[1] || '1', 10)
        cells.push({ content, rowspan, colspan })
      }
      rawRows.push(cells)
    }
    if (rawRows.length === 0) return ''

    // 算最大列数（按 colspan 累加）
    let maxCols = 0
    for (const row of rawRows) {
      let colCount = 0
      for (const cell of row) colCount += cell.colspan
      if (colCount > maxCols) maxCols = colCount
    }
    const numRows = rawRows.length
    const matrix: string[][] = Array.from({ length: numRows }, () => Array(maxCols).fill(''))
    const occupied: boolean[][] = Array.from({ length: numRows }, () => Array(maxCols).fill(false))

    for (let r = 0; r < numRows; r++) {
      let col = 0
      for (const cell of rawRows[r]) {
        // 跳过被上方 rowspan 占用的列
        while (col < maxCols && occupied[r][col]) col++
        if (col >= maxCols) break
        // 填充 cell + 其 rowspan/colspan 区域
        for (let rr = 0; rr < cell.rowspan && r + rr < numRows; rr++) {
          for (let cc = 0; cc < cell.colspan && col + cc < maxCols; cc++) {
            matrix[r + rr][col + cc] = cell.content
            occupied[r + rr][col + cc] = true
          }
        }
        col += cell.colspan
      }
    }

    const lines: string[] = []
    if (matrix.length > 0) {
      lines.push('| ' + matrix[0].join(' | ') + ' |')
      lines.push('| ' + matrix[0].map(() => '---').join(' | ') + ' |')
      for (let i = 1; i < matrix.length; i++) {
        lines.push('| ' + matrix[i].join(' | ') + ' |')
      }
    }
    return lines.join('\n')
  })
}

// 组装输出：去掉开头的封面/目录/前言，只保留 1 概述、3.1 保护功能、5.1 保护定值 + 5.4 出口设置
const out: string[] = []
out.push(`# ${MODEL} 线路保护测控装置技术说明书`)
out.push('')
out.push(`> 来源：${base}.pdf | 提取：markitdown + MinerU 合并`)
out.push('')
out.push('---')
out.push('')

// 1 概述（去掉 1.3）
out.push(...lines.slice(s1Start, s1Cut))
out.push('')
out.push('---')
out.push('')

// 3 工作原理 - 3.1
out.push(...lines.slice(s3Start, s3Cut))
out.push('')
out.push('---')
out.push('')

// 5 定值及参数 - 5.1（保护定值，含 5.1.1-5.1.4）
out.push(...lines.slice(s5Start, s5Cut))
out.push('')
out.push('---')
out.push('')

// 5.4 出口设置
if (s5_4Start > 0) {
  out.push(...lines.slice(s5_4Start, s5End))
  out.push('')
}

mkdirSync(OUT_DIR, { recursive: true })

// 修复 markdown 格式：strip details（mermaid 块 + text_image 块）→ HTML 表格转 markdown 表格 → 标题层次修正
const stripped = stripTextImage(stripMermaid(out.join('\n')))
const formatted = htmlTableToMd(stripped)
const final = fixHeadings(formatted)
writeFileSync(join(OUT_DIR, `${MODEL}线路保护说明书.md`), final)

// 复制 images 目录：只复制最终 markdown 里引用的图
const referencedImgs = new Set<string>()
for (const m of final.matchAll(/!\[[^\]]*\]\(images\/([a-f0-9]+\.jpg)\)/g)) {
  referencedImgs.add(m[1])
}

const IMG_DST = join(OUT_DIR, 'images')
if (existsSync(IMG_DST)) rmSync(IMG_DST, { recursive: true, force: true })
if (referencedImgs.size > 0) {
  mkdirSync(IMG_DST, { recursive: true })
  let copied = 0
  for (const f of referencedImgs) {
    const src = join(IMG_SRC, f)
    if (existsSync(src)) {
      copyFileSync(src, join(IMG_DST, f))
      copied++
    }
  }
  const total = readdirSync(IMG_SRC).filter((f) => f.endsWith('.jpg')).length
  console.log(`✓ 复制 ${copied}/${total} 张被引用的图片（节省 ${total - copied} 张）`)
}

// 复制原版 PDF（如提供）
if (pdfSrc && existsSync(pdfSrc)) {
  const pdfDst = join(OUT_DIR, basename(pdfSrc))
  copyFileSync(pdfSrc, pdfDst)
  console.log(`✓ 复制原版 PDF: ${basename(pdfSrc)}`)
} else if (pdfSrc) {
  console.warn(`⚠ 原版 PDF 路径不存在: ${pdfSrc}（跳过）`)
}

console.log(`✓ 输出: ${join(OUT_DIR, `${MODEL}线路保护说明书.md`)}`)
console.log(`  行数: ${final.split('\n').length}`)
