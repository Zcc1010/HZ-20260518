import { useMemo, useState } from 'react'
import { useWaveformStore } from './comtrade/store'
import { Zap, Download, Loader2, Scissors } from 'lucide-react'

export default function SubagentExtract() {
  const devices = useWaveformStore(s => s.devices)
  const selectedId = useWaveformStore(s => s.selectedDeviceId)
  const setSelectedId = useWaveformStore(s => s.setSelectedDeviceId)
  const [extractResults, setExtractResults] = useState<Record<string, { loading: boolean; error: string; data: any }>>({})
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number; running: boolean }>({ current: 0, total: 0, running: false })

  const deviceOptions = useMemo(() =>
    devices.map(d => ({
      value: d.id,
      label: d.fileName.replace(/\.[^.]+$/, ''),
    })),
    [devices]
  )

  const handleGenerate = async (deviceId: string) => {
    const device = devices.find(d => d.id === deviceId)
    if (!device) return

    setExtractResults(prev => ({
      ...prev,
      [deviceId]: { loading: true, error: '', data: null }
    }))

    try {
      // TODO: Implement extraction logic using AI
      // For now, show a placeholder
      setExtractResults(prev => ({
        ...prev,
        [deviceId]: { loading: false, error: '', data: null }
      }))
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err)
      setExtractResults(prev => ({
        ...prev,
        [deviceId]: { loading: false, error: errMsg, data: null }
      }))
    }
  }

  const handleGenerateAll = async () => {
    setBatchProgress({ current: 0, total: devices.length, running: true })
    for (let i = 0; i < devices.length; i++) {
      const device = devices[i]
      setBatchProgress({ current: i + 1, total: devices.length, running: true })
      setSelectedId(device.id)
      await handleGenerate(device.id)
    }
    setBatchProgress({ current: 0, total: 0, running: false })
  }

  if (devices.length === 0) {
    return (
      <div className="p-6 text-center text-gray-400">
        <Scissors className="w-10 h-10 mx-auto mb-2 opacity-30" />
        <div className="text-sm">请先上传录波文件</div>
      </div>
    )
  }

  const currentResult = selectedId ? extractResults[selectedId] : null
  const selectedDevice = devices.find(d => d.id === selectedId)

  return (
    <div className="h-full flex flex-col text-xs">
      <div className="px-3 py-2 border-b border-gray-100 flex gap-2 items-center shrink-0">
        <select
          value={selectedId || ''}
          onChange={(e) => setSelectedId(e.target.value)}
          className="flex-1 px-2 py-1 text-xs border border-gray-200 rounded-md bg-white focus:outline-none focus:border-teal-400"
        >
          <option value="">选择装置</option>
          {deviceOptions.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <button
          onClick={() => selectedId && handleGenerate(selectedId)}
          disabled={!selectedId || currentResult?.loading}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-teal-600 text-white rounded-md hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {currentResult?.loading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <Zap className="w-3 h-3" />
          )}
          提取
        </button>
        <button
          onClick={handleGenerateAll}
          disabled={devices.length === 0 || batchProgress.running}
          className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-gray-200 text-gray-600 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {batchProgress.running ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : null}
          全部提取
        </button>
        {batchProgress.running && (
          <span className="inline-flex items-center px-1.5 py-0.5 text-[10px] bg-blue-50 text-blue-600 rounded">
            {batchProgress.current}/{batchProgress.total}
          </span>
        )}
        {selectedDevice && currentResult?.data && (
          <button
            onClick={() => {
              const baseName = selectedDevice.fileName.replace(/\.[^.]+$/, '')
              const blob = new Blob([JSON.stringify(currentResult.data, null, 2)], { type: 'application/json' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = baseName + '.extract.json'
              a.click()
              URL.revokeObjectURL(url)
            }}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs border border-gray-200 text-gray-600 rounded-md hover:bg-gray-50 transition-colors"
          >
            <Download className="w-3 h-3" />
            下载
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {!selectedId && (
          <div className="text-gray-400 text-xs p-4">
            选择一个装置后点击"提取"，AI 将提取该装置的信息。
          </div>
        )}
        {selectedId && currentResult?.loading && (
          <div className="text-center p-10">
            <Loader2 className="w-8 h-8 mx-auto mb-2 animate-spin text-teal-500" />
            <span className="text-xs text-gray-500">
              正在提取 {selectedDevice?.fileName.replace(/\.[^.]+$/, '')} ...
            </span>
          </div>
        )}
        {selectedId && currentResult && !currentResult.loading && currentResult.error && !currentResult.data && (
          <div>
            <div className="bg-red-50 border border-red-200 rounded-md p-3 text-xs text-red-600">
              {currentResult.error}
            </div>
          </div>
        )}
        {selectedId && !currentResult && (
          <div className="text-gray-400 text-xs p-4">
            点击"提取"生成该装置的段落信息。
          </div>
        )}
      </div>
    </div>
  )
}
