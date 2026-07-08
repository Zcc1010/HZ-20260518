import { useRef, useEffect, useMemo, useState } from 'react'
import type { Cfg, Sample } from './comtrade/types'
import { computeRmsAtPoint } from './comtrade/rms'

export interface ChannelSpec {
  deviceId: string
  deviceName: string
  type: 'analog' | 'digital'
  channelIndex: number
  name: string
  unit: string
  color: string
}

export interface ChannelData {
  spec: ChannelSpec
  cfg: Cfg
  samples: Sample[]
  triggerOffsetMs: number
  timeOffsetMs: number
}

interface Props {
  channels: ChannelData[]
  cursorTimeMs?: number | null
  onCursorMove?: (timeMs: number | null) => void
  onHoverTimeChange?: (timeStr: string | null) => void
}

const ROW_HEIGHT = 80
const LABEL_WIDTH = 120

interface YScale { min: number; max: number }
interface TimeWindow { startMs: number; endMs: number }
interface RowLayout { channel: ChannelData; y: number; height: number }

function absMs(ch: ChannelData, sampleIdx: number): number {
  return ch.triggerOffsetMs + ch.samples[sampleIdx].timestampMs + ch.timeOffsetMs
}

function computeScales(channels: ChannelData[]): Map<string, YScale> {
  const unitGroups = new Map<string, { maxAbs: number }>()
  for (const ch of channels) {
    if (ch.spec.type !== 'analog') continue
    const unit = ch.spec.unit.toLowerCase()
    if (!unit) continue
    if (!unitGroups.has(unit)) unitGroups.set(unit, { maxAbs: 0 })
  }
  for (const ch of channels) {
    if (ch.spec.type !== 'analog') continue
    const unit = ch.spec.unit.toLowerCase()
    if (!unit) continue
    const group = unitGroups.get(unit)!
    for (let i = 0; i < ch.samples.length; i++) {
      const v = Math.abs(ch.samples[i].analogValues[ch.spec.channelIndex])
      if (v > group.maxAbs) group.maxAbs = v
    }
  }
  const scales = new Map<string, YScale>()
  for (const ch of channels) {
    if (ch.spec.type !== 'analog') continue
    const unit = ch.spec.unit.toLowerCase()
    if (!unit) {
      let maxAbs = 0
      for (let i = 0; i < ch.samples.length; i++) {
        const v = Math.abs(ch.samples[i].analogValues[ch.spec.channelIndex])
        if (v > maxAbs) maxAbs = v
      }
      const range = Math.max(maxAbs * 1.2, 0.001)
      scales.set(ch.spec.deviceId + ':' + ch.spec.channelIndex, { min: -range, max: range })
    } else {
      const group = unitGroups.get(unit)!
      const range = Math.max(group.maxAbs * 1.2, 0.001)
      scales.set(unit, { min: -range, max: range })
    }
  }
  return scales
}

function formatAbsTime(triggerTimestamp: string, absoluteMs: number): string {
  if (!triggerTimestamp) return `${absoluteMs.toFixed(3)}ms`
  const parts = triggerTimestamp.split(',')
  const dateStr = parts[0] || ''
  const formatted = dateStr.replace(/^(\d{2})(\d{2})(\d{2})$/, '20$1-$2-$3')
  const totalMs = absoluteMs
  const h = Math.floor(totalMs / 3600000) % 24
  const m = Math.floor((totalMs % 3600000) / 60000)
  const s = Math.floor((totalMs % 60000) / 1000)
  const ms = Math.round(totalMs % 1000)
  return `${formatted} ${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

function findSampleBeforeAbsMs(ch: ChannelData, targetMs: number): number {
  const samples = ch.samples
  const offset = ch.triggerOffsetMs + ch.timeOffsetMs
  let lo = 0, hi = samples.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (offset + samples[mid].timestampMs <= targetMs) lo = mid
    else hi = mid - 1
  }
  return lo
}

function findSampleRangeAbs(ch: ChannelData, startMs: number, endMs: number): [number, number] {
  if (ch.samples.length === 0) return [0, -1]
  const s = findSampleBeforeAbsMs(ch, startMs)
  const e = findSampleBeforeAbsMs(ch, endMs)
  if (e < s) return [0, -1]
  return [s, Math.min(ch.samples.length - 1, e)]
}

function drawCanvas(
  ctx: CanvasRenderingContext2D,
  canvasWidth: number,
  canvasHeight: number,
  rowLayouts: RowLayout[],
  scales: Map<string, YScale>,
  timeWindow: TimeWindow | null,
  cursorTimeMs: number | null,
) {
  const w = canvasWidth
  const plotWidth = w - LABEL_WIDTH
  ctx.clearRect(0, 0, w, canvasHeight)

  const tw = timeWindow
  if (!tw || tw.endMs <= tw.startMs) return
  const twRange = tw.endMs - tw.startMs

  for (let i = 0; i < rowLayouts.length; i++) {
    const { channel: ch, y: rowY, height: rowH } = rowLayouts[i]
    const { spec, cfg, samples, triggerOffsetMs } = ch
    ctx.save()
    ctx.translate(0, rowY)

    const [startIdx, endIdx] = findSampleRangeAbs(ch, tw.startMs, tw.endMs)
    if (endIdx <= startIdx) {
      ctx.fillStyle = i % 2 === 0 ? '#fff' : '#fafbfc'
      ctx.fillRect(0, 0, w, rowH)
      ctx.fillStyle = '#999'
      ctx.font = '10px monospace'
      ctx.textAlign = 'left'
      const displayName = spec.deviceName.length > 8 ? spec.deviceName.substring(0, 8) + '..' : spec.deviceName
      ctx.fillText(`${displayName}/${spec.name}`, 4, 12)
      ctx.fillStyle = '#ccc'
      ctx.fillText('无数据', 4, 24)
      ctx.restore()
      continue
    }

    const localStartMs = triggerOffsetMs + ch.timeOffsetMs + samples[startIdx].timestampMs
    const localEndMs = triggerOffsetMs + ch.timeOffsetMs + samples[endIdx].timestampMs
    if (localEndMs <= localStartMs) { ctx.restore(); continue }

    ctx.fillStyle = i % 2 === 0 ? '#fff' : '#fafbfc'
    ctx.fillRect(0, 0, w, rowH)

    ctx.strokeStyle = '#e8e8e8'
    ctx.lineWidth = 0.5
    ctx.beginPath()
    ctx.moveTo(LABEL_WIDTH, rowH / 2)
    ctx.lineTo(w, rowH / 2)
    ctx.stroke()

    ctx.strokeStyle = '#f0f0f0'
    ctx.beginPath()
    ctx.moveTo(0, rowH - 0.5)
    ctx.lineTo(w, rowH - 0.5)
    ctx.stroke()

    let rmsText = ''
    if (cursorTimeMs != null && spec.type === 'analog') {
      const spc = Math.round((cfg.samplingRates[0]?.rate || 192) / cfg.frequency)
      const sampleIdx = findSampleBeforeAbsMs(ch, cursorTimeMs)
      const rms = computeRmsAtPoint(samples, spec.channelIndex, sampleIdx, spc)
      rmsText = `有效值:${rms.toFixed(2)}${spec.unit ? spec.unit : ''}`
    }

    ctx.fillStyle = '#333'
    ctx.font = '10px monospace'
    ctx.textAlign = 'left'
    const displayName = spec.deviceName.length > 8 ? spec.deviceName.substring(0, 8) + '..' : spec.deviceName
    ctx.fillText(`${displayName}/${spec.name}${spec.unit ? '(' + spec.unit + ')' : ''}`, 4, 12)

    if (rmsText) {
      ctx.fillStyle = '#1677ff'
      ctx.fillText(rmsText, 4, 24)
    }

    ctx.strokeStyle = spec.color
    ctx.lineWidth = 1
    ctx.beginPath()

    if (spec.type === 'analog') {
      const scaleKey = spec.unit.toLowerCase() || (spec.deviceId + ':' + spec.channelIndex)
      const scale = scales.get(scaleKey) || { min: -1, max: 1 }
      const yRange = Math.max(scale.max - scale.min, 0.001)
      const padding = 6

      for (let si = startIdx; si <= endIdx; si++) {
        const absT = triggerOffsetMs + ch.timeOffsetMs + samples[si].timestampMs
        const t = (absT - tw.startMs) / twRange
        const x = LABEL_WIDTH + t * plotWidth
        const v = samples[si].analogValues[spec.channelIndex]
        const normalized = (v - scale.min) / yRange
        const y = rowH - padding - normalized * (rowH - 2 * padding)
        if (si === startIdx) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
    } else {
      const padding = Math.min(10, rowH / 4)
      for (let si = startIdx; si <= endIdx; si++) {
        const absT = triggerOffsetMs + ch.timeOffsetMs + samples[si].timestampMs
        const t = (absT - tw.startMs) / twRange
        const x = LABEL_WIDTH + t * plotWidth
        const v = samples[si].digitalValues[spec.channelIndex]
        const y = rowH - padding - v * (rowH - 2 * padding)
        if (si === startIdx) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      }
    }
    ctx.stroke()
    ctx.restore()
  }

  if (cursorTimeMs != null && rowLayouts.length > 0) {
    const t = (cursorTimeMs - tw.startMs) / twRange
    const cx = LABEL_WIDTH + t * plotWidth
    if (cx >= LABEL_WIDTH && cx <= w) {
      ctx.strokeStyle = '#ff4d4f'
      ctx.lineWidth = 1
      ctx.setLineDash([4, 4])
      ctx.beginPath()
      ctx.moveTo(cx, 0)
      ctx.lineTo(cx, canvasHeight)
      ctx.stroke()
      ctx.setLineDash([])
    }
  }
}

export default function WaveformCanvas({ channels, cursorTimeMs, onCursorMove, onHoverTimeChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{ startX: number; windowStartMs: number } | null>(null)
  const timeWindowRef = useRef<TimeWindow | null>(null)
  const rafRef = useRef<number>(0)

  const totalHeight = Math.max(channels.reduce((sum, ch) => sum + (ch.spec.type === 'digital' ? ROW_HEIGHT / 2 : ROW_HEIGHT), 0), ROW_HEIGHT)
  const scales = useMemo(() => computeScales(channels), [channels])

  const rowLayouts = useMemo((): RowLayout[] => {
    const layouts: RowLayout[] = []
    let y = 0
    for (const ch of channels) {
      const h = ch.spec.type === 'digital' ? ROW_HEIGHT / 2 : ROW_HEIGHT
      layouts.push({ channel: ch, y, height: h })
      y += h
    }
    return layouts
  }, [channels])
  const [tick, setTick] = useState(0)

  const globalTimeRange = useMemo((): { minMs: number; maxMs: number } | null => {
    if (channels.length === 0) return null
    let minMs = Infinity, maxMs = -Infinity
    for (const ch of channels) {
      if (ch.samples.length === 0) continue
      const first = absMs(ch, 0)
      const last = absMs(ch, ch.samples.length - 1)
      if (first < minMs) minMs = first
      if (last > maxMs) maxMs = last
    }
    if (minMs >= maxMs) return null
    return { minMs, maxMs }
  }, [channels])

  const initialTimeWindow = useMemo((): TimeWindow | null => {
    if (!globalTimeRange) return null
    const startMs = globalTimeRange.minMs
    const endMs = startMs + 300
    return { startMs, endMs: Math.min(endMs, globalTimeRange.maxMs) }
  }, [globalTimeRange])

  useEffect(() => {
    timeWindowRef.current = initialTimeWindow
    setTick(t => t + 1)
  }, [initialTimeWindow])

  useEffect(() => {
    if (cursorTimeMs != null && rowLayouts.length > 0) {
      const cfg = channels[0].cfg
      onHoverTimeChange?.(formatAbsTime(cfg.triggerTimestamp, cursorTimeMs))
    } else {
      onHoverTimeChange?.(null)
    }
  }, [cursorTimeMs, channels, onHoverTimeChange])

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const fullWidth = container.clientWidth
    if (fullWidth <= 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = fullWidth * dpr
    canvas.height = totalHeight * dpr
    canvas.style.width = `${fullWidth}px`
    canvas.style.height = `${totalHeight}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    drawCanvas(ctx, fullWidth, totalHeight, rowLayouts, scales, timeWindowRef.current, cursorTimeMs ?? null)
  }, [channels, scales, totalHeight, cursorTimeMs, tick])

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container || !globalTimeRange) return

    const plotWidth = () => container.clientWidth - LABEL_WIDTH

    const onMouseMove = (e: MouseEvent) => {
      if (dragRef.current) return
      const rect = canvas.getBoundingClientRect()
      const x = e.clientX - rect.left
      const pw = plotWidth()
      if (pw <= 0) return
      const tw = timeWindowRef.current
      if (!tw) return
      if (x < LABEL_WIDTH) { onCursorMove?.(null); return }
      const t = (x - LABEL_WIDTH) / pw
      onCursorMove?.(tw.startMs + t * (tw.endMs - tw.startMs))

      cancelAnimationFrame(rafRef.current)
      rafRef.current = requestAnimationFrame(() => setTick(t => t + 1))
    }

    const onMouseLeave = () => {
      onCursorMove?.(null)
      setTick(t => t + 1)
    }

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 0) return
      const tw = timeWindowRef.current
      if (!tw) return
      dragRef.current = { startX: e.clientX, windowStartMs: tw.startMs }
      canvas.style.cursor = 'grabbing'
    }

    const onDragMove = (e: MouseEvent) => {
      if (!dragRef.current) return
      const pw = plotWidth()
      if (pw <= 0) return
      const tw = timeWindowRef.current
      if (!tw) return
      const durationMs = tw.endMs - tw.startMs
      const dx = e.clientX - dragRef.current.startX
      const shiftMs = (-dx / pw) * durationMs
      let newStartMs = dragRef.current.windowStartMs + shiftMs
      const maxStartMs = globalTimeRange.maxMs - durationMs
      newStartMs = Math.max(globalTimeRange.minMs, Math.min(newStartMs, maxStartMs))
      let newEndMs = newStartMs + durationMs
      if (newEndMs > globalTimeRange.maxMs) { newEndMs = globalTimeRange.maxMs; newStartMs = newEndMs - durationMs }
      if (newStartMs < globalTimeRange.minMs) { newStartMs = globalTimeRange.minMs; newEndMs = newStartMs + durationMs }
      timeWindowRef.current = { startMs: newStartMs, endMs: newEndMs }
      setTick(t => t + 1)
    }

    const onDragUp = () => {
      if (!dragRef.current) return
      dragRef.current = null
      canvas.style.cursor = 'crosshair'
    }

    canvas.addEventListener('mousemove', onMouseMove)
    canvas.addEventListener('mouseleave', onMouseLeave)
    canvas.addEventListener('mousedown', onMouseDown)
    window.addEventListener('mousemove', onDragMove)
    window.addEventListener('mouseup', onDragUp)
    return () => {
      canvas.removeEventListener('mousemove', onMouseMove)
      canvas.removeEventListener('mouseleave', onMouseLeave)
      canvas.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('mousemove', onDragMove)
      window.removeEventListener('mouseup', onDragUp)
    }
  }, [channels, onCursorMove, globalTimeRange])

  if (channels.length === 0) {
    return (
      <div className="flex items-center justify-center text-gray-400 text-sm min-h-full">
        请在左侧通道树勾选通道以显示波形
      </div>
    )
  }

  return (
    <div ref={containerRef}>
      <canvas
        ref={canvasRef}
        style={{ cursor: 'crosshair', display: 'block' }}
      />
    </div>
  )
}
