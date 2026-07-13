import { useEffect, useState, useMemo } from 'react'
import { FileText } from 'lucide-react'
import { readBinaryFile, getFileUrl } from './setting-check-api'
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'
import { parseXlsx, parseDocx, parsePdfOutline, parseMarkdownOutline, parseDocOutline, type OutlineItem, type SheetData } from './setting-check-parse'
import { PdfViewer } from './PdfViewer'

function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let current: string[] = []
  let field = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') { field += '"'; i++ }
        else { inQuotes = false }
      } else { field += ch }
    } else {
      if (ch === '"') { inQuotes = true }
      else if (ch === ',') { current.push(field); field = '' }
      else if (ch === '\n' || ch === '\r') {
        current.push(field); field = ''
        if (current.some(c => c.trim() !== '')) rows.push(current)
        current = []
        if (ch === '\r' && text[i + 1] === '\n') i++
      } else { field += ch }
    }
  }
  current.push(field)
  if (current.some(c => c.trim() !== '')) rows.push(current)
  return rows
}

interface Props {
  workspacePath: string | null
  filePath: string | null
  version?: number
  activeSheet: number
  onSheetsChange: (sheets: string[]) => void
  onActiveSheetChange: (idx: number) => void
  onOutlineChange: (outline: OutlineItem[]) => void
  pdfPage?: number
}

export function FileViewer({ workspacePath, filePath, version, activeSheet, onSheetsChange, onActiveSheetChange, onOutlineChange, pdfPage }: Props) {
  const [mdContent, setMdContent] = useState('')
  const [docxHtml, setDocxHtml] = useState('')
  const [sheets, setSheets] = useState<SheetData[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const ext = filePath?.split('.').pop()?.toLowerCase() || ''

  useEffect(() => {
    if (!workspacePath || !filePath) {
      setMdContent(''); setDocxHtml(''); setSheets([])
      onSheetsChange([]); onOutlineChange([])
      return
    }
    setLoading(true); setError('')

    async function load() {
      try {
        onSheetsChange([]); onOutlineChange([])
        setMdContent(''); setDocxHtml(''); setSheets([])

        if (ext === 'csv') {
          const text = await fetch(getFileUrl(workspacePath!, filePath!)).then((r) => r.text())
          const rows = parseCsv(text)
          setSheets([{ name: 'Sheet1', rows, cols: [], merges: [] }])
          onSheetsChange(['Sheet1'])
        } else if (['xls', 'xlsx'].includes(ext)) {
          const data = await readBinaryFile(workspacePath!, filePath!)
          const bytes = Uint8Array.from(atob(data.base64), (c) => c.charCodeAt(0))
          const result = parseXlsx(bytes.buffer)
          setSheets(result.sheets)
          onSheetsChange(result.sheets.map((s) => s.name))
        } else if (ext === 'docx') {
          const data = await readBinaryFile(workspacePath!, filePath!)
          const bytes = Uint8Array.from(atob(data.base64), (c) => c.charCodeAt(0))
          const { html, outline } = await parseDocx(bytes.buffer)
          setDocxHtml(html)
          onOutlineChange(outline)
        } else if (ext === 'doc') {
          const resp = await fetch(getFileUrl(workspacePath!, filePath!))
          if (!resp.ok) {
            throw new Error('doc 解析失败')
          }
          const html = await resp.text()
          setDocxHtml(html)
          onOutlineChange(parseDocOutline(html))
        } else if (ext === 'pdf') {
          const resp = await fetch(getFileUrl(workspacePath!, filePath!))
          const buf = await resp.arrayBuffer()
          const outline = await parsePdfOutline(buf)
          onOutlineChange(outline)
        } else if (['md', 'markdown', 'txt'].includes(ext)) {
          const text = await fetch(getFileUrl(workspacePath!, filePath!)).then((r) => r.text())
          setMdContent(text)
          onOutlineChange(parseMarkdownOutline(text))
        }
      } catch (e: any) {
        setError(e.message || '读取失败')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [workspacePath, filePath, version])

  const docxHtmlWithIds = useMemo(() => {
    if (!docxHtml) return ''
    let idx = 0
    return docxHtml.replace(/<(h[1-6])[^>]*>/gi, (_tag, h) => {
      const id = `docx-heading-${idx}`
      idx++
      return `<${h} id="${id}">`
    })
  }, [docxHtml])

  const mergeLayout = useMemo(() => {
    const sheet = sheets[activeSheet] || sheets[0]
    if (!sheet || !sheet.merges || sheet.merges.length === 0) {
      const hiddenCols = new Set<number>()
      if (sheet?.cols) sheet.cols.forEach((c, i) => { if (c.hidden) hiddenCols.add(i) })
      return { mergeMap: new Map(), covered: new Set<string>(), hiddenCols, colWidths: sheet?.cols || [] }
    }
    const mergeMap = new Map<string, { rowspan: number; colspan: number }>()
    const covered = new Set<string>()
    for (const m of sheet.merges) {
      const rs = m.e.r - m.s.r + 1
      const cs = m.e.c - m.s.c + 1
      mergeMap.set(`${m.s.r},${m.s.c}`, { rowspan: rs, colspan: cs })
      for (let r = m.s.r; r <= m.e.r; r++) {
        for (let c = m.s.c; c <= m.e.c; c++) {
          if (r === m.s.r && c === m.s.c) continue
          covered.add(`${r},${c}`)
        }
      }
    }
    const hiddenCols = new Set<number>()
    if (sheet.cols) sheet.cols.forEach((c, i) => { if (c.hidden) hiddenCols.add(i) })
    return { mergeMap, covered, hiddenCols, colWidths: sheet.cols || [] }
  }, [sheets, activeSheet])

  if (!filePath) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-center">
          <FileText className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <div className="text-sm">选择文件查看内容</div>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="flex items-center gap-2 text-sm">
          <div className="w-4 h-4 border-2 border-gray-200 border-t-teal-500 rounded-full animate-spin" />
          加载中
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-red-500 text-sm">{error}</div>
    )
  }

  if (['xls', 'xlsx', 'csv'].includes(ext)) {
    const sheet = sheets[activeSheet] || sheets[0]
    return (
      <div className="h-full flex flex-col">
        {sheets.length > 1 && (
          <div className="flex border-b border-gray-200 bg-white shrink-0 overflow-x-auto">
            {sheets.map((s, i) => (
              <button
                key={i}
                title={s.name}
                onClick={() => onActiveSheetChange(i)}
                className={`px-3 py-1.5 text-[13px] border-r border-gray-200 whitespace-nowrap shrink-0 transition-colors ${
                  i === activeSheet ? 'bg-gray-50 text-teal-700 font-medium border-b-2 border-b-teal-500' : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        <div className="flex-1 overflow-auto">
        {sheet && sheet.rows.length > 0 ? (
          <table className="border-collapse text-[12px] w-auto">
            <colgroup>
              {sheet.cols && sheet.cols.map((c, i) => {
                if (mergeLayout.hiddenCols.has(i)) return null
                let w: string | undefined
                if (c.wpx) w = `${c.wpx}px`
                else if (c.wch) w = `${Math.round(c.wch * 7 + 5)}px`
                return w ? <col key={i} style={{ width: w, minWidth: w }} /> : <col key={i} />
              })}
            </colgroup>
            <tbody>
              {sheet.rows.map((row, ri) => (
                <tr key={ri}>
                  {row.map((cell, ci) => {
                    if (mergeLayout.hiddenCols.has(ci)) return null
                    const key = `${ri},${ci}`
                    if (mergeLayout.covered.has(key)) return null
                    const span = mergeLayout.mergeMap.get(key)
                    const isMerged = !!span
                    return (
                      <td
                        key={ci}
                        rowSpan={span?.rowspan}
                        colSpan={span?.colspan}
                        className={`border border-gray-200 px-1.5 py-0.5 whitespace-nowrap ${
                          ri === 0 ? 'bg-gray-50 font-medium' : (isMerged ? 'bg-gray-50/50' : 'bg-white')
                        } ${cell.trim() === '' ? 'text-gray-300' : 'text-gray-700'}`}
                      >
                        {cell}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
       ) : (
         <div className="p-4 text-sm text-gray-400">此工作表为空</div>
       )}
      </div>
      </div>
    )
  }

  if (['doc', 'docx'].includes(ext)) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <div className="markdown-body max-w-none" dangerouslySetInnerHTML={{ __html: docxHtmlWithIds }} />
      </div>
    )
  }

  if (ext === 'pdf') {
    const url = workspacePath ? getFileUrl(workspacePath, filePath) : ''
    return (
      <PdfViewer url={url} targetPage={pdfPage} />
    )
  }

  if (['md', 'markdown'].includes(ext)) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <MarkdownRenderer content={mdContent} />
      </div>
    )
  }

  if (ext === 'json') {
    return (
      <div className="h-full overflow-y-auto p-6">
        <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-4 rounded-lg">
          {(() => { try { return JSON.stringify(JSON.parse(mdContent), null, 2) } catch { return mdContent } })()}
        </pre>
      </div>
    )
  }

  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) {
    return (
      <div className="h-full overflow-y-auto p-6 flex items-center justify-center">
        <img src={workspacePath ? getFileUrl(workspacePath, filePath) : ''} alt={filePath} className="max-w-full max-h-full" />
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono">{mdContent}</pre>
    </div>
  )
}
