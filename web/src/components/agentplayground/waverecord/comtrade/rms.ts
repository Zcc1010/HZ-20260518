import type { Cfg, Sample } from './types'

export function getSamplesPerCycle(cfg: Cfg): number {
  return Math.round((cfg.samplingRates[0]?.rate || 192) / cfg.frequency)
}

export function computeRmsAtPoint(
  samples: Sample[],
  channelIndex: number,
  center: number,
  samplesPerCycle: number
): number {
  const half = Math.floor(samplesPerCycle / 2)
  const start = Math.max(0, center - half)
  const end = Math.min(samples.length, center + half)
  let sq = 0
  for (let j = start; j < end; j++) {
    const v = samples[j].analogValues[channelIndex]
    sq += v * v
  }
  return Math.sqrt(sq / samplesPerCycle)
}

export function computeRmsArray(
  samples: Sample[],
  channelIndex: number,
  samplesPerCycle: number
): Float64Array {
  const half = Math.floor(samplesPerCycle / 2)
  const n = samples.length
  const rms = new Float64Array(n)
  for (let i = half; i < n - half; i++) {
    let sq = 0
    for (let j = i - half; j < i + half; j++) {
      const v = samples[j].analogValues[channelIndex]
      sq += v * v
    }
    rms[i] = Math.sqrt(sq / samplesPerCycle)
  }
  return rms
}

export function computeRmsOverWindow(
  samples: Sample[],
  cfg: Cfg,
  startIdx: number,
  endIdx: number
): Float64Array[] {
  const spc = getSamplesPerCycle(cfg)
  const window = samples.slice(startIdx, endIdx)
  if (window.length < spc) return cfg.analogChannelInfo.map(() => new Float64Array(0))

  return cfg.analogChannelInfo.map((_, chIdx) => {
    return computeRmsArray(window, chIdx, spc)
  })
}

export function computeVisibleRms(
  samples: Sample[],
  cfg: Cfg,
  channelIndex: number,
  visibleStart: number,
  visibleEnd: number
): number {
  const spc = getSamplesPerCycle(cfg)
  const half = Math.floor(spc / 2)
  const start = Math.max(visibleStart + half, 0)
  const end = Math.min(visibleEnd - half, samples.length)

  if (end <= start) return 0

  let sqSum = 0
  for (let i = start; i < end; i++) {
    const v = samples[i].analogValues[channelIndex]
    sqSum += v * v
  }
  return Math.sqrt(sqSum / (end - start))
}
