import { useEffect, useRef, useState, useCallback } from 'react'
import { Minus, Plus, MoveHorizontal, Frame, ChevronLeft, ChevronRight } from 'lucide-react'

interface Props {
  url: string
  targetPage?: number
  onLoad?: (numPages: number) => void
}

type ZoomMode = 'width' | 'page' | 'manual'

export function PdfViewer({ url, targetPage, onLoad }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const pdfDocRef = useRef<any>(null)
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])
  const baseSizeRef = useRef<{ w: number; h: number } | null>(null)
  const renderedScaleRef = useRef<number>(-1)

  const [numPages, setNumPages] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [zoomMode, setZoomMode] = useState<ZoomMode>('width')
  const [scale, setScale] = useState(1.0)
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 })
  const [currentPage, setCurrentPage] = useState(1)
  const isJumpingRef = useRef(false)

  const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setNumPages(0)
    baseSizeRef.current = null
    renderedScaleRef.current = -1

    ;(async () => {
      try {
        const pdfjs: any = await import('pdfjs-dist')
        const worker = await import('pdfjs-dist/build/pdf.worker.mjs?url')
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default
        const loadingTask = pdfjs.getDocument({
          url,
          cMapUrl: 'https://unpkg.com/pdfjs-dist@6.0.227/cmaps/',
          cMapPacked: true,
        })
        const doc = await loadingTask.promise
        if (cancelled) return
        pdfDocRef.current = doc
        setNumPages(doc.numPages)
        onLoad?.(doc.numPages)
        const page1 = await doc.getPage(1)
        const vp = page1.getViewport({ scale: 1 })
        baseSizeRef.current = { w: vp.width, h: vp.height }
        setLoading(false)
      } catch (e: any) {
        if (!cancelled) {
          setError(e.message || 'PDF 加载失败')
          setLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
      if (pdfDocRef.current) {
        try { pdfDocRef.current.destroy() } catch {}
        pdfDocRef.current = null
      }
    }
  }, [url])

  useEffect(() => {
    if (loading) return
    const el = scrollRef.current
    if (!el) return
    const update = () => setContainerSize({ w: el.clientWidth - 32, h: el.clientHeight - 32 })
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [loading])

  useEffect(() => {
    const base = baseSizeRef.current
    if (!base || containerSize.w <= 0) return
    if (zoomMode === 'width') {
      setScale(containerSize.w / base.w)
    } else if (zoomMode === 'page') {
      setScale(Math.min(containerSize.w / base.w, containerSize.h / base.h))
    }
  }, [zoomMode, containerSize])

  useEffect(() => {
    if (!numPages || !pdfDocRef.current || scale <= 0) return
    if (Math.abs(renderedScaleRef.current - scale) < 0.001) return
    renderedScaleRef.current = scale
    let cancelled = false
    const doc = pdfDocRef.current

    ;(async () => {
      for (let i = 1; i <= numPages; i++) {
        if (cancelled) return
        const canvas = scrollRef.current?.querySelector(`canvas[data-page="${i}"]`) as HTMLCanvasElement | null
        if (!canvas) continue
        try {
          const page = await doc.getPage(i)
          if (cancelled) return
          const baseVp = page.getViewport({ scale: 1 })
          const viewport = page.getViewport({ scale: scale * dpr })
          const ctx = canvas.getContext('2d')!
          canvas.width = viewport.width
          canvas.height = viewport.height
          canvas.style.width = `${Math.round(scale * baseVp.width)}px`
          canvas.style.height = `${Math.round(scale * baseVp.height)}px`
          await page.render({ canvasContext: ctx, viewport }).promise
        } catch {}
      }
    })()

    return () => { cancelled = true }
  }, [numPages, scale, dpr])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !numPages) return
    let ticking = false
    const onScroll = () => {
      if (ticking) return
      if (isJumpingRef.current) return
      ticking = true
      requestAnimationFrame(() => {
        ticking = false
        const scrollTop = el.scrollTop
        let bestPage = 1
        for (let i = 0; i < pageRefs.current.length; i++) {
          const ref = pageRefs.current[i]
          if (!ref) continue
          if (ref.offsetTop - scrollTop <= 10) {
            bestPage = i + 1
          } else {
            break
          }
        }
        setCurrentPage(bestPage)
      })
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [numPages, scale])

  useEffect(() => {
    if (!targetPage || !numPages) return
    isJumpingRef.current = true
    setCurrentPage(targetPage)
    const el = pageRefs.current[targetPage - 1]
    const container = scrollRef.current
    if (el && container) container.scrollTo({ top: el.offsetTop - 16, behavior: 'smooth' })
    setTimeout(() => { isJumpingRef.current = false }, 800)
  }, [targetPage, numPages])

  const zoomIn = useCallback(() => {
    setZoomMode('manual')
    setScale((s) => Math.min(Math.round((s + 0.1) * 10) / 10, 5))
  }, [])
  const zoomOut = useCallback(() => {
    setZoomMode('manual')
    setScale((s) => Math.max(Math.round((s - 0.1) * 10) / 10, 0.2))
  }, [])

  const jumpToPage = useCallback((page: number) => {
    const clamped = Math.max(1, Math.min(page, numPages))
    isJumpingRef.current = true
    setCurrentPage(clamped)
    const el = pageRefs.current[clamped - 1]
    const container = scrollRef.current
    if (el && container) {
      container.scrollTo({ top: el.offsetTop - 16, behavior: 'smooth' })
    }
    setTimeout(() => { isJumpingRef.current = false }, 800)
  }, [numPages])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="flex items-center gap-2 text-sm">
          <div className="w-4 h-4 border-2 border-gray-200 border-t-teal-500 rounded-full animate-spin" />
          加载 PDF...
        </div>
      </div>
    )
  }

  if (error) {
    return <div className="h-full flex items-center justify-center text-red-500 text-sm">{error}</div>
  }

  return (
    <div className="h-full flex flex-col bg-gray-50">
      <div className="flex items-center justify-between px-3 py-1 border-b border-gray-200 bg-white shrink-0 gap-2">
        <div className="flex items-center gap-1 shrink-0">
          <button onClick={() => jumpToPage(currentPage - 1)} disabled={currentPage <= 1} className="w-7 h-7 flex items-center justify-center text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded disabled:opacity-30 disabled:cursor-not-allowed">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-[12px] text-gray-600 tabular-nums min-w-[50px] text-center">{currentPage} / {numPages}</span>
          <button onClick={() => jumpToPage(currentPage + 1)} disabled={currentPage >= numPages} className="w-7 h-7 flex items-center justify-center text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded disabled:opacity-30 disabled:cursor-not-allowed">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button title="适应宽度" onClick={() => setZoomMode('width')} className={`w-7 h-7 flex items-center justify-center rounded transition-colors ${zoomMode === 'width' ? 'bg-teal-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
            <MoveHorizontal className="w-4 h-4" />
          </button>
          <button title="适应页面" onClick={() => setZoomMode('page')} className={`w-7 h-7 flex items-center justify-center rounded transition-colors ${zoomMode === 'page' ? 'bg-teal-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>
            <Frame className="w-4 h-4" />
          </button>
          <div className="w-px h-4 bg-gray-200 mx-0.5" />
          <button onClick={zoomOut} className="w-6 h-6 flex items-center justify-center text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded">
            <Minus className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] text-gray-600 w-9 text-center tabular-nums">{Math.round(scale * 100)}%</span>
          <button onClick={zoomIn} className="w-6 h-6 flex items-center justify-center text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded">
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-auto p-4 flex flex-col items-center gap-3">
        {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
          <div
            key={pageNum}
            ref={(el) => { pageRefs.current[pageNum - 1] = el }}
            className="bg-white shadow-sm rounded-sm shrink-0"
          >
            <canvas data-page={pageNum} className="block rounded-sm" />
          </div>
        ))}
      </div>
    </div>
  )
}
