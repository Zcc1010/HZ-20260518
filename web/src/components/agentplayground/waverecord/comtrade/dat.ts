import type { Cfg, Sample } from './types'

export function parseDat(data: Uint8Array, cfg: Cfg, isBinary: boolean): Sample[] {
  if (isBinary) {
    return parseBinary(data, cfg)
  }
  const text = new TextDecoder('utf-8', { fatal: false }).decode(data)
  return parseAscii(text, cfg)
}

function parseAscii(text: string, cfg: Cfg): Sample[] {
  const samples: Sample[] = []
  const lines = text.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const parts = trimmed.split(',')
    if (parts.length < 2) continue

    const sequence = parseInt(parts[0]) || 0
    const timestampMs = (parseInt(parts[1]) || 0) * cfg.timeMultiplier / 1000

    const analogValues = new Float64Array(cfg.analogChannels)
    for (let j = 0; j < cfg.analogChannels; j++) {
      const raw = parseFloat(parts[2 + j]) || 0
      const ch = cfg.analogChannelInfo[j]
      analogValues[j] = ch ? raw * ch.a + ch.b : raw
    }

    const digitalValues = new Uint8Array(cfg.digitalChannels)
    for (let j = 0; j < cfg.digitalChannels; j++) {
      const idx = 2 + cfg.analogChannels + j
      digitalValues[j] = idx < parts.length ? (parseInt(parts[idx]) || 0) as 0 | 1 : 0
    }

    samples.push({ sequence, timestampMs, analogValues, digitalValues })
  }
  return samples
}

function parseBinary(data: Uint8Array, cfg: Cfg): Sample[] {
  const digitalWords = Math.ceil(cfg.digitalChannels / 16)
  const bytesPerSample = 8 + 2 * cfg.analogChannels + 2 * digitalWords
  const numSamples = Math.floor(data.byteLength / bytesPerSample)
  const samples: Sample[] = []

  const view = new DataView(data.buffer, data.byteOffset, data.byteLength)

  for (let i = 0; i < numSamples; i++) {
    const offset = i * bytesPerSample
    const sequence = view.getUint32(offset, true)
    const timestampMs = view.getUint32(offset + 4, true) * cfg.timeMultiplier / 1000

    const analogValues = new Float64Array(cfg.analogChannels)
    let pos = offset + 8
    for (let j = 0; j < cfg.analogChannels; j++) {
      const raw = view.getInt16(pos, true)
      const ch = cfg.analogChannelInfo[j]
      analogValues[j] = ch ? raw * ch.a + ch.b : raw
      pos += 2
    }

    const digitalValues = new Uint8Array(cfg.digitalChannels)
    let dIdx = 0
    for (let w = 0; w < digitalWords; w++) {
      const word = view.getUint16(pos, true)
      pos += 2
      for (let bit = 0; bit < 16 && dIdx < cfg.digitalChannels; bit++) {
        digitalValues[dIdx++] = ((word >> bit) & 1) as 0 | 1
      }
    }

    samples.push({ sequence, timestampMs, analogValues, digitalValues })
  }

  return samples
}
