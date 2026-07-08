export interface AnalogChannel {
  index: number
  name: string
  phase: string
  component: string
  unit: string
  a: number
  b: number
  skew: number
  minVal: number
  maxVal: number
  primary: number
  secondary: number
  ps: string
}

export interface DigitalChannel {
  index: number
  name: string
  phase: string
  component: string
  normalState: number
}

export interface Cfg {
  stationName: string
  recDevId: string
  revYear: string
  totalChannels: number
  analogChannels: number
  digitalChannels: number
  analogChannelInfo: AnalogChannel[]
  digitalChannelInfo: DigitalChannel[]
  frequency: number
  samplingRates: Array<{ rate: number; endSample: number }>
  firstDataTimestamp: string
  triggerTimestamp: string
  dataFileType: string
  timeMultiplier: number
}

export interface Sample {
  sequence: number
  timestampMs: number
  analogValues: Float64Array
  digitalValues: Uint8Array
}

export interface ComtradeRecording {
  cfg: Cfg
  samples: Sample[]
  hdrText: string | null
}

export interface HdrData {
  rawText: string
  deviceInfo: Record<string, string>
  tripInfo: Array<{ time: string; element: string; phase: string }>
  digitalEvents: Array<{ time: string; channel: string; state: string }>
  settings: Array<{ name: string; value: string; unit: string }>
  rawSections: Array<{ title: string; content: string; type: 'table' | 'text' }>
}

export type DeviceType = 'line' | 'transformer' | 'busbar' | 'unknown'
