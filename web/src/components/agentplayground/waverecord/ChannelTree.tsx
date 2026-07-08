import { useState } from 'react'
import { useWaveformStore, deviceDisplayName } from './comtrade/store'
import { ChevronDown, ChevronRight, Radio } from 'lucide-react'

export default function ChannelTree() {
  const devices = useWaveformStore(s => s.devices)
  const selectedChannelIds = useWaveformStore(s => s.selectedChannelIds)
  const toggleChannel = useWaveformStore(s => s.toggleChannel)
  const setDeviceChannels = useWaveformStore(s => s.setDeviceChannels)
  const [expandedDevices, setExpandedDevices] = useState<Set<string>>(new Set())

  const toggleDevice = (id: string) => {
    setExpandedDevices(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (devices.length === 0) {
    return (
      <div className="p-4 text-center text-gray-400 text-xs">
        <Radio className="w-8 h-8 mx-auto mb-2 opacity-30" />
        <div>请先上传录波文件</div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto py-1">
      {devices.map(device => {
        const isExpanded = expandedDevices.has(device.id)
        const allChannelIds = [
          ...device.cfg.analogChannelInfo.map((_, i) => `${device.id}:a:${i}`),
          ...device.cfg.digitalChannelInfo.map((_, i) => `${device.id}:d:${i}`),
        ]
        const selectedCount = allChannelIds.filter(id => selectedChannelIds.has(id)).length
        const allSelected = selectedCount === allChannelIds.length

        return (
          <div key={device.id} className="mb-0.5">
            <div
              className="flex items-center gap-1 px-2 py-1.5 cursor-pointer hover:bg-gray-50 transition-colors"
              onClick={() => toggleDevice(device.id)}
            >
              {isExpanded ? (
                <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
              )}
              <span className="flex-1 text-xs font-medium text-gray-700 truncate">
                {deviceDisplayName(device)}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setDeviceChannels(device.id, !allSelected)
                }}
                className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                  allSelected
                    ? 'bg-teal-100 text-teal-700'
                    : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                }`}
              >
                {allSelected ? '全选' : `${selectedCount}/${allChannelIds.length}`}
              </button>
            </div>

            {isExpanded && (
              <div className="ml-4 border-l border-gray-100">
                {device.cfg.analogChannelInfo.length > 0 && (
                  <div>
                    <div className="px-2 py-1 text-[10px] text-gray-400 font-medium">模拟通道</div>
                    {device.cfg.analogChannelInfo.map((ch, i) => {
                      const channelId = `${device.id}:a:${i}`
                      const isSelected = selectedChannelIds.has(channelId)
                      return (
                        <label
                          key={channelId}
                          className={`flex items-center gap-1.5 px-2 py-1 cursor-pointer transition-colors ${
                            isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleChannel(channelId)}
                            className="w-3 h-3 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                          />
                          <span className="text-[11px] text-gray-600 truncate">
                            {ch.name.trim()}
                          </span>
                          {ch.unit && (
                            <span className="text-[10px] text-gray-400 ml-auto">({ch.unit})</span>
                          )}
                        </label>
                      )
                    })}
                  </div>
                )}
                {device.cfg.digitalChannelInfo.length > 0 && (
                  <div>
                    <div className="px-2 py-1 text-[10px] text-gray-400 font-medium">数字通道</div>
                    {device.cfg.digitalChannelInfo.map((ch, i) => {
                      const channelId = `${device.id}:d:${i}`
                      const isSelected = selectedChannelIds.has(channelId)
                      return (
                        <label
                          key={channelId}
                          className={`flex items-center gap-1.5 px-2 py-1 cursor-pointer transition-colors ${
                            isSelected ? 'bg-blue-50' : 'hover:bg-gray-50'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleChannel(channelId)}
                            className="w-3 h-3 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                          />
                          <span className="text-[11px] text-gray-600 truncate">
                            {ch.name.trim()}
                          </span>
                        </label>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
