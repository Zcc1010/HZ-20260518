import { FileSpreadsheet, ListTree, Hash } from 'lucide-react'
import type { OutlineItem } from './setting-check-parse'

interface Props {
  filePath: string | null
  outline: OutlineItem[]
  sheets: string[]
  activeSheet: number
  onSheetSelect: (idx: number) => void
  onJump: (item: OutlineItem) => void
}

const LEVEL_COLOR: Record<number, string> = {
  1: 'text-teal-700 font-semibold',
  2: 'text-sky-600',
  3: 'text-sky-500',
  4: 'text-gray-500',
  5: 'text-gray-400',
  6: 'text-gray-300',
}

export function Outline({ filePath, outline, sheets, activeSheet, onSheetSelect, onJump }: Props) {
  if (!filePath) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-center">
          <ListTree className="w-8 h-8 mx-auto mb-2 opacity-30" />
          <div className="text-[13px]">选择文件查看大纲</div>
        </div>
      </div>
    )
  }

  const hasSheets = sheets.length > 0
  const hasOutline = outline.length > 0

  if (!hasSheets && !hasOutline) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-[13px]">无大纲或工作表</div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto py-1">
      {hasSheets && (
        <>
          <div className="px-3 py-1.5 mt-1 mx-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400 bg-gray-50 rounded">
            工作表
          </div>
          {sheets.map((name, i) => (
            <div
              key={i}
              className={`flex items-center gap-1.5 px-2 py-[3px] mx-1 cursor-pointer text-[13px] rounded-md transition-all ${
                i === activeSheet
                  ? 'bg-teal-50 text-teal-700 font-medium shadow-sm'
                  : 'text-gray-700 hover:bg-gray-50'
              }`}
              style={{ paddingLeft: 8 }}
              onClick={() => onSheetSelect(i)}
            >
              <FileSpreadsheet className={`w-3.5 h-3.5 shrink-0 ${i === activeSheet ? 'text-teal-600' : 'text-blue-500 opacity-70'}`} />
              <span className="truncate flex-1" title={name}>{name}</span>
            </div>
          ))}
        </>
      )}

      {hasOutline && (
        <>
          {hasSheets && (
            <div className="px-3 py-1.5 mt-2 mx-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400 bg-gray-50 rounded">
              标题大纲
            </div>
          )}
          {outline.map((h, idx) => (
            <div
              key={idx}
              className={`flex items-center gap-1.5 px-2 py-[3px] mx-1 cursor-pointer text-[13px] rounded-md transition-all ${
                h.level === 1
                  ? 'font-semibold text-gray-800 hover:bg-teal-50'
                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-800'
              }`}
              style={{ paddingLeft: (h.level - 1) * 12 + 8 }}
              onClick={() => onJump(h)}
              title={`跳转: ${h.text}`}
            >
              {h.level === 1 ? (
                <ListTree className="w-3 h-3 shrink-0 text-teal-600" />
              ) : h.level === 2 ? (
                <Hash className={`w-3 h-3 shrink-0 ${LEVEL_COLOR[h.level] || 'text-gray-400'}`} />
              ) : (
                <span className={`shrink-0 w-1 h-1 rounded-full ml-1 mr-1 ${LEVEL_COLOR[h.level] || 'text-gray-400'} bg-current opacity-50`} />
              )}
              <span className="truncate flex-1" title={h.text}>{h.text}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
