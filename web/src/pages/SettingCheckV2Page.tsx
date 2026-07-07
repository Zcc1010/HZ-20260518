import { useState, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { ArrowLeft, FolderOpen, ChevronRight, Plus, Search, X, FolderTree, ListTree, Upload, FileText, PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { FileTree } from '@/components/agentplayground/settingcheck/FileTree'
import { FileViewer } from '@/components/agentplayground/settingcheck/FileViewer'
import { ChatPanel } from '@/components/agentplayground/settingcheck/ChatPanel'
import { Outline } from '@/components/agentplayground/settingcheck/Outline'
import { ResizeHandle } from '@/components/agentplayground/settingcheck/ResizeHandle'
import { listWorkspaces, getFileTree, createWorkspace, uploadFiles } from '@/components/agentplayground/settingcheck/setting-check-api'
import type { FileNode } from '@/components/agentplayground/settingcheck/setting-check-api'
import type { OutlineItem } from '@/components/agentplayground/settingcheck/setting-check-parse'
import { useNavigate } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'

type LeftTab = 'files' | 'outline'

export default function SettingCheckV2Page() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const jobId = searchParams.get('jobId')
  const [workspacePath, setWorkspacePath] = useState<string | null>(null)
  const [files, setFiles] = useState<FileNode[]>([])
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(false)
  const [folderList, setFolderList] = useState<string[]>([])
  const [fileVersion, setFileVersion] = useState(0)
  const [searchQ, setSearchQ] = useState('')
  const [showNewWs, setShowNewWs] = useState(false)
  const [newWsName, setNewWsName] = useState('')
  const [newWsFile, setNewWsFile] = useState<File | null>(null)
  const newWsFileInputRef = useRef<HTMLInputElement>(null)
  const selectedFileRef = useRef<string | null>(null)
  const [leftWidth, setLeftWidth] = useState(() =>
    Number(localStorage.getItem('sc2-leftWidth')) || 260,
  )
  const [rightWidth, setRightWidth] = useState(() =>
    Number(localStorage.getItem('sc2-rightWidth')) || 560,
  )
  const [leftCollapsed, setLeftCollapsed] = useState(() =>
    localStorage.getItem('sc2-leftCollapsed') === 'true',
  )
  const [leftTab, setLeftTab] = useState<LeftTab>('files')
  const [sheets, setSheets] = useState<string[]>([])
  const [activeSheet, setActiveSheet] = useState(0)
  const [outline, setOutline] = useState<OutlineItem[]>([])
  const [pdfPage, setPdfPage] = useState<number>(0)
  const [loading, setLoading] = useState(() => !!searchParams.get('jobId'))

  selectedFileRef.current = selectedFile

  useEffect(() => {
    localStorage.setItem('sc2-leftWidth', String(leftWidth))
    localStorage.setItem('sc2-rightWidth', String(rightWidth))
  }, [leftWidth, rightWidth])

  useEffect(() => {
    localStorage.setItem('sc2-leftCollapsed', String(leftCollapsed))
  }, [leftCollapsed])

  const findFirstReportMd = (nodes: FileNode[]): string | null => {
    for (const n of nodes) {
      if (n.name === '报告' && n.children) {
        const md = n.children.find(c => c.type === 'file' && c.name.endsWith('.md'))
        if (md) return md.path
      }
    }
    return null
  }

  const refreshTree = (ws: string) => {
    getFileTree(ws).then((tree) => {
      setFiles(tree)
      setLoading(false)
      if (selectedFileRef.current) {
        const exists = (nodes: FileNode[]): boolean =>
          nodes.some((n) => n.path === selectedFileRef.current || (n.children && exists(n.children)))
        if (!exists(tree)) setSelectedFile(null)
      } else {
        const reportMd = findFirstReportMd(tree)
        if (reportMd) setSelectedFile(reportMd)
      }
    }).catch(() => setLoading(false))
  }

  useEffect(() => {
    if (workspacePath) {
      refreshTree(workspacePath)
      const ws = workspacePath
      const es = new EventSource(`/api/setting-check-v2/workspaces/${encodeURIComponent(ws)}/events`)
      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          refreshTree(ws)
          if (selectedFileRef.current && event.path === selectedFileRef.current && event.type === 'change') {
            setFileVersion((v) => v + 1)
          }
        } catch {}
      }
      return () => es.close()
    } else {
      setFiles([])
    }
  }, [workspacePath])

  useEffect(() => {
    setSelectedFile(null)
  }, [workspacePath])

  useEffect(() => {
    setActiveSheet(0)
    setPdfPage(0)
  }, [selectedFile])

  const refreshFolders = () => {
    listWorkspaces().then(setFolderList).catch(() => setFolderList([]))
  }

  useEffect(() => {
    refreshFolders()
  }, [])

  useEffect(() => {
    if (jobId) {
      setLoading(true)
      fetch(`/api/setting-check/jobs/${jobId}`)
        .then(res => res.json())
        .then(job => {
          if (job && job.id) {
            const wsName = job.station && job.device
              ? `${job.station}-${job.device}`
              : `job-${job.id}`
            listWorkspaces().then(workspaces => {
              if (workspaces.includes(wsName)) {
                setWorkspacePath(wsName)
              } else {
                fetch(`/api/setting-check/jobs/${jobId}/copy-to-workspace`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ workspace: wsName })
                }).then(() => {
                  setWorkspacePath(wsName)
                  refreshFolders()
                })
              }
            })
          } else {
            setLoading(false)
          }
        })
        .catch(() => setLoading(false))
    }
  }, [jobId])

  const filteredFolders = searchQ
    ? folderList.filter((f) => f.toLowerCase().includes(searchQ.toLowerCase()))
    : folderList

  const handleCreateWs = async () => {
    const name = newWsName.trim()
    if (!name) return
    await createWorkspace(name)
    if (newWsFile) {
      try {
        await uploadFiles(name, [newWsFile])
      } catch (e) {
        console.error('Upload failed', e)
      }
    }
    setNewWsName('')
    setNewWsFile(null)
    if (newWsFileInputRef.current) newWsFileInputRef.current.value = ''
    setShowNewWs(false)
    refreshFolders()
    setWorkspacePath(name)
    setShowPicker(false)
  }

  const handleNewWsFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setNewWsFile(f)
    setNewWsName(f.name.replace(/\.[^.]+$/, ''))
  }

  const cancelNewWs = () => {
    setNewWsName('')
    setNewWsFile(null)
    if (newWsFileInputRef.current) newWsFileInputRef.current.value = ''
    setShowNewWs(false)
  }

  const handleJump = (item: OutlineItem) => {
    if (item.page !== undefined) {
      setPdfPage(item.page)
      return
    }
    let attempts = 0
    const tryScroll = () => {
      const el = document.getElementById(item.id)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
      if (++attempts < 10) {
        setTimeout(tryScroll, 50)
      }
    }
    tryScroll()
  }

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {loading && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/80">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-[3px] border-teal-200 border-t-teal-600 rounded-full animate-spin" />
            <span className="text-sm text-gray-500">加载文件中...</span>
          </div>
        </div>
      )}
      <header className="h-12 bg-white border-b border-gray-200 flex items-center px-4 shrink-0 gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => navigate('/agentplayground')}
          title="返回"
          className="shrink-0"
        >
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="w-px h-5 bg-gray-200" />
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-teal-600 flex items-center justify-center">
            <span className="text-white text-xs font-bold">校</span>
          </div>
          <h1 className="text-sm font-semibold text-gray-800 whitespace-nowrap">定值校核</h1>
        </div>
        <div className="w-px h-5 bg-gray-200" />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { setShowPicker(true); refreshFolders() }}
          className="max-w-[240px] hover:bg-gray-100"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          <span className="truncate">{workspacePath || '选择工作区'}</span>
          {workspacePath && <ChevronRight className="w-3 h-3 opacity-50" />}
        </Button>
        <div className="flex-1" />
      </header>

      <div className="flex-1 flex overflow-hidden">
        {leftCollapsed ? (
          <div className="shrink-0 bg-white border-r border-gray-200 flex flex-col items-center py-2 gap-2">
            <button
              onClick={() => setLeftCollapsed(false)}
              className="p-1.5 rounded-md hover:bg-gray-100 text-gray-400 hover:text-teal-600 transition-colors"
              title="展开文件面板"
            >
              <PanelLeftOpen className="w-4 h-4" />
            </button>
            <div className="w-px h-4 bg-gray-200" />
            <button
              onClick={() => { setLeftCollapsed(false); setLeftTab('files') }}
              className={`p-1.5 rounded-md transition-colors ${leftTab === 'files' ? 'bg-teal-50 text-teal-600' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'}`}
              title="文件"
            >
              <FolderTree className="w-4 h-4" />
            </button>
            <button
              onClick={() => { setLeftCollapsed(false); setLeftTab('outline') }}
              className={`p-1.5 rounded-md transition-colors ${leftTab === 'outline' ? 'bg-teal-50 text-teal-600' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'}`}
              title="大纲"
            >
              <ListTree className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div style={{ width: leftWidth }} className="shrink-0 bg-white border-r border-gray-200 overflow-hidden">
            <div className="h-full flex flex-col">
              <div className="flex border-b border-gray-200 shrink-0">
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-[13px] font-medium transition-colors ${
                    leftTab === 'files'
                      ? 'text-teal-700 border-b-2 border-teal-500'
                      : 'text-gray-400 hover:text-gray-600 border-b-2 border-transparent'
                  }`}
                  onClick={() => setLeftTab('files')}
                >
                  <FolderTree className="w-3.5 h-3.5" />
                  文件
                </button>
                <button
                  className={`flex-1 flex items-center justify-center gap-1.5 py-2 text-[13px] font-medium transition-colors ${
                    leftTab === 'outline'
                      ? 'text-teal-700 border-b-2 border-teal-500'
                      : 'text-gray-400 hover:text-gray-600 border-b-2 border-transparent'
                  }`}
                  onClick={() => setLeftTab('outline')}
                >
                  <ListTree className="w-3.5 h-3.5" />
                  大纲
                </button>
                <button
                  onClick={() => setLeftCollapsed(true)}
                  className="px-2 py-2 text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
                  title="折叠文件面板"
                >
                  <PanelLeftClose className="w-3.5 h-3.5" />
                </button>
              </div>

              <div className="flex-1 flex flex-col overflow-hidden">
                {leftTab === 'files' ? (
                  <FileTree
                    files={files}
                    selectedFile={selectedFile}
                    onSelect={setSelectedFile}
                    workspacePath={workspacePath}
                    onRefresh={() => workspacePath && refreshTree(workspacePath)}
                  />
                ) : (
                  <Outline
                    filePath={selectedFile}
                    outline={outline}
                    sheets={sheets}
                    activeSheet={activeSheet}
                    onSheetSelect={setActiveSheet}
                    onJump={handleJump}
                  />
                )}
              </div>
            </div>
          </div>
        )}
        {!leftCollapsed && <ResizeHandle side="left" currentWidth={leftWidth} onResize={setLeftWidth} />}
        <div className="flex-1 overflow-hidden bg-gray-50">
          <FileViewer
            workspacePath={workspacePath}
            filePath={selectedFile}
            version={fileVersion}
            activeSheet={activeSheet}
            onSheetsChange={setSheets}
            onActiveSheetChange={setActiveSheet}
            onOutlineChange={setOutline}
            pdfPage={pdfPage}
          />
        </div>
        <ResizeHandle side="right" currentWidth={rightWidth} onResize={setRightWidth} />
        <div style={{ width: rightWidth }} className="shrink-0 bg-white border-l border-gray-200 overflow-hidden">
          <ChatPanel workspacePath={workspacePath} />
        </div>
      </div>

      {showPicker && (
        <div className="fixed inset-0 bg-black/20 flex items-center justify-center z-50" onClick={() => setShowPicker(false)}>
          <div className="bg-white rounded-xl shadow-xl w-[400px] border border-gray-200" onClick={(e) => e.stopPropagation()}>
            <div className="p-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-gray-800">选择工作区</h3>
              <button onClick={() => setShowPicker(false)} className="text-gray-400 hover:text-gray-600 transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-3 border-b border-gray-200">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  placeholder="搜索工作区..."
                  className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-md bg-gray-50 focus:outline-none focus:border-teal-400 focus:bg-white transition-colors"
                />
              </div>
            </div>
            <div className="max-h-[360px] overflow-y-auto py-1">
              {filteredFolders.map((name) => (
                <div
                  key={name}
                  className={`px-4 py-2.5 text-sm cursor-pointer hover:bg-gray-50 flex items-center gap-2.5 transition-colors ${
                    workspacePath === name ? 'bg-teal-50 text-teal-700 font-medium' : 'text-gray-700'
                  }`}
                  onClick={() => { setWorkspacePath(name); setShowPicker(false); setSearchQ('') }}
                >
                  <FolderOpen className="w-4 h-4 shrink-0 opacity-60" />
                  <span className="truncate">{name}</span>
                </div>
              ))}
              {filteredFolders.length === 0 && !showNewWs && (
                <div className="text-center text-gray-400 text-sm py-8">
                  {searchQ ? '未找到匹配的工作区' : '暂无工作区'}
                </div>
              )}
            </div>
            <div className="p-3 border-t border-gray-200">
              {showNewWs ? (
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      value={newWsName}
                      onChange={(e) => setNewWsName(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleCreateWs()}
                      placeholder="工作区名称"
                      className="flex-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:border-teal-400 bg-white"
                      autoFocus
                    />
                    <button onClick={handleCreateWs} className="px-3 py-1.5 text-sm bg-teal-600 text-white rounded-md hover:bg-teal-700 transition-colors">
                      创建
                    </button>
                    <button onClick={cancelNewWs} className="px-2 py-1.5 text-sm text-gray-400 hover:text-gray-600 transition-colors">
                      取消
                    </button>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      ref={newWsFileInputRef}
                      type="file"
                      onChange={handleNewWsFile}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => newWsFileInputRef.current?.click()}
                      className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-teal-600 transition-colors"
                    >
                      <Upload className="w-3 h-3" />
                      {newWsFile ? '更换文件' : '或选择文件命名'}
                    </button>
                    {newWsFile && (
                      <div className="flex items-center gap-1 text-xs text-gray-400 truncate flex-1 min-w-0">
                        <FileText className="w-3 h-3 shrink-0" />
                        <span className="truncate">{newWsFile.name}</span>
                        <button
                          type="button"
                          onClick={() => {
                            setNewWsFile(null)
                            if (newWsFileInputRef.current) newWsFileInputRef.current.value = ''
                          }}
                          className="text-gray-400 hover:text-gray-600 shrink-0"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowNewWs(true)}
                  className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-teal-600 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  新建工作区
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
