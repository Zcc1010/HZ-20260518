import { useState, useRef, useCallback, useMemo, useEffect } from 'react'
import {
  FileText, ChevronRight, Folder, FolderOpen,
  Upload, Pencil, Trash2, Download, Search, X, Copy,
  FileSpreadsheet, FileCode, FileType,
} from 'lucide-react'
import type { FileNode } from './setting-check-api'
import {
  uploadFiles, renameFile, deleteFile, getFileUrl, duplicateFile, moveFile,
} from './setting-check-api'

type UploadCategory = '定值单' | '计算书' | '说明书'

interface Props {
  files: FileNode[]
  selectedFile: string | null
  onSelect: (path: string) => void
  workspacePath: string | null
  onRefresh: () => void
}

function getFileIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase()
  if (['xls', 'xlsx', 'csv'].includes(ext || '')) return FileSpreadsheet
  if (['json', 'js', 'ts', 'py', 'sh'].includes(ext || '')) return FileCode
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext || '')) return FileType
  return FileText
}

function getFileColor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || ''
  if (['doc', 'docx'].includes(ext)) return 'text-emerald-600'
  if (['xls', 'xlsx', 'csv'].includes(ext)) return 'text-blue-600'
  if (['ppt', 'pptx'].includes(ext)) return 'text-red-500'
  if (['md', 'markdown'].includes(ext)) return 'text-amber-500'
  if (ext === 'pdf') return 'text-teal-600'
  if (['json'].includes(ext)) return 'text-purple-500'
  if (['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(ext)) return 'text-pink-500'
  if (['txt', 'log'].includes(ext)) return 'text-gray-400'
  return 'text-gray-400'
}

function getFileBadge(name: string): { ext: string; color: string } {
  const ext = (name.split('.').pop() || 'FILE').toUpperCase().slice(0, 4)
  const colorMap: Record<string, string> = {
    'doc':   'bg-emerald-50 text-emerald-700',
    'docx':  'bg-emerald-50 text-emerald-700',
    'xls':   'bg-blue-50 text-blue-700',
    'xlsx':  'bg-blue-50 text-blue-700',
    'csv':   'bg-blue-50 text-blue-700',
    'ppt':   'bg-red-50 text-red-700',
    'pptx':  'bg-red-50 text-red-700',
    'md':    'bg-amber-50 text-amber-700',
    'pdf':   'bg-teal-50 text-teal-700',
    'json':  'bg-purple-50 text-purple-700',
    'png':   'bg-pink-50 text-pink-700',
    'jpg':   'bg-pink-50 text-pink-700',
    'jpeg':  'bg-pink-50 text-pink-700',
    'gif':   'bg-pink-50 text-pink-700',
    'svg':   'bg-pink-50 text-pink-700',
    'webp':  'bg-pink-50 text-pink-700',
    'txt':   'bg-gray-50 text-gray-600',
    'log':   'bg-gray-50 text-gray-600',
  }
  return { ext, color: colorMap[ext.toLowerCase()] || 'bg-gray-100 text-gray-500' }
}

function formatSize(bytes?: number) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function formatDate(mtime?: number | string) {
  if (!mtime) return ''
  try {
    // Unix 时间戳（秒）转毫秒
    const ts = typeof mtime === 'number' ? mtime * 1000 : new Date(mtime).getTime()
    const d = new Date(ts)
    return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch { return '' }
}

function useTooltip() {
  const [tip, setTip] = useState<{ x: number; y: number; content: React.ReactNode } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showTip = useCallback((e: React.MouseEvent, content: React.ReactNode) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    timerRef.current = setTimeout(() => {
      setTip({ x: rect.left, y: rect.bottom + 4, content })
    }, 200)
  }, [])

  const hideTip = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
    setTip(null)
  }, [])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  return { tip, showTip, hideTip }
}

function TooltipOverlay({ tip }: { tip: { x: number; y: number; content: React.ReactNode } | null }) {
  if (!tip) return null
  return (
    <div
      className="fixed z-[100] bg-white border border-gray-200 text-gray-800 text-[12px] px-2.5 py-1.5 rounded-lg shadow-lg max-w-[360px] pointer-events-none break-all"
      style={{ left: tip.x, top: tip.y }}
    >
      {tip.content}
    </div>
  )
}

interface ContextMenuState {
  x: number
  y: number
  node: FileNode
}

interface DeleteConfirmState {
  node: FileNode
  onConfirm: () => void
}

function TreeNode({
  node, depth, selectedFile, onSelect, workspacePath, onRefresh, onContext, tooltipApi, onDragStart, onDragMove, onDeleteRequest,
}: {
  node: FileNode
  depth: number
  selectedFile: string | null
  onSelect: (path: string) => void
  workspacePath: string
  onRefresh: () => void
  onContext: (s: ContextMenuState) => void
  tooltipApi: ReturnType<typeof useTooltip>
  onDragStart: (path: string, isDir: boolean) => void
  onDragMove: (destPath: string) => void
  onDeleteRequest: (node: FileNode, onConfirm: () => void) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [renameVal, setRenameVal] = useState(node.name)
  const [dropTarget, setDropTarget] = useState(false)

  const handleRename = async () => {
    const newName = renameVal.trim()
    if (newName && newName !== node.name) {
      await renameFile(workspacePath, node.path, newName)
      onRefresh()
    }
    setRenaming(false)
  }

  const handleDelete = () => {
    onDeleteRequest(node, async () => {
      await deleteFile(workspacePath, node.path)
      onRefresh()
    })
  }

  const handleDownload = () => {
    const a = document.createElement('a')
    a.href = getFileUrl(workspacePath, node.path)
    a.download = node.name
    a.click()
  }

  const handleDuplicate = async () => {
    await duplicateFile(workspacePath, node.path)
    onRefresh()
  }

  const tipContent = (
    <div>
      <div className="font-medium text-gray-800">{node.name}</div>
      {node.size !== undefined && <div className="text-gray-500">{formatSize(node.size)}</div>}
      {node.mtime && <div className="text-gray-500">{formatDate(node.mtime)}</div>}
    </div>
  )

  if (node.type === 'file') {
    const isSelected = selectedFile === node.path
    const Icon = getFileIcon(node.name)
    const iconColor = getFileColor(node.name)
    const badge = getFileBadge(node.name)
    const parentDir = node.path.includes('/') ? node.path.slice(0, node.path.lastIndexOf('/')) : ''
    return (
      <div
        className={`group flex items-center gap-1.5 px-2 py-[3px] cursor-pointer text-[13px] rounded-md mx-1 transition-all relative ${
          isSelected
            ? 'bg-teal-50 text-teal-700 font-medium shadow-sm border-l-2 border-teal-500'
            : dropTarget
            ? 'bg-teal-50/60 ring-2 ring-teal-400/50'
            : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900 border-l-2 border-transparent'
        }`}
        style={{ paddingLeft: depth * 14 + 8 }}
        draggable
        onDragStart={(e) => { e.dataTransfer.setData('application/x-file-path', node.path); e.dataTransfer.effectAllowed = 'copyMove'; onDragStart(node.path, false) }}
        onDragEnd={() => { tooltipApi.hideTip(); setDropTarget(false) }}
        onDragOver={(e) => {
          e.preventDefault()
          e.stopPropagation()
          e.dataTransfer.dropEffect = 'move'
          setDropTarget(true)
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return
          setDropTarget(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setDropTarget(false)
          onDragMove(parentDir)
        }}
        onClick={() => onSelect(node.path)}
        onContextMenu={(e) => { e.preventDefault(); onContext({ x: e.clientX, y: e.clientY, node }) }}
        onMouseEnter={(e) => tooltipApi.showTip(e, tipContent)}
        onMouseLeave={tooltipApi.hideTip}
      >
        <Icon className={`w-3.5 h-3.5 shrink-0 transition-colors ${isSelected ? 'text-teal-600' : iconColor}`} />
        {renaming ? (
          <input
            className="flex-1 text-[13px] border border-teal-400 rounded px-1 py-0 outline-none bg-white"
            value={renameVal}
            autoFocus
            onChange={(e) => setRenameVal(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRename()
              if (e.key === 'Escape') { setRenaming(false); setRenameVal(node.name) }
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            <span className="truncate flex-1">{node.name}</span>
            <span className={`shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded ${badge.color} uppercase tracking-wide opacity-70`}>
              {badge.ext}
            </span>
          </>
        )}
        {!renaming && (
          <div className="hidden group-hover:flex items-center gap-0.5 absolute right-1 bg-inherit">
            <button
              className="p-0.5 rounded hover:bg-sky-50 text-gray-400 hover:text-sky-600"
              onClick={(e) => { e.stopPropagation(); handleDuplicate() }}
              title="复制副本"
            >
              <Copy className="w-3 h-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-sky-50 text-gray-400 hover:text-sky-600"
              onClick={(e) => { e.stopPropagation(); handleDownload() }}
              title="下载"
            >
              <Download className="w-3 h-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-amber-50 text-gray-400 hover:text-amber-600"
              onClick={(e) => { e.stopPropagation(); setRenaming(true) }}
              title="重命名"
            >
              <Pencil className="w-3 h-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500"
              onClick={(e) => { e.stopPropagation(); handleDelete() }}
              title="删除"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    )
  }

  const Icon = expanded ? FolderOpen : Folder
  return (
    <div>
      <div
        className={`group flex items-center gap-1 px-2 py-[3px] cursor-pointer text-[13px] font-medium text-gray-700 rounded-md mx-1 transition-all relative ${
          dropTarget
            ? 'bg-teal-50 ring-2 ring-teal-400 shadow-sm'
            : 'hover:bg-gray-50 hover:text-teal-700'
        }`}
        style={{ paddingLeft: depth * 14 + 4 }}
        draggable
        onDragStart={(e) => { e.dataTransfer.setData('application/x-file-path', node.path); e.dataTransfer.effectAllowed = 'copyMove'; onDragStart(node.path, true) }}
        onDragEnd={tooltipApi.hideTip}
        onClick={() => setExpanded(!expanded)}
        onContextMenu={(e) => { e.preventDefault(); onContext({ x: e.clientX, y: e.clientY, node }) }}
        onMouseEnter={(e) => tooltipApi.showTip(e, tipContent)}
        onMouseLeave={tooltipApi.hideTip}
        onDragOver={(e) => {
          e.preventDefault()
          e.stopPropagation()
          e.dataTransfer.dropEffect = 'move'
          setDropTarget(true)
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return
          setDropTarget(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          e.stopPropagation()
          setDropTarget(false)
          onDragMove(node.path)
        }}
      >
        <ChevronRight className={`w-3 h-3 shrink-0 text-gray-400 transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`} />
        <Icon className={`w-3.5 h-3.5 shrink-0 ${expanded ? 'text-teal-600' : 'text-gray-400'}`} />
        {renaming ? (
          <input
            className="flex-1 text-[13px] font-medium border border-teal-400 rounded px-1 py-0 outline-none bg-white"
            value={renameVal}
            autoFocus
            onChange={(e) => setRenameVal(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRename()
              if (e.key === 'Escape') { setRenaming(false); setRenameVal(node.name) }
            }}
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <span className="truncate flex-1">{node.name}</span>
        )}
        {!renaming && (
          <div className="hidden group-hover:flex items-center gap-0.5 absolute right-1 bg-inherit">
            <button
              className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700"
              onClick={(e) => { e.stopPropagation(); handleDuplicate() }}
              title="复制副本"
            >
              <Copy className="w-3 h-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700"
              onClick={(e) => { e.stopPropagation(); setRenaming(true) }}
              title="重命名"
            >
              <Pencil className="w-3 h-3" />
            </button>
            <button
              className="p-0.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500"
              onClick={(e) => { e.stopPropagation(); handleDelete() }}
              title="删除"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
      {expanded && node.children?.map((child) => (
        <TreeNode
          key={child.path}
          node={child}
          depth={depth + 1}
          selectedFile={selectedFile}
          onSelect={onSelect}
          workspacePath={workspacePath}
          onRefresh={onRefresh}
          onContext={onContext}
          tooltipApi={tooltipApi}
          onDragStart={onDragStart}
          onDragMove={onDragMove}
          onDeleteRequest={onDeleteRequest}
        />
      ))}
    </div>
  )
}

export function FileTree({ files, selectedFile, onSelect, workspacePath, onRefresh }: Props) {
  const [dragOver, setDragOver] = useState(false)
  const [ctxMenu, setCtxMenu] = useState<ContextMenuState | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<DeleteConfirmState | null>(null)
  const [searchQ, setSearchQ] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const tooltipApi = useTooltip()
  const dragDataRef = useRef<{ path: string; isDir: boolean } | null>(null)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [uploadCategory, setUploadCategory] = useState<UploadCategory>('定值单')

  const flatFiles = useMemo(() => {
    const result: FileNode[] = []
    const walk = (nodes: FileNode[]) => {
      for (const n of nodes) {
        if (n.type === 'file') result.push(n)
        if (n.children) walk(n.children)
      }
    }
    walk(files)
    return result
  }, [files])

  const filteredFiles = useMemo(() => {
    if (!searchQ.trim()) return null
    const q = searchQ.toLowerCase()
    return flatFiles.filter((f) => f.name.toLowerCase().includes(q))
  }, [searchQ, flatFiles])

  const handleUpload = async (fileList: FileList | File[]) => {
    if (!workspacePath) return
    const arr = Array.from(fileList)
    if (!arr.length) return
    setPendingFiles(arr)
    setUploadCategory('定值单')
    setUploadDialogOpen(true)
  }

  const handleUploadConfirm = async () => {
    if (!workspacePath || pendingFiles.length === 0) return
    // Prefix filenames with category directory
    const renamedFiles = pendingFiles.map(f => {
      const prefixedName = `${uploadCategory}/${f.name}`
      return new File([f], prefixedName, { type: f.type, lastModified: f.lastModified })
    })
    await uploadFiles(workspacePath, renamedFiles)
    setUploadDialogOpen(false)
    setPendingFiles([])
    onRefresh()
  }

  const handleDragStart = useCallback((path: string, isDir: boolean) => {
    dragDataRef.current = { path, isDir }
  }, [])

  const handleDragMove = useCallback(async (destDir: string) => {
    const drag = dragDataRef.current
    if (!drag || !workspacePath) return
    if (drag.path === destDir || destDir.startsWith(drag.path + '/')) return
    const fileName = drag.path.split('/').pop()!
    const destPath = destDir ? destDir + '/' + fileName : fileName
    if (destPath === drag.path) return
    try {
      await moveFile(workspacePath, drag.path, destPath)
    } catch (e) {
      console.error('Move failed:', e)
    }
    dragDataRef.current = null
    onRefresh()
  }, [workspacePath, onRefresh])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const filePath = e.dataTransfer.getData('application/x-file-path')
    if (filePath && dragDataRef.current) {
      const drag = dragDataRef.current
      if (!drag.path.includes('/')) return
      const fileName = drag.path.split('/').pop()!
      if (fileName === drag.path) return
      moveFile(workspacePath || '', drag.path, fileName).then(() => {
        dragDataRef.current = null
        onRefresh()
      })
      return
    }
    if (e.dataTransfer.files.length) {
      handleUpload(e.dataTransfer.files)
    }
  }, [workspacePath, onRefresh])

  if (ctxMenu) {
    const close = () => setCtxMenu(null)
    setTimeout(() => document.addEventListener('click', close, { once: true }), 0)
  }

  const handleCtxRename = () => {
    if (!ctxMenu) return
    const newName = prompt('新名称', ctxMenu.node.name)
    if (newName && newName.trim() && newName !== ctxMenu.node.name && workspacePath) {
      renameFile(workspacePath, ctxMenu.node.path, newName.trim()).then(onRefresh)
    }
    setCtxMenu(null)
  }

  const handleCtxDelete = () => {
    if (!ctxMenu || !workspacePath) return
    const node = ctxMenu.node
    setDeleteConfirm({
      node,
      onConfirm: () => {
        deleteFile(workspacePath, node.path).then(onRefresh)
      },
    })
    setCtxMenu(null)
  }

  const handleCtxDuplicate = () => {
    if (!ctxMenu || !workspacePath) return
    duplicateFile(workspacePath, ctxMenu.node.path).then(onRefresh)
    setCtxMenu(null)
  }

  const handleCtxDownload = () => {
    if (!ctxMenu || !workspacePath) return
    const a = document.createElement('a')
    a.href = getFileUrl(workspacePath, ctxMenu.node.path)
    a.download = ctxMenu.node.name
    a.click()
    setCtxMenu(null)
  }

  const isEmpty = files.length === 0

  return (
    <div className="h-full flex flex-col">
      <div className="px-2 py-1.5 border-b border-gray-200 shrink-0 flex items-center gap-1.5">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-400 pointer-events-none" />
          <input
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
            placeholder="搜索文件..."
            className="w-full pl-7 pr-6 py-1 text-[13px] border border-gray-200 rounded-md bg-gray-50 focus:outline-none focus:border-teal-400 focus:bg-white transition-colors"
          />
          {searchQ && (
            <button
              onClick={() => setSearchQ('')}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-teal-600 transition-colors shrink-0"
          title="上传文件"
          disabled={!workspacePath}
        >
          <Upload className="w-3.5 h-3.5" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) handleUpload(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      <div
        className={`flex-1 overflow-y-auto py-1 ${dragOver ? 'bg-teal-50/40' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          if (e.dataTransfer.types.includes('Files') || e.dataTransfer.types.includes('application/x-file-path')) {
            setDragOver(true)
          }
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return
          setDragOver(false)
        }}
        onDrop={handleDrop}
      >
        {isEmpty ? (
          <div
            className="h-full flex items-center justify-center text-center p-4"
            onDragOver={(e) => {
              e.preventDefault()
              if (e.dataTransfer.types.includes('Files') || e.dataTransfer.types.includes('application/x-file-path')) setDragOver(true)
            }}
            onDragLeave={(e) => {
              if ((e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) return
              setDragOver(false)
            }}
            onDrop={handleDrop}
          >
            <div>
              <Upload className="w-8 h-8 mx-auto mb-2 text-gray-300 opacity-40" />
              <div className="text-[13px] text-gray-400">
                {dragOver ? '松开上传/移动' : workspacePath ? '拖放文件到此处或点击上传' : '请先选择工作区'}
              </div>
            </div>
          </div>
        ) : filteredFiles ? (
          filteredFiles.length === 0 ? (
            <div className="text-center text-gray-400 text-[13px] py-8">
              未找到匹配的文件
            </div>
          ) : (
            filteredFiles.map((node) => {
              const isSelected = selectedFile === node.path
              const Icon = getFileIcon(node.name)
              const tipContent = (
                <div>
                  <div className="font-medium text-gray-800">{node.name}</div>
                  {node.size !== undefined && <div className="text-gray-500">{formatSize(node.size)}</div>}
                  {node.mtime && <div className="text-gray-500">{formatDate(node.mtime)}</div>}
                </div>
              )
              return (
                <div
                  key={node.path}
                  className={`group flex items-center gap-1.5 px-2 py-[3px] cursor-pointer text-[13px] rounded-md mx-1 transition-colors relative ${
                    isSelected
                      ? 'bg-teal-50 text-teal-700 font-medium'
                      : 'text-gray-700 hover:bg-gray-50'
                  }`}
                  style={{ paddingLeft: 8 }}
                  draggable
                  onDragStart={(e) => { e.dataTransfer.setData('application/x-file-path', node.path); e.dataTransfer.effectAllowed = 'copyMove'; handleDragStart(node.path, false) }}
                  onClick={() => onSelect(node.path)}
                  onContextMenu={(e) => { e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, node }) }}
                  onMouseEnter={(e) => tooltipApi.showTip(e, tipContent)}
                  onMouseLeave={tooltipApi.hideTip}
                >
                  <Icon className={`w-3.5 h-3.5 shrink-0 ${isSelected ? 'text-teal-600' : 'text-gray-400'}`} />
                  <span className="truncate flex-1">{node.name}</span>
                </div>
              )
            })
          )
        ) : (
          <>
            {dragOver && (
              <div className="mx-2 mb-1 border-2 border-dashed border-teal-400 rounded-md py-2 text-center text-[13px] text-teal-600">
                松开上传文件
              </div>
            )}
            {files.map((node) => (
              <TreeNode
                key={node.path}
                node={node}
                depth={0}
                selectedFile={selectedFile}
                onSelect={onSelect}
                workspacePath={workspacePath || ''}
                onRefresh={onRefresh}
                onContext={setCtxMenu}
                tooltipApi={tooltipApi}
                onDragStart={handleDragStart}
                onDragMove={handleDragMove}
                onDeleteRequest={(n, onConfirm) => setDeleteConfirm({ node: n, onConfirm })}
              />
            ))}
          </>
        )}
      </div>

      {ctxMenu && (
        <div
          className="fixed z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 text-[13px] min-w-[120px]"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          {ctxMenu.node.type === 'file' && (
            <button
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-gray-700 text-left"
              onClick={handleCtxDownload}
            >
              <Download className="w-3.5 h-3.5" />
              下载
            </button>
          )}
          <button
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-gray-700 text-left"
            onClick={handleCtxDuplicate}
          >
            <Copy className="w-3.5 h-3.5" />
            复制副本
          </button>
          <button
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 text-gray-700 text-left"
            onClick={handleCtxRename}
          >
            <Pencil className="w-3.5 h-3.5" />
            重命名
          </button>
          <button
            className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-red-50 text-red-500 text-left"
            onClick={handleCtxDelete}
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        </div>
      )}

      <TooltipOverlay tip={tooltipApi.tip} />

      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={() => setDeleteConfirm(null)}>
          <div className="bg-white rounded-xl shadow-xl w-[340px] border border-gray-200" onClick={e => e.stopPropagation()}>
            <div className="p-4 border-b border-gray-200 flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-red-50 flex items-center justify-center shrink-0">
                <Trash2 className="w-4 h-4 text-red-500" />
              </div>
              <h3 className="text-sm font-semibold text-gray-800">确认删除</h3>
            </div>
            <div className="p-4">
              <p className="text-[13px] text-gray-600">
                确定要删除「<span className="font-medium text-gray-800">{deleteConfirm.node.name}</span>」吗？
              </p>
              <p className="text-[12px] text-gray-400 mt-1">此操作不可撤销</p>
            </div>
            <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-3 py-1.5 text-[13px] text-gray-600 hover:text-gray-800 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => { deleteConfirm.onConfirm(); setDeleteConfirm(null) }}
                className="px-4 py-1.5 text-[13px] bg-red-500 text-white rounded-md hover:bg-red-600 transition-colors"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {uploadDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20" onClick={() => setUploadDialogOpen(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[360px] border border-gray-200" onClick={e => e.stopPropagation()}>
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-800">上传文件</h3>
              <button onClick={() => setUploadDialogOpen(false)} className="text-gray-400 hover:text-gray-600 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="text-[13px] font-medium text-gray-700 mb-2 block">文件类型</label>
                <div className="flex gap-2">
                  {(['定值单', '计算书', '说明书'] as UploadCategory[]).map(cat => (
                    <button
                      key={cat}
                      onClick={() => setUploadCategory(cat)}
                      className={`flex-1 py-2 px-3 text-[13px] rounded-lg border transition-colors ${
                        uploadCategory === cat
                          ? 'bg-teal-50 border-teal-400 text-teal-700 font-medium'
                          : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-[13px] font-medium text-gray-700 mb-2 block">待上传文件</label>
                <div className="space-y-1 max-h-[160px] overflow-y-auto">
                  {pendingFiles.map((f, i) => (
                    <div key={i} className="flex items-center gap-2 text-[13px] text-gray-600 bg-gray-50 rounded px-2 py-1.5">
                      <FileText className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                      <span className="truncate flex-1">{f.name}</span>
                      <button
                        onClick={() => setPendingFiles(prev => prev.filter((_, idx) => idx !== i))}
                        className="text-gray-400 hover:text-red-500 transition-colors shrink-0"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="p-4 border-t border-gray-200 flex justify-end gap-2">
              <button
                onClick={() => setUploadDialogOpen(false)}
                className="px-3 py-1.5 text-[13px] text-gray-600 hover:text-gray-800 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleUploadConfirm}
                disabled={pendingFiles.length === 0}
                className="px-4 py-1.5 text-[13px] bg-teal-600 text-white rounded-md hover:bg-teal-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                上传到「{uploadCategory}」
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
