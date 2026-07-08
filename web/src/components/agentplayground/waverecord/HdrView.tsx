import { useState } from 'react'
import { useWaveformStore, deviceDisplayName } from './comtrade/store'
import { ChevronDown, ChevronRight, FileText } from 'lucide-react'

function parsePipeTable(text: string): { headers: string[]; rows: string[][] } | null {
  const lines = text.split('\n').filter(l => l.trim())
  if (lines.length < 2) return null
  const headers = lines[0].split('|').map(s => s.trim())
  if (headers.length === 0) return null
  const colCount = headers.length
  const rows = lines.slice(1).map(l => {
    const cells = l.split('|').map(s => s.trim())
    while (cells.length < colCount) cells.push('')
    return cells.slice(0, colCount)
  })
  return { headers, rows }
}

function TableDisplay({ content }: { content: string }) {
  const parsed = parsePipeTable(content)
  if (!parsed) {
    return (
      <pre className="text-xs whitespace-pre-wrap bg-gray-50 p-2 rounded-md m-0">{content}</pre>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {parsed.headers.map((h, i) => (
              <th key={i} className="border border-gray-200 px-2 py-1 bg-gray-50 text-left whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {parsed.rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci} className="border border-gray-200 px-2 py-1 whitespace-nowrap">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function HdrView() {
  const devices = useWaveformStore(s => s.devices)
  const selectedDeviceId = useWaveformStore(s => s.selectedDeviceId)
  const setSelectedDeviceId = useWaveformStore(s => s.setSelectedDeviceId)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())

  const device = devices.find(d => d.id === selectedDeviceId) || devices[0]

  const toggleSection = (key: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const expandAll = () => {
    if (!device?.hdrData) return
    setExpandedSections(new Set(device.hdrData.rawSections.map((_, i) => String(i))))
  }

  const collapseAll = () => {
    setExpandedSections(new Set())
  }

  if (devices.length === 0) {
    return (
      <div className="p-6 text-center text-gray-400">
        <FileText className="w-10 h-10 mx-auto mb-2 opacity-30" />
        <div className="text-sm">请先上传录波文件</div>
      </div>
    )
  }

  if (!device?.hdrData) {
    return (
      <div className="p-4 h-full overflow-auto">
        <select
          value={device?.id || ''}
          onChange={(e) => setSelectedDeviceId(e.target.value)}
          className="w-full mb-4 px-3 py-1.5 text-sm border border-gray-200 rounded-md bg-white focus:outline-none focus:border-teal-400"
        >
          {devices.map(d => (
            <option key={d.id} value={d.id}>{deviceDisplayName(d)}</option>
          ))}
        </select>
        <div className="text-center text-gray-400">
          <FileText className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <div className="text-sm">该装置无 HDR 数据</div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-4 h-full overflow-auto">
      <div className="flex items-center gap-2 mb-4">
        <select
          value={device.id}
          onChange={(e) => setSelectedDeviceId(e.target.value)}
          className="flex-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md bg-white focus:outline-none focus:border-teal-400"
        >
          {devices.map(d => (
            <option key={d.id} value={d.id}>{`${d.station} - ${d.setName}`}</option>
          ))}
        </select>
        <button
          onClick={expandAll}
          className="px-2 py-1.5 text-xs text-gray-600 hover:text-teal-600 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors"
        >
          展开
        </button>
        <button
          onClick={collapseAll}
          className="px-2 py-1.5 text-xs text-gray-600 hover:text-teal-600 border border-gray-200 rounded-md hover:bg-gray-50 transition-colors"
        >
          折叠
        </button>
      </div>

      <div className="space-y-1">
        {device.hdrData.rawSections.map((section, idx) => {
          const key = String(idx)
          const isExpanded = expandedSections.has(key)
          return (
            <div key={idx} className="border border-gray-200 rounded-md overflow-hidden">
              <button
                onClick={() => toggleSection(key)}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-gray-400" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-gray-400" />
                )}
                <span>{section.title}</span>
              </button>
              {isExpanded && (
                <div className="px-3 pb-3 border-t border-gray-100">
                  {section.type === 'table' ? (
                    <TableDisplay content={section.content} />
                  ) : (
                    <div className="whitespace-pre-wrap text-sm mt-2">{section.content}</div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
