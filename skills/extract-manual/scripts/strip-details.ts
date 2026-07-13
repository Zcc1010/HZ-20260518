import { readFileSync, writeFileSync } from 'fs'

const file = process.argv[2]
if (!file) {
  console.error('usage: npx tsx strip-details.ts <path-to-md>')
  process.exit(1)
}

const src = readFileSync(file, 'utf-8')
// 匹配 <details>\n<summary>...</summary>\n...\n</details>（多行非贪婪）
// 说明书里的 details 都是 MinerU 产物：flowchart（mermaid 块）或 text_image（OCR 文字备份）
// 实际图片已经在 details 之前通过 ![](images/xxx.jpg) 渲染了，全部清掉
const re = /<details>\s*<summary>[^<]*<\/summary>[\s\S]*?<\/details>\s*/g
const out = src.replace(re, '')
const removed = (src.match(re) || []).length
writeFileSync(file, out, 'utf-8')
console.log(`removed ${removed} details block(s) from ${file}`)
