import type { Cfg, Sample } from './types'
import { computeRmsArray } from './rms'

export interface MutationResult {
  channelIndex: number
  channelName: string
  firstPositive: { value: number; sampleIndex: number; timeMs: number } | null
  firstNegative: { value: number; sampleIndex: number; timeMs: number } | null
  intervalMs: number | null
  secondPositive: { value: number; sampleIndex: number; timeMs: number } | null
  secondNegative: { value: number; sampleIndex: number; timeMs: number } | null
}

export function detectMutations(
  samples: Sample[],
  cfg: Cfg,
  channelIndex: number
): MutationResult {
  const ch = cfg.analogChannelInfo[channelIndex]
  const spc = Math.round((cfg.samplingRates[0]?.rate || 192) / cfg.frequency)
  const half = Math.floor(spc / 2)
  const n = samples.length

  const rms = computeRmsArray(samples, channelIndex, spc)

  // diff[i] = rms[i + half] - rms[i - half], at sample point i
  const diffs: number[] = []
  for (let i = spc; i < n - half; i++) {
    diffs.push(rms[i + half] - rms[i - half])
  }

  if (diffs.length === 0) {
    return {
      channelIndex, channelName: ch?.name || `CH${channelIndex}`,
      firstPositive: null, firstNegative: null, intervalMs: null,
      secondPositive: null, secondNegative: null,
    }
  }

  let rmsMax = 0
  for (let i = half; i < n - half; i++) {
    if (rms[i] > rmsMax) rmsMax = rms[i]
  }
  const threshold = Math.max(rmsMax * 0.2, 0.01)

  const firstPos = findFirstPositive(diffs, threshold)
  const firstNeg = findFirstNegative(diffs, threshold)

  const toSampleIdx = (diffIdx: number) => diffIdx + spc

  let intervalMs: number | null = null
  if (firstPos && firstNeg) {
    const sampleRate = cfg.samplingRates[0]?.rate || 1200
    intervalMs = Math.abs(toSampleIdx(firstPos.index) - toSampleIdx(firstNeg.index)) * (1000 / sampleRate)
  }

  let secondPos: MutationResult['secondPositive'] = null
  let secondNeg: MutationResult['secondNegative'] = null

  if (firstPos && firstNeg) {
    const searchStart = Math.max(firstPos.index, firstNeg.index)
    const sp = findSecondPositive(diffs, threshold, searchStart)
    if (sp) {
      const sampleIdx = toSampleIdx(sp.index)
      secondPos = {
        value: sp.value,
        sampleIndex: sampleIdx,
        timeMs: samples[sampleIdx]?.timestampMs || 0,
      }
      const subDiffs = diffs.slice(sp.index + spc)
      const sn = findFirstNegative(subDiffs, threshold)
      if (sn) {
        const snSampleIdx = toSampleIdx(sp.index + spc + sn.index)
        secondNeg = {
          value: sn.value,
          sampleIndex: snSampleIdx,
          timeMs: samples[snSampleIdx]?.timestampMs || 0,
        }
      }
    }
  }

  return {
    channelIndex,
    channelName: ch?.name || `CH${channelIndex}`,
    firstPositive: firstPos ? {
      value: firstPos.value,
      sampleIndex: toSampleIdx(firstPos.index),
      timeMs: samples[toSampleIdx(firstPos.index)]?.timestampMs || 0,
    } : null,
    firstNegative: firstNeg ? {
      value: firstNeg.value,
      sampleIndex: toSampleIdx(firstNeg.index),
      timeMs: samples[toSampleIdx(firstNeg.index)]?.timestampMs || 0,
    } : null,
    intervalMs,
    secondPositive: secondPos,
    secondNegative: secondNeg,
  }
}

function findFirstPositive(
  diffs: number[], threshold: number
): { value: number; index: number } | null {
  let i = 0
  while (i < diffs.length && diffs[i] <= threshold) i++
  if (i >= diffs.length) return null

  let maxVal = diffs[i]
  let maxIdx = i
  i++
  while (i < diffs.length && diffs[i] >= threshold) {
    if (diffs[i] > maxVal) { maxVal = diffs[i]; maxIdx = i }
    i++
  }
  return { value: maxVal, index: maxIdx }
}

function findFirstNegative(
  diffs: number[], threshold: number
): { value: number; index: number } | null {
  const neg = -threshold
  let i = 0
  while (i < diffs.length && diffs[i] >= neg) i++
  if (i >= diffs.length) return null

  let minVal = diffs[i]
  let minIdx = i
  i++
  while (i < diffs.length && diffs[i] <= neg) {
    if (diffs[i] < minVal) { minVal = diffs[i]; minIdx = i }
    i++
  }
  return { value: minVal, index: minIdx }
}

function findSecondPositive(
  diffs: number[], threshold: number, firstEnd: number
): { value: number; index: number } | null {
  const recoveryLen = 10
  const recoveryTh = threshold * 0.5
  const n = diffs.length
  let i = firstEnd + 1

  while (i < n - recoveryLen) {
    let recovered = true
    for (let j = 0; j < recoveryLen; j++) {
      if (Math.abs(diffs[i + j]) > recoveryTh) { recovered = false; break }
    }
    if (recovered) {
      const sub = diffs.slice(i + recoveryLen)
      const result = findFirstPositive(sub, threshold)
      if (result) return { value: result.value, index: i + recoveryLen + result.index }
      return null
    }
    i++
  }
  return null
}
