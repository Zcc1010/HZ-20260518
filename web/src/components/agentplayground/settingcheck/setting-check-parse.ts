import * as XLSX from 'xlsx'
import mammoth from 'mammoth'
import GithubSlugger from 'github-slugger'

export interface OutlineItem {
  id: string
  level: number
  text: string
  page?: number
}

export interface CellMerge {
  s: { r: number; c: number }
  e: { r: number; c: number }
}

export interface ColInfo {
  wpx?: number
  wch?: number
  hidden?: boolean
}

export interface SheetData {
  name: string
  rows: string[][]
  merges: CellMerge[]
  cols: ColInfo[]
}

export interface ParseResult {
  sheets: SheetData[]
  outline: OutlineItem[]
}

export function slugify(text: string): string {
  return text.replace(/[#*`_~]/g, '').trim().replace(/\s+/g, '-').toLowerCase()
}

// ── Markdown ──

export function parseMarkdownOutline(text: string): OutlineItem[] {
  const lines = text.split('\n')
  const outline: OutlineItem[] = []
  let inCode = false
  const slugger = new GithubSlugger()
  for (const line of lines) {
    if (/^```/.test(line.trim())) { inCode = !inCode; continue }
    if (inCode) continue
    const m = /^(#{1,6})\s+(.+)/.exec(line)
    if (m) {
      const level = m[1].length
      const t = m[2].replace(/[#*`_~]/g, '').trim()
      outline.push({ id: slugger.slug(t), level, text: t })
    }
  }
  return outline
}

// ── XLSX ──

export function parseXlsx(data: ArrayBuffer): ParseResult {
  const wb = XLSX.read(data, { type: 'array', cellStyles: true })
  const sheets: SheetData[] = []
  for (const name of wb.SheetNames) {
    const sheet = wb.Sheets[name]
    const raw = XLSX.utils.sheet_to_json<any[]>(sheet, { header: 1, raw: false, defval: '' })
    const rows = (raw as any[][]).map((r) => r.map((c) => String(c ?? '')))

    const merges: CellMerge[] = (sheet['!merges'] || []).map((m: any) => ({
      s: { r: m.s.r, c: m.s.c },
      e: { r: m.e.r, c: m.e.c },
    }))
    const cols: ColInfo[] = (sheet['!cols'] || []).map((c: any) => ({
      wpx: c.wpx,
      wch: c.wch,
      hidden: c.hidden,
    }))

    let lastNonEmpty = -1
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].some((c) => c.trim() !== '')) lastNonEmpty = i
    }
    const trimmedRows = rows.slice(0, lastNonEmpty + 1)

    let maxCol = 0
    for (const row of trimmedRows) {
      for (let c = row.length - 1; c >= 0; c--) {
        if (row[c].trim() !== '') {
          if (c + 1 > maxCol) maxCol = c + 1
          break
        }
      }
    }
    for (const m of merges) {
      if (m.e.c + 1 > maxCol) maxCol = m.e.c + 1
    }
    const finalRows = trimmedRows.map((r) => {
      const sliced = r.slice(0, maxCol)
      while (sliced.length < maxCol) sliced.push('')
      return sliced
    })
    sheets.push({ name, rows: finalRows, merges, cols })
  }
  return { sheets, outline: [] }
}

// ── DOCX ──

export async function parseDocx(data: ArrayBuffer): Promise<{ html: string; outline: OutlineItem[] }> {
  const result = await mammoth.convertToHtml({ arrayBuffer: data })
  const html = result.value
  const outline: OutlineItem[] = []
  let idx = 0
  const regex = /<h([1-6])[^>]*>([\s\S]*?)<\/h\1>/gi
  let m
  while ((m = regex.exec(html)) !== null) {
    const level = parseInt(m[1])
    const text = m[2].replace(/<[^>]+>/g, '').trim()
    if (text) {
      outline.push({ id: `docx-heading-${idx}`, level, text })
      idx++
    }
  }
  return { html, outline }
}

// ── DOC (legacy binary) outline from backend HTML ──

export function parseDocOutline(html: string): OutlineItem[] {
  const outline: OutlineItem[] = []
  let idx = 0
  const regex = /<(h[1-4])\s+id="doc-heading-(\d+)"[^>]*>([\s\S]*?)<\/\1>/gi
  let m
  while ((m = regex.exec(html)) !== null) {
    const level = parseInt(m[1][1])
    const text = m[3].replace(/<[^>]+>/g, '').trim()
    if (text) {
      outline.push({ id: `doc-heading-${idx}`, level, text })
      idx++
    }
  }
  return outline
}

// ── PDF ──

let pdfjsPromise: Promise<any> | null = null
async function getPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const pdfjs = await import('pdfjs-dist')
      const worker = await import('pdfjs-dist/build/pdf.worker.mjs?url')
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default
      return pdfjs
    })()
  }
  return pdfjsPromise
}

export async function parsePdfOutline(data: ArrayBuffer): Promise<OutlineItem[]> {
  const pdfjs = await getPdfjs()
  const doc = await pdfjs.getDocument({ data }).promise

  try {
    const outline_data = await doc.getOutline()
    if (outline_data && outline_data.length > 0) {
      const items: OutlineItem[] = []
      async function walk(nodes: any[], level: number) {
        for (const n of nodes) {
          let pageNum: number | undefined
          if (n.dest) {
            try {
              let dest = n.dest
              if (typeof dest === 'string') dest = await doc.getDestination(dest)
              if (Array.isArray(dest) && dest[0]) {
                const ref = dest[0]
                const idx = await doc.getPageIndex(ref)
                pageNum = idx + 1
              }
            } catch {}
          }
          items.push({ id: `pdf-${items.length}`, level, text: n.title, page: pageNum })
          if (n.items && n.items.length) await walk(n.items, level + 1)
        }
      }
      await walk(outline_data, 1)
      if (items.length > 0) return items
    }
  } catch {}

  const pageText: Array<{ size: number; text: string; page: number }> = []
  let maxSize = 0
  for (let p = 1; p <= doc.numPages; p++) {
    const page = await doc.getPage(p)
    const tc = await page.getTextContent()
    for (const item of tc.items as any[]) {
      if (!item.str || !item.str.trim()) continue
      const ts = item.transform
      const size = Math.hypot(ts[0], ts[1])
      if (size > maxSize) maxSize = size
      pageText.push({ size, text: item.str.trim(), page: p })
    }
  }
  const outline: OutlineItem[] = []
  if (maxSize > 0) {
    const threshold = maxSize * 0.82
    let idx = 0
    for (const d of pageText) {
      if (d.size >= threshold && d.text.length < 80) {
        outline.push({ id: `pdf-${idx}`, level: d.size >= maxSize * 0.95 ? 1 : 2, text: d.text, page: d.page })
        idx++
      }
    }
  }
  return outline
}
