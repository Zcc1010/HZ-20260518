import type { Sample } from './types'

export interface DigitalEvent {
  sampleIndex: number
  timeMs: number
  channelIndex: number
  channelName: string
  newState: number
  description: string
}

export function extractEvents(
  samples: Sample[],
  digitalChannelNames: string[]
): DigitalEvent[] {
  const events: DigitalEvent[] = []
  const numDigital = digitalChannelNames.length
  if (numDigital === 0 || samples.length < 2) return events

  for (let i = 1; i < samples.length; i++) {
    for (let ch = 0; ch < numDigital; ch++) {
      const prev = samples[i - 1].digitalValues[ch]
      const curr = samples[i].digitalValues[ch]
      if (prev !== curr) {
        events.push({
          sampleIndex: i,
          timeMs: samples[i].timestampMs,
          channelIndex: ch,
          channelName: digitalChannelNames[ch],
          newState: curr,
          description: curr === 1 ? '动作' : '返回',
        })
      }
    }
  }

  return events
}
