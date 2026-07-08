import type { HdrData } from './types'

function getChildText(parent: Element, tagName: string): string {
  const el = parent.querySelector(tagName)
  return el?.textContent?.trim() || ''
}

function getAttrOrChild(el: Element, name: string): string {
  return el.getAttribute(name) || getChildText(el, name)
}

export function parseHdr(text: string): HdrData {
  const result: HdrData = {
    rawText: text,
    deviceInfo: {},
    tripInfo: [],
    digitalEvents: [],
    settings: [],
    rawSections: [],
  }

  const parser = new DOMParser()
  const doc = parser.parseFromString(text, 'text/xml')

  const parseError = doc.querySelector('parsererror')
  if (parseError) {
    result.rawSections.push({ title: '原始内容', content: text, type: 'text' })
    return result
  }

  const faultStartTime = getChildText(doc.documentElement, 'FaultStartTime')
  if (faultStartTime) {
    result.deviceInfo['故障时间'] = faultStartTime
  }

  parseDeviceInfo(doc, result)
  parseTripInfo(doc, result)
  parseDigitalEvents(doc, result)
  parseSettingValues(doc, result)
  parseFaultInfo(doc, result)
  parseDigitalStatus(doc, result)

  if (result.rawSections.length === 0) {
    result.rawSections.push({ title: '原始内容', content: text, type: 'text' })
  }

  return result
}

function parseDeviceInfo(doc: Document, result: HdrData) {
  const items = doc.querySelectorAll('DeviceInfo')
  if (items.length === 0) return

  const rows: string[][] = []
  items.forEach(item => {
    const name = getAttrOrChild(item, 'name')
    const value = getAttrOrChild(item, 'value')
    if (name || value) {
      result.deviceInfo[name] = value
      rows.push([name, value])
    }
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '设备信息',
      content: formatRowsAsTable(['名称', '值'], rows),
      type: 'table',
    })
  }
}

function parseTripInfo(doc: Document, result: HdrData) {
  const items = doc.querySelectorAll('TripInfo')
  if (items.length === 0) return

  const rows: string[][] = []
  items.forEach(item => {
    const time = getAttrOrChild(item, 'time')
    const name = getAttrOrChild(item, 'name')
    const phase = getAttrOrChild(item, 'phase')
    const value = getAttrOrChild(item, 'value')
    const phaseDisplay = phase || (value === '1' ? '动作' : value === '0' ? '返回' : value)

    result.tripInfo.push({ time, element: name, phase: phaseDisplay })
    rows.push([time, name, phaseDisplay])

    const faultInfos = item.querySelectorAll('FaultInfo')
    faultInfos.forEach(fi => {
      const fiName = getAttrOrChild(fi, 'name')
      const fiValue = getAttrOrChild(fi, 'value')
      rows.push(['', fiName, fiValue])
    })
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '保护动作信息',
      content: formatRowsAsTable(['时间', '动作元件', '信息'], rows),
      type: 'table',
    })
  }
}

function parseDigitalEvents(doc: Document, result: HdrData) {
  const items = doc.querySelectorAll('DigitalEvent')
  if (items.length === 0) return

  const rows: string[][] = []
  items.forEach(item => {
    const time = getAttrOrChild(item, 'time')
    const name = getAttrOrChild(item, 'name')
    const value = getAttrOrChild(item, 'value')
    const state = value === '0->1' ? '动作' : value === '1->0' ? '返回' : value

    result.digitalEvents.push({ time, channel: name, state })
    rows.push([time, name, state])
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '数字量事件',
      content: formatRowsAsTable(['时间', '通道', '状态'], rows),
      type: 'table',
    })
  }
}

function parseSettingValues(doc: Document, result: HdrData) {
  const items = doc.querySelectorAll('SettingValue')
  if (items.length === 0) return

  const rows: string[][] = []
  items.forEach(item => {
    const name = getAttrOrChild(item, 'name')
    const value = getAttrOrChild(item, 'value')
    const unit = getAttrOrChild(item, 'unit')
    result.settings.push({ name, value, unit })
    rows.push([name, value, unit])
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '定值信息',
      content: formatRowsAsTable(['名称', '值', '单位'], rows),
      type: 'table',
    })
  }
}

function parseFaultInfo(doc: Document, result: HdrData) {
  const rootFis = doc.documentElement.querySelectorAll(':scope > FaultInfo')
  if (rootFis.length === 0) return

  const rows: string[][] = []
  rootFis.forEach(fi => {
    const name = getAttrOrChild(fi, 'name')
    const value = getAttrOrChild(fi, 'value')
    if (name || value) rows.push([name, value])
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '故障信息',
      content: formatRowsAsTable(['名称', '值'], rows),
      type: 'table',
    })
  }
}

function parseDigitalStatus(doc: Document, result: HdrData) {
  const items = doc.querySelectorAll('DigitalStatus')
  if (items.length === 0) return

  const rows: string[][] = []
  items.forEach(item => {
    const name = getAttrOrChild(item, 'name')
    const value = getAttrOrChild(item, 'value')
    if (name) rows.push([name, value || ''])
  })

  if (rows.length > 0) {
    result.rawSections.push({
      title: '开关量状态',
      content: formatRowsAsTable(['通道', '状态'], rows),
      type: 'table',
    })
  }
}

function formatRowsAsTable(headers: string[], rows: string[][]): string {
  const all = [headers, ...rows]
  return all.map(r => r.join(' | ')).join('\n')
}
