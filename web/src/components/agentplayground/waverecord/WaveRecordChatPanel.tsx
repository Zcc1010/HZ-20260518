import { useState, useRef, useEffect, useCallback } from 'react'
import { nanoid } from 'nanoid'
import { MessageSquare, Send, Square, Plus, Copy, Check, Paperclip, X, FileText, ChevronDown, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { MarkdownRenderer } from '@/components/shared/MarkdownRenderer'
import { ChatWebSocket, type WsMessage } from '@/lib/ws'
import { useChatStore, type ChatMessage } from '@/stores/chatStore'
import { uploadFiles, getFileTree, type FileNode } from './wave-record-api'

interface Props {
  workspacePath: string | null
}

export function WaveRecordChatPanel({ workspacePath }: Props) {
  const {
    messages,
    addMessage,
    setWaiting,
    setProgress,
    setMessages,
    setCurrentSession,
  } = useChatStore()

  const sessionState = useChatStore((s) => {
    const key = s.currentSessionKey ?? ''
    return s.sessionStates[key] ?? { isWaiting: false, progressText: '' }
  })
  const isWaiting = sessionState.isWaiting

  const wsRef = useRef<ChatWebSocket | null>(null)
  const assistantMsgIdsRef = useRef<Record<string, string>>({})
  const handleWsMessageRef = useRef<(msg: WsMessage) => void>(() => {})
  const contextSentRef = useRef(false)
  const messagesScrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const wasAtBottomRef = useRef(true)
  const [showJumpBottom, setShowJumpBottom] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [chatInput, setChatInput] = useState('')
  const chatFileInputRef = useRef<HTMLInputElement>(null)
  const [chatDragOver, setChatDragOver] = useState(false)
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; path: string }[]>([])
  const [fileTree, setFileTree] = useState<FileNode[]>([])

  // Auto-scroll
  useEffect(() => {
    if (wasAtBottomRef.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  const handleMessagesScroll = () => {
    const el = messagesScrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    wasAtBottomRef.current = atBottom
    setShowJumpBottom(!atBottom)
  }

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    wasAtBottomRef.current = true
    setShowJumpBottom(false)
  }

  // Load file tree for context
  useEffect(() => {
    if (workspacePath) {
      getFileTree(workspacePath).then(setFileTree).catch(() => setFileTree([]))
    } else {
      setFileTree([])
    }
  }, [workspacePath])

  // Clear chat when workspace changes
  useEffect(() => {
    if (!workspacePath) {
      setMessages([])
      return
    }
    useChatStore.getState().clearMessages()
    contextSentRef.current = false
  }, [workspacePath])

  // WebSocket connection
  useEffect(() => {
    const ws = new ChatWebSocket(
      (msg) => handleWsMessageRef.current(msg),
      (connected) => setIsConnected(connected),
    )
    wsRef.current = ws
    ws.connect(useChatStore.getState().currentSessionKey ?? undefined)
    return () => ws.disconnect()
  }, [])

  // Handle WebSocket messages
  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      const msgSessionKey = msg.session_key
      const currentKey = useChatStore.getState().currentSessionKey
      const targetKey = msgSessionKey || currentKey || ''

      const ensureStreamingMessage = () => {
        const state = useChatStore.getState()
        const existingId = assistantMsgIdsRef.current[targetKey]
        if (existingId && state.messages.some((m) => m.id === existingId)) return existingId
        const nextId = nanoid()
        assistantMsgIdsRef.current[targetKey] = nextId
        addMessage({
          id: nextId,
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
          isStreaming: true,
        })
        return nextId
      }

      const patchStreamingMessage = (patch: Partial<ChatMessage>) => {
        const streamId = assistantMsgIdsRef.current[targetKey]
        if (!streamId) return false
        const state = useChatStore.getState()
        if (!state.messages.some((m) => m.id === streamId)) {
          delete assistantMsgIdsRef.current[targetKey]
          return false
        }
        setMessages(state.messages.map((m) => (m.id === streamId ? { ...m, ...patch } : m)))
        return true
      }

      if (msg.type === 'session_info') {
        if (msg.session_key && msg.session_key !== currentKey) {
          setCurrentSession(msg.session_key)
        }
      } else if (msg.type === 'stream_start') {
        ensureStreamingMessage()
        setProgress('', targetKey)
      } else if (msg.type === 'stream_delta') {
        if (msg.content) {
          const streamId = ensureStreamingMessage()
          useChatStore.getState().appendAssistantText(streamId, msg.content)
        }
        setProgress('', targetKey)
      } else if (msg.type === 'stream_end') {
        patchStreamingMessage({ isStreaming: false })
        delete assistantMsgIdsRef.current[targetKey]
      } else if (msg.type === 'progress') {
        setProgress(msg.content ?? '', targetKey)
      } else if (msg.type === 'done') {
        setProgress('', targetKey)
        setWaiting(false, targetKey)
        patchStreamingMessage({ isStreaming: false })
        delete assistantMsgIdsRef.current[targetKey]
      } else if (msg.type === 'error') {
        setProgress('', targetKey)
        setWaiting(false, targetKey)
        patchStreamingMessage({ isStreaming: false })
        delete assistantMsgIdsRef.current[targetKey]
        addMessage({
          id: nanoid(),
          role: 'assistant',
          content: `⚠️ ${msg.content ?? '发生错误'}`,
          timestamp: new Date().toISOString(),
        })
      }
    },
    [addMessage, setCurrentSession, setMessages, setProgress, setWaiting],
  )

  useEffect(() => {
    handleWsMessageRef.current = handleWsMessage
  }, [handleWsMessage])

  // Build context message
  const buildContextMessage = (userQuestion: string): string => {
    if (!workspacePath) return userQuestion

    const treeText = (nodes: FileNode[], indent = 0): string => {
      return nodes.map((n) => {
        const prefix = '  '.repeat(indent)
        if (n.type === 'directory') {
          const children = n.children ? treeText(n.children, indent + 1) : ''
          return `${prefix}📁 ${n.name}/\n${children}`
        }
        return `${prefix}📄 ${n.name}`
      }).join('\n')
    }

    const wsFullPath = `~/.nanobot/agentplayground/wave-record-parser/workspace/${workspacePath}`

    let ctx = `【任务类型：录波解析】你是继电保护故障分析专家。这不是定值校核任务，请勿使用 setting_check 相关工具。\n\n`
    ctx += `当前工作区：${workspacePath}\n`
    ctx += `工作区完整路径：${wsFullPath}\n\n`
    ctx += `工作区文件结构：\n${treeText(fileTree)}\n\n`
    ctx += `【可用工具】\n`
    ctx += `- read_file: 读取文件内容，路径格式 "${wsFullPath}/录波源文件/xxx.cfg"\n`
    ctx += `- glob: 搜索文件，例如 glob(pattern="**/*.cfg", path="${wsFullPath}")\n`
    ctx += `- trip_briefing_rerun: 重新生成跳闸简报（需要 job_id）\n`
    ctx += `- trip_briefing_read: 读取跳闸简报\n`
    ctx += `- trip_briefing_write: 修改跳闸简报章节\n`
    ctx += `【禁止使用】setting_check_read、setting_check_write、setting_check_generate（这些是定值校核的工具）\n\n`
    ctx += `【目录说明】\n`
    ctx += `- 录波源文件/: 录波原始文件\n`
    ctx += `  - 保护录波/: 保护装置录波文件（.cfg/.dat/.hdr/.rms.csv/.events.csv）\n`
    ctx += `  - 故障录波/: 故障录波器文件\n`
    ctx += `- 报告/: 跳闸简报输出目录\n\n`
    ctx += `【文件类型说明】\n`
    ctx += `- .cfg — 通道配置文件（文本，可读）：定义了采样率、通道名称、通道数量等\n`
    ctx += `- .hdr — 头文件（文本，可读）：包含装置信息、录波触发原因等\n`
    ctx += `- .dat — 采样数据（二进制，不可直接文本读取）：包含各通道的瞬时值采样数据\n`
    ctx += `- .rms.csv — 有效值数据（文本CSV，可读）：各通道的RMS值随时间变化\n`
    ctx += `- .events.csv — 事件记录（文本CSV，可读）：保护动作事件、开关变位等时序记录\n\n`
    ctx += `【重要】用户提到以下关键词时，指当前工作区：\n`
    ctx += `- "录波"/"波形"/"源文件" → ${wsFullPath}/录波源文件/ 目录\n`
    ctx += `- "报告"/"简报" → ${wsFullPath}/报告/ 目录\n`
    ctx += `- "HDR"/"头文件" → .hdr 文件\n`
    ctx += `- "事件" → .events.csv 文件\n`
    ctx += `- "有效值"/"RMS" → .rms.csv 文件\n`
    ctx += `当用户说"看一下录波"、"读取报告"等，直接用 read_file 读取对应目录下的文件即可。\n\n`
    ctx += `用户问题：${userQuestion}`
    return ctx
  }

  // File upload
  const handleChatUpload = async (fileList: FileList | File[]) => {
    if (!workspacePath) return
    const arr = Array.from(fileList)
    if (!arr.length) return
    const uploaded = await uploadFiles(workspacePath, arr)
    setAttachedFiles((prev) => [...prev, ...uploaded.map((f) => ({ name: f, path: f }))])
  }

  const handleChatDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setChatDragOver(false)
    const filePath = e.dataTransfer.getData('application/x-file-path')
    if (filePath) {
      const fileName = filePath.split('/').pop()!
      setAttachedFiles((prev) => [...prev, { name: fileName, path: filePath }])
      return
    }
    if (e.dataTransfer.files.length) {
      handleChatUpload(e.dataTransfer.files)
    }
  }

  // Send message
  const handleSend = useCallback(
    (content: string, displayContent?: string) => {
      if (!content.trim()) return
      if (!wsRef.current?.isConnected) wsRef.current?.connect()
      addMessage({
        id: nanoid(),
        role: 'user',
        content: displayContent ?? content,
        timestamp: new Date().toISOString(),
      })
      const key = useChatStore.getState().currentSessionKey ?? ''
      setWaiting(true, key)
      setProgress('思考中...', key)
      wsRef.current?.send(content, useChatStore.getState().currentSessionKey ?? undefined)
    },
    [addMessage, setProgress, setWaiting],
  )

  const handleStop = useCallback(() => {
    const key = useChatStore.getState().currentSessionKey ?? ''
    wsRef.current?.cancel(key)
    setWaiting(false, key)
    setProgress('', key)
  }, [setProgress, setWaiting])

  const handleNewChat = () => {
    useChatStore.getState().clearMessages()
    contextSentRef.current = false
    assistantMsgIdsRef.current = {}
  }

  const handleSendClick = () => {
    const text = chatInput.trim()
    if (!text || isWaiting) return

    const fileRefs = attachedFiles.map((f) => `[${f.name}](${f.path})`).join(' ')
    const fullText = (text + ' ' + fileRefs).trim()

    if (!contextSentRef.current && workspacePath) {
      contextSentRef.current = true
      handleSend(buildContextMessage(fullText), text)
    } else {
      handleSend(fullText, text)
    }
    setChatInput('')
    setAttachedFiles([])
  }

  if (!workspacePath) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-center">
          <MessageSquare className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <div className="text-sm">请先选择工作区</div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-3 py-2 border-b bg-gray-50/50 shrink-0">
        <Button
          variant="outline"
          size="sm"
          onClick={handleNewChat}
          disabled={isWaiting}
          title="新建对话"
        >
          <Plus className="w-3.5 h-3.5" />
          <span className="text-xs">新建</span>
        </Button>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {isConnected ? (
            <Wifi className="h-3.5 w-3.5 text-green-500" />
          ) : (
            <WifiOff className="h-3.5 w-3.5 text-destructive" />
          )}
          <span>{isConnected ? '已连接' : '未连接'}</span>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={messagesScrollRef}
        onScroll={handleMessagesScroll}
        className="flex-1 overflow-y-auto px-4 py-4 space-y-3 relative"
        onDragOver={(e) => { if (e.dataTransfer.types.includes('application/x-file-path') || e.dataTransfer.files.length) { e.preventDefault(); setChatDragOver(true) } }}
        onDragLeave={(e) => { if (e.currentTarget === e.target) setChatDragOver(false) }}
        onDrop={handleChatDrop}
      >
        {messages.length === 0 && !isWaiting && (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <MessageSquare className="w-10 h-10 mx-auto mb-2 opacity-20" />
              <div className="text-sm">输入消息开始对话</div>
              <div className="text-xs mt-1 text-gray-300">首次对话会自动加载工作区上下文</div>
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`group flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={cn(
                'max-w-[88%] px-3.5 py-2.5 rounded-xl text-sm',
                msg.role === 'user'
                  ? 'bg-teal-600 text-white rounded-br-sm'
                  : 'bg-white text-gray-800 border border-gray-200 rounded-bl-sm',
              )}
            >
              {msg.role === 'assistant' ? (
                <>
                  <MarkdownRenderer content={msg.content || ''} />
                  {msg.content && (
                    <div className="flex items-center gap-2 mt-1.5 pt-1.5 border-t border-gray-100">
                      <CopyButton getText={() => msg.content} />
                    </div>
                  )}
                </>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
        {showJumpBottom && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 flex items-center justify-center w-8 h-8 bg-white border border-gray-200 rounded-full text-gray-600 hover:text-teal-600 hover:border-teal-400 shadow-sm transition-colors"
            title="跳至最下方"
          >
            <ChevronDown className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Input + attached files chips */}
      <div
        className={`px-3 pb-3 pt-2 border-t ${chatDragOver ? 'border-teal-400 bg-teal-50' : 'border-gray-200'}`}
        onDragOver={(e) => { e.preventDefault(); setChatDragOver(true) }}
        onDragLeave={() => setChatDragOver(false)}
        onDrop={handleChatDrop}
      >
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {attachedFiles.map((f, i) => (
              <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-teal-50 text-teal-700 text-[12px] rounded-md border border-teal-200">
                <FileText className="w-3 h-3 shrink-0" />
                <span className="truncate max-w-[120px]">{f.name}</span>
                <button
                  className="text-teal-400 hover:text-teal-700 shrink-0"
                  onClick={() => setAttachedFiles((prev) => prev.filter((_, idx) => idx !== i))}
                  title="取消"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex gap-2 items-end p-3 bg-white">
          <Button
            variant="outline"
            size="icon"
            onClick={() => chatFileInputRef.current?.click()}
            disabled={isWaiting}
            title="上传附件"
            className="shrink-0 h-9 w-9 hover:text-sky-600 hover:border-sky-300"
          >
            <Paperclip className="w-4 h-4" />
          </Button>
          <input
            ref={chatFileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) handleChatUpload(e.target.files)
              e.target.value = ''
            }}
          />
          <Textarea
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSendClick()
              }
            }}
            placeholder={chatDragOver ? '松开添加文件' : '输入消息，Enter 发送'}
            rows={1}
            className="resize-none border-gray-200 bg-white text-sm min-h-[44px] max-h-[120px]"
            disabled={isWaiting}
          />
          {isWaiting ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={handleStop}
              className="shrink-0 h-9"
            >
              <Square className="w-3 h-3 fill-current" />
              停止
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleSendClick}
              disabled={!chatInput.trim()}
              className="shrink-0 h-9 bg-teal-600 hover:bg-teal-700 text-white"
            >
              <Send className="w-3.5 h-3.5" />
              发送
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function CopyButton({ getText }: { getText: () => string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className="ml-auto p-0.5 text-gray-400 hover:text-gray-700 transition-colors"
      onClick={() => {
        navigator.clipboard.writeText(getText())
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      title="复制"
    >
      {copied ? <Check className="w-3 h-3 text-teal-600" /> : <Copy className="w-3 h-3" />}
    </button>
  )
}
