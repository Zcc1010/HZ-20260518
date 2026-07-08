import { create } from 'zustand'
import type { Cfg, Sample, HdrData, DeviceType } from './types'
import type { MutationResult } from './mutation'
import type { DigitalEvent } from './event'

export interface DeviceData {
  id: string
  station: string
  setName: string
  cfg: Cfg
  samples: Sample[]
  hdrData: HdrData | null
  deviceType: DeviceType
  mutations: MutationResult[]
  events: DigitalEvent[]
  fileName: string
  filePath: string
  voltage: string
  protectionType: string
  deviceName: string
  model: string
  softwareVersion: string
  timeOffsetMs: number
  alignmentRefMs: number | null
}

export type MiddleTab = 'waveform' | 'hdr' | 'extract'

export function deviceDisplayName(d: DeviceData): string {
  return d.fileName || '未知装置'
}

export function isFaultRecorder(d: DeviceData): boolean {
  const recDevId = (d.cfg.recDevId || '').toLowerCase()
  const filePath = (d.filePath || '').toLowerCase()
  const fileName = (d.fileName || '').toLowerCase()
  return recDevId.includes('录波器') || filePath.includes('故障录波') || fileName.includes('录波器') || filePath.includes('recorder')
}

interface WaveformState {
  devices: DeviceData[]
  selectedChannelIds: Set<string>
  middleTab: MiddleTab
  selectedDeviceId: string | null

  addDevice: (device: DeviceData) => void
  removeDevice: (id: string) => void
  clearDevices: () => void
  toggleChannel: (channelId: string) => void
  setDeviceChannels: (deviceId: string, selected: boolean) => void
  setMiddleTab: (tab: MiddleTab) => void
  setSelectedDeviceId: (id: string | null) => void
  updateDeviceMeta: (id: string, meta: Partial<DeviceData>) => void
  setTimeOffset: (id: string, offsetMs: number) => void
}

export const useWaveformStore = create<WaveformState>((set) => ({
  devices: [],
  selectedChannelIds: new Set<string>(),
  middleTab: 'waveform',
  selectedDeviceId: null,

  addDevice: (device) => set((state) => ({ devices: [...state.devices, device] })),
  removeDevice: (id) => set((state) => {
    const device = state.devices.find(d => d.id === id)
    if (!device) return state
    const next = new Set(state.selectedChannelIds)
    device.cfg.analogChannelInfo.forEach((_, i) => next.delete(`${id}:a:${i}`))
    device.cfg.digitalChannelInfo.forEach((_, i) => next.delete(`${id}:d:${i}`))
    return { devices: state.devices.filter(d => d.id !== id), selectedChannelIds: next }
  }),
  clearDevices: () => set({ devices: [], selectedChannelIds: new Set() }),

  toggleChannel: (channelId) => set((state) => {
    const next = new Set(state.selectedChannelIds)
    if (next.has(channelId)) next.delete(channelId)
    else next.add(channelId)
    return { selectedChannelIds: next }
  }),

  setDeviceChannels: (deviceId, selected) => set((state) => {
    const next = new Set(state.selectedChannelIds)
    const device = state.devices.find(d => d.id === deviceId)
    if (!device) return state
    const allIds = [
      ...device.cfg.analogChannelInfo.map((_, i) => `${deviceId}:a:${i}`),
      ...device.cfg.digitalChannelInfo.map((_, i) => `${deviceId}:d:${i}`),
    ]
    if (selected) allIds.forEach(id => next.add(id))
    else allIds.forEach(id => next.delete(id))
    return { selectedChannelIds: next }
  }),

  setMiddleTab: (tab) => set({ middleTab: tab }),
  setSelectedDeviceId: (id) => set({ selectedDeviceId: id }),
  updateDeviceMeta: (id, meta) => set((state) => ({
    devices: state.devices.map(d => d.id === id ? { ...d, ...meta } : d),
  })),
  setTimeOffset: (id, offsetMs) => set((state) => ({
    devices: state.devices.map(d => d.id === id ? { ...d, timeOffsetMs: offsetMs } : d),
  })),
}))
