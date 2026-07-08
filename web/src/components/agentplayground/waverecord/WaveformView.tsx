import { useMemo, useState } from 'react'
import WaveformCanvas from './WaveformCanvas'
import type { ChannelData } from './WaveformCanvas'
import { useWaveformStore, deviceDisplayName } from './comtrade/store'
import { ArrowLeftRight } from 'lucide-react'

const COLORS = [
  '#1677ff', '#52c41a', '#faad14', '#ff4d4f',
  '#722ed1', '#13c2c2', '#eb2f96', '#fa8c16',
]

function parseTriggerTimeOfDay(triggerTimestamp: string): number {
  if (!triggerTimestamp) return 0
  const parts = triggerTimestamp.split(',')
  const timeStr = parts[1] || parts[0]
  const secParts = timeStr.split(':')
  if (secParts.length < 3) return 0
  return (parseInt(secParts[0]) || 0) * 3600000
    + (parseInt(secParts[1]) || 0) * 60000
    + (parseFloat(secParts[2]) || 0) * 1000
}

export default function WaveformView() {
  const devices = useWaveformStore(s => s.devices)
  const selectedChannelIds = useWaveformStore(s => s.selectedChannelIds)
  const hasOffsets = devices.some(d => d.timeOffsetMs !== 0)
  const [useAligned, setUseAligned] = useState(false)
  const [cursorTimeMs, setCursorTimeMs] = useState<number | null>(null)
  const [hoverTime, setHoverTime] = useState<string | null>(null)

  const channels: ChannelData[] = useMemo(() => {
    const result: ChannelData[] = []
    let colorIdx = 0
    for (const device of devices) {
      const deviceName = deviceDisplayName(device)
      const triggerOffsetMs = parseTriggerTimeOfDay(device.cfg.triggerTimestamp)
      const offsetMs = useAligned ? device.timeOffsetMs : 0
      for (let i = 0; i < device.cfg.analogChannelInfo.length; i++) {
        const id = `${device.id}:a:${i}`
        if (selectedChannelIds.has(id)) {
          const ch = device.cfg.analogChannelInfo[i]
          result.push({
            spec: {
              deviceId: device.id, deviceName,
              type: 'analog', channelIndex: i,
              name: ch.name.trim(), unit: ch.unit?.trim() || '',
              color: COLORS[colorIdx++ % COLORS.length],
            },
            cfg: device.cfg, samples: device.samples, triggerOffsetMs, timeOffsetMs: offsetMs,
          })
        }
      }
      for (let i = 0; i < device.cfg.digitalChannelInfo.length; i++) {
        const id = `${device.id}:d:${i}`
        if (selectedChannelIds.has(id)) {
          const ch = device.cfg.digitalChannelInfo[i]
          result.push({
            spec: {
              deviceId: device.id, deviceName,
              type: 'digital', channelIndex: i,
              name: ch.name.trim(), unit: '',
              color: COLORS[colorIdx++ % COLORS.length],
            },
            cfg: device.cfg, samples: device.samples, triggerOffsetMs, timeOffsetMs: offsetMs,
          })
        }
      }
    }
    return result
  }, [devices, selectedChannelIds, useAligned])

  return (
    <div className="flex flex-col min-h-full relative overflow-visible">
      <div className="h-6 leading-6 pl-3 bg-gray-50 border-b border-gray-200 text-xs font-mono text-gray-400 shrink-0 sticky top-0 z-10 flex items-center">
        <span className="flex-1">{hoverTime || 'yyyy-MM-dd HH:mm:ss.SSS'}</span>
        {hasOffsets && (
          <button
            onClick={() => setUseAligned(!useAligned)}
            className={`text-[11px] px-2 flex items-center gap-1 h-full cursor-pointer ${useAligned ? 'text-blue-500' : 'text-gray-400'}`}
          >
            <ArrowLeftRight className="w-3 h-3" />
            {useAligned ? '对齐' : '原始'}
          </button>
        )}
      </div>
      <WaveformCanvas channels={channels} cursorTimeMs={cursorTimeMs} onCursorMove={setCursorTimeMs} onHoverTimeChange={setHoverTime} />
    </div>
  )
}
