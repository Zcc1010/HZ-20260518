import type { Cfg } from './types'

export function parseCfg(text: string): Cfg {
  const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0)
  const cfg: Cfg = {
    stationName: '',
    recDevId: '',
    revYear: '',
    totalChannels: 0,
    analogChannels: 0,
    digitalChannels: 0,
    analogChannelInfo: [],
    digitalChannelInfo: [],
    frequency: 50.0,
    samplingRates: [],
    firstDataTimestamp: '',
    triggerTimestamp: '',
    dataFileType: 'ASCII',
    timeMultiplier: 1.0,
  }

  if (lines.length === 0) return cfg

  // Line 1: station, device ID, revision year
  const p1 = lines[0].split(',').map(s => s.trim())
  if (p1.length >= 3) {
    cfg.stationName = p1[0]
    cfg.recDevId = p1[1]
    cfg.revYear = p1[2]
  }

  // Line 2: analog count, digital count (e.g. "24A,48D")
  if (lines.length >= 2) {
    const m = lines[1].match(/(\d+)\s*[Aa]\s*,\s*(\d+)\s*[Dd]/)
    if (m) {
      cfg.analogChannels = parseInt(m[1])
      cfg.digitalChannels = parseInt(m[2])
    }
    cfg.totalChannels = cfg.analogChannels + cfg.digitalChannels
  }

  let idx = 2

  // Analog channels (13 comma-separated fields each)
  for (let i = 0; i < cfg.analogChannels && idx < lines.length; i++, idx++) {
    const p = lines[idx].split(',').map(s => s.trim())
    if (p.length < 13) continue
    cfg.analogChannelInfo.push({
      index: parseInt(p[0]) || i + 1,
      name: p[1],
      phase: p[2] ?? '',
      component: p[3] ?? '',
      unit: p[4] ?? '',
      a: parseFloat(p[5]) || 1,
      b: parseFloat(p[6]) || 0,
      skew: parseFloat(p[7]) || 0,
      minVal: parseInt(p[8]) || -32768,
      maxVal: parseInt(p[9]) || 32767,
      primary: parseFloat(p[10]) || 1,
      secondary: parseFloat(p[11]) || 1,
      ps: p[12] ?? 'S',
    })
  }

  // Digital channels (5 fields each)
  for (let i = 0; i < cfg.digitalChannels && idx < lines.length; i++, idx++) {
    const p = lines[idx].split(',').map(s => s.trim())
    if (p.length < 5) continue
    cfg.digitalChannelInfo.push({
      index: parseInt(p[0]) || i + 1,
      name: p[1],
      phase: p[2] ?? '',
      component: p[3] ?? '',
      normalState: parseInt(p[4]) || 0,
    })
  }

  // Frequency
  if (idx < lines.length) {
    cfg.frequency = parseFloat(lines[idx]) || 50.0
    idx++
  }

  // Sampling rate count
  let nrates = 1
  if (idx < lines.length && /^\d+$/.test(lines[idx].trim())) {
    nrates = parseInt(lines[idx]) || 1
    idx++
  }

  // Sampling rates
  for (let i = 0; i < nrates && idx < lines.length; i++, idx++) {
    const p = lines[idx].split(',').map(s => s.trim())
    if (p.length >= 2) {
      cfg.samplingRates.push({
        rate: parseFloat(p[0]),
        endSample: parseInt(p[1]),
      })
    }
  }

  // First data timestamp
  if (idx < lines.length) { cfg.firstDataTimestamp = lines[idx].trim(); idx++ }
  // Trigger timestamp
  if (idx < lines.length) { cfg.triggerTimestamp = lines[idx].trim(); idx++ }
  // Data file type
  if (idx < lines.length) { cfg.dataFileType = lines[idx].trim().toUpperCase(); idx++ }
  // Time multiplier
  if (idx < lines.length) {
    const tm = parseFloat(lines[idx])
    if (!isNaN(tm)) cfg.timeMultiplier = tm
  }

  return cfg
}
