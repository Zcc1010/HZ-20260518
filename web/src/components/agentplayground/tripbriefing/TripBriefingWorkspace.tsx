import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { nanoid } from "nanoid";
import {
  Loader2,
  FileText,
  ChevronLeft,
  ChevronRight,
  BrainCircuit,
  MessageSquare,
  Send,
  Square,
  Wifi,
  WifiOff,
  ArrowLeft,
  RefreshCw,
} from "lucide-react";
import { Button } from "../../ui/button";
import { Badge } from "../../ui/badge";
import { Textarea } from "../../ui/textarea";
import { cn } from "../../../lib/utils";
import { withBasePath } from "../../../lib/basePath";
import { MarkdownRenderer } from "../../shared/MarkdownRenderer";
import { BRAND_NAME } from "../../../lib/branding";
import { ChatWebSocket, type WsMessage } from "../../../lib/ws";
import { useChatStore, type ChatMessage } from "../../../stores/chatStore";

interface WaveRecordJob {
  id: string;
  app_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  created_at: string;
  updated_at: string;
  error_message?: string;
  file_name: string;
  result_file_name?: string;
  download_url?: string;
  preview_url?: string;
  station?: string;
  device?: string;
  progress: number;
  progress_message?: string;
  evaluation?: string;
  external_id?: string;
}

function formatDateTime(isoString: string): string {
  if (!isoString) return "";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    const h = String(date.getHours()).padStart(2, "0");
    const min = String(date.getMinutes()).padStart(2, "0");
    return `${y}-${m}-${d} ${h}:${min}`;
  } catch {
    return isoString;
  }
}

async function fetchJobs(): Promise<WaveRecordJob[]> {
  const res = await fetch(withBasePath("/api/wave-record-parser/jobs"));
  if (!res.ok) throw new Error("Failed to fetch jobs");
  return res.json();
}

async function fetchPreview(url: string): Promise<string> {
  const res = await fetch(withBasePath(url));
  if (!res.ok) return "加载失败";
  const data = await res.json();
  let text = (data.content || "").replace(/\r\n/g, "\n");
  const fenceIdx = text.indexOf("```markdown\n");
  if (fenceIdx !== -1) {
    text = text.slice(fenceIdx + 12);
    const closeIdx = text.lastIndexOf("\n```");
    if (closeIdx !== -1) text = text.slice(0, closeIdx);
    text = text.trim();
  }
  return text;
}

export function TripBriefingWorkspace() {
  const { t } = useTranslation();

  // --- Job list state ---
  const [jobs, setJobs] = useState<WaveRecordJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedJob, setSelectedJob] = useState<WaveRecordJob | null>(null);
  const [previewContent, setPreviewContent] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);

  const PAGE_SIZE = 10;
  const totalPages = Math.max(1, Math.ceil(jobs.length / PAGE_SIZE));
  const paginatedJobs = jobs.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  // --- Chat state ---
  const {
    messages,
    addMessage,
    setWaiting,
    setProgress,
    setMessages,
    setCurrentSession,
  } = useChatStore();

  const sessionState = useChatStore((s) => {
    const key = s.currentSessionKey ?? "";
    return s.sessionStates[key] ?? { isWaiting: false, progressText: "" };
  });
  const isWaiting = sessionState.isWaiting;
  const progressText = sessionState.progressText;

  const wsRef = useRef<ChatWebSocket | null>(null);
  const assistantMsgIdsRef = useRef<Record<string, string>>({});
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const handleWsMessageRef = useRef<(msg: WsMessage) => void>(() => {});
  const contextSentForJobRef = useRef<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [chatInput, setChatInput] = useState("");

  // --- Fetch jobs ---
  useEffect(() => {
    fetchJobs()
      .then((data) => {
        setJobs(data.filter((j) => j.status === "completed" && j.preview_url));
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  // Poll for new completed jobs
  useEffect(() => {
    const interval = setInterval(() => {
      fetchJobs()
        .then((data) => setJobs(data.filter((j) => j.status === "completed" && j.preview_url)))
        .catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, []);

  // --- Select a job: load preview, hide list ---
  const handleSelectJob = useCallback(async (job: WaveRecordJob) => {
    if (selectedJob?.id === job.id) return;
    setSelectedJob(job);
    setPreviewLoading(true);
    setPreviewContent("");
    useChatStore.getState().clearMessages();
    contextSentForJobRef.current = null;
    try {
      const content = await fetchPreview(job.preview_url!);
      setPreviewContent(content);
    } catch {
      setPreviewContent("加载失败");
    } finally {
      setPreviewLoading(false);
    }
  }, [selectedJob?.id]);

  // --- Back to list ---
  const handleBackToList = useCallback(() => {
    setSelectedJob(null);
    setPreviewContent("");
    useChatStore.getState().clearMessages();
    contextSentForJobRef.current = null;
  }, []);

  // --- WebSocket chat ---
  useEffect(() => {
    const ws = new ChatWebSocket(
      (msg) => handleWsMessageRef.current(msg),
      (connected) => setIsConnected(connected),
    );
    wsRef.current = ws;
    ws.connect(useChatStore.getState().currentSessionKey ?? undefined);
    return () => ws.disconnect();
  }, []);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, progressText]);

  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      const msgSessionKey = msg.session_key;
      const currentKey = useChatStore.getState().currentSessionKey;
      const targetKey = msgSessionKey || currentKey || "";

      const ensureStreamingMessage = () => {
        const state = useChatStore.getState();
        const existingId = assistantMsgIdsRef.current[targetKey];
        if (existingId && state.messages.some((m) => m.id === existingId)) return existingId;
        const nextId = nanoid();
        assistantMsgIdsRef.current[targetKey] = nextId;
        addMessage({
          id: nextId,
          role: "assistant",
          content: "",
          timestamp: new Date().toISOString(),
          isStreaming: true,
        });
        return nextId;
      };

      const patchStreamingMessage = (patch: Partial<ChatMessage>) => {
        const streamId = assistantMsgIdsRef.current[targetKey];
        if (!streamId) return false;
        const state = useChatStore.getState();
        if (!state.messages.some((m) => m.id === streamId)) {
          delete assistantMsgIdsRef.current[targetKey];
          return false;
        }
        setMessages(state.messages.map((m) => (m.id === streamId ? { ...m, ...patch } : m)));
        return true;
      };

      if (msg.type === "session_info") {
        if (msg.session_key && msg.session_key !== currentKey) {
          setCurrentSession(msg.session_key);
        }
      } else if (msg.type === "stream_start") {
        ensureStreamingMessage();
        setProgress("", targetKey);
      } else if (msg.type === "stream_delta") {
        if (msg.content) {
          const streamId = ensureStreamingMessage();
          useChatStore.getState().appendAssistantText(streamId, msg.content);
        }
        setProgress("", targetKey);
      } else if (msg.type === "stream_end") {
        patchStreamingMessage({ isStreaming: false });
        delete assistantMsgIdsRef.current[targetKey];
      } else if (msg.type === "progress") {
        setProgress(msg.content ?? "", targetKey);
      } else if (msg.type === "done") {
        setProgress("", targetKey);
        setWaiting(false, targetKey);
        patchStreamingMessage({ isStreaming: false });
        delete assistantMsgIdsRef.current[targetKey];
      } else if (msg.type === "error") {
        setProgress("", targetKey);
        setWaiting(false, targetKey);
        patchStreamingMessage({ isStreaming: false });
        delete assistantMsgIdsRef.current[targetKey];
        addMessage({
          id: nanoid(),
          role: "assistant",
          content: `⚠️ ${msg.content ?? "发生错误"}`,
          timestamp: new Date().toISOString(),
        });
      }
    },
    [addMessage, setCurrentSession, setMessages, setProgress, setWaiting],
  );

  useEffect(() => {
    handleWsMessageRef.current = handleWsMessage;
  }, [handleWsMessage]);

  const handleSend = useCallback(
    (content: string, displayContent?: string) => {
      if (!content.trim()) return;
      if (!wsRef.current?.isConnected) wsRef.current?.connect();
      addMessage({
        id: nanoid(),
        role: "user",
        content: displayContent ?? content,
        timestamp: new Date().toISOString(),
      });
      const key = useChatStore.getState().currentSessionKey ?? "";
      setWaiting(true, key);
      setProgress("思考中...", key);
      wsRef.current?.send(content, useChatStore.getState().currentSessionKey ?? undefined);
    },
    [addMessage, setProgress, setWaiting],
  );

  const handleStop = useCallback(() => {
    const key = useChatStore.getState().currentSessionKey ?? "";
    wsRef.current?.cancel(key);
    setWaiting(false, key);
    setProgress("", key);
  }, [setProgress, setWaiting]);

  const buildContextMessage = (userQuestion: string) => {
    let ctx =
      `以下是跳闸简报的完整内容，请基于这份简报回答后续问题。\n\n` +
      `--- 简报开始 ---\n${previewContent}\n--- 简报结束 ---\n\n` +
      `站点：${selectedJob?.station || "未知"}\n` +
      `设备：${selectedJob?.device || "未知"}\n\n`;
    ctx += `工作区中已加载本次录波的源文件（COMTRADE格式），根目录为：跳闸简报/录波源文件/\n`;
    ctx += `目录结构示例：\n`;
    ctx += `  跳闸简报/录波源文件/保护录波/{装置名}/xxx.cfg\n`;
    ctx += `  跳闸简报/录波源文件/保护录波/{装置名}/xxx.hdr\n`;
    ctx += `  跳闸简报/录波源文件/保护录波/{装置名}/xxx.dat\n`;
    ctx += `  跳闸简报/录波源文件/保护录波/{装置名}/xxx.rms.csv\n`;
    ctx += `  跳闸简报/录波源文件/保护录波/{装置名}/xxx.events.csv\n`;
    ctx += `  跳闸简报/录波源文件/故障录波/{装置名}/... (同上结构)\n`;
    ctx += `文件类型说明：\n`;
    ctx += `  .cfg        — 通道配置文件（文本，可读）：定义了采样率、通道名称、通道数量等\n`;
    ctx += `  .hdr        — 头文件（文本，可读）：包含装置信息、录波触发原因等\n`;
    ctx += `  .dat        — 采样数据（二进制，不可直接文本读取）：包含各通道的瞬时值采样数据\n`;
    ctx += `  .rms.csv    — 有效值数据（文本CSV，可读）：各通道的RMS值随时间变化，适合分析故障前后电气量变化\n`;
    ctx += `  .events.csv — 事件记录（文本CSV，可读）：保护动作事件、开关变位等时序记录\n`;
    ctx += `重要：\n`;
    ctx += `1. 文件在子目录中，必须用递归搜索。glob 工具用法示例：\n`;
    ctx += `   glob(pattern="**/*.cfg") — 列出所有 .cfg 文件\n`;
    ctx += `   glob(pattern="**/*.rms.csv") — 列出所有有效值文件\n`;
    ctx += `   glob(pattern="**/*.events.csv") — 列出所有事件文件\n`;
    ctx += `   glob(pattern="**/*.hdr") — 列出所有头文件\n`;
    ctx += `   注意：pattern 直接用 **/*.xxx，不要加中文路径前缀\n`;
    ctx += `2. 先用 glob 列出文件，再用 read_file 读取具体内容\n`;
    ctx += `3. 保护录波和故障录波目录下都可能有文件，都检查一下\n`;
    ctx += `4. .dat 是二进制文件，不要尝试以文本方式读取\n`;
    ctx += `5. .cfg 文件包含通道定义，可以用来了解录波包含哪些电气量\n`;
    ctx += `6. 当用户要求"查看波形"、"分析波形"、"重新分析"时，必须读取 .rms.csv 和 .events.csv 文件进行分析，不要读取 .dat 文件\n`;
    ctx += `7. .rms.csv 包含各通道的有效值（RMS）、突变量、突变时间等关键数据，是分析故障的主要数据源\n`;
    ctx += `8. .events.csv 包含保护动作事件和开关变位记录，是分析保护行为的主要数据源\n\n`;
    ctx += `用户问题：${userQuestion}`;
    return ctx;
  };

  const handleNewChat = () => {
    useChatStore.getState().clearMessages();
    contextSentForJobRef.current = null;
    assistantMsgIdsRef.current = {};
  };

  const handleSendClick = () => {
    const text = chatInput.trim();
    if (!text || isWaiting || !selectedJob) return;

    if (contextSentForJobRef.current !== selectedJob.id && previewContent) {
      contextSentForJobRef.current = selectedJob.id;
      handleSend(buildContextMessage(text), text);
    } else {
      handleSend(text);
    }
    setChatInput("");
  };

  return (
    <div className="flex h-full gap-4">
      {/* ===== Left Panel: List (visible when no job selected) ===== */}
      {!selectedJob && (
        <div className="flex w-[380px] shrink-0 flex-col rounded-[24px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#298c88] to-[#00706b]">
              <BrainCircuit className="h-5 w-5 text-white" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-[#888]">跳闸简报</p>
              <h3 className="brand-display text-lg text-[#000]">故障录波分析</h3>
            </div>
          </div>

          {/* Job List */}
          <div className="flex-1 overflow-y-auto">
            {loading && (
              <div className="flex items-center justify-center py-10 text-[#666]">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="ml-2">{t("agentPlayground.loading")}</span>
              </div>
            )}

            {error && (
              <div className="mx-4 mt-4 rounded-xl border border-red-300 bg-[#f5d5d5]/50 p-3 text-sm text-[#cc3333]">
                {error}
              </div>
            )}

            {!loading && !error && paginatedJobs.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-[#888]">
                <FileText className="h-10 w-10 mb-3 opacity-40" />
                <p className="text-sm">暂无已完成的跳闸简报</p>
              </div>
            )}

            {!loading && !error && paginatedJobs.map((job) => (
              <button
                key={job.id}
                type="button"
                onClick={() => handleSelectJob(job)}
                className="w-full border-b border-[#e8f0f0] px-5 py-4 text-left transition-colors hover:bg-[#f0f7fa]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-[#000]">
                      {job.station || "未知站点"}
                    </p>
                    <p className="mt-1 truncate text-xs text-[#666]">
                      {job.device || "未知设备"} · {job.file_name}
                    </p>
                  </div>
                  <Badge className="shrink-0 rounded-full bg-[#dcecec] text-[#0d5d57] px-2 py-0.5 text-xs">
                    {t(`agentPlayground.status.${job.status}`)}
                  </Badge>
                </div>
                <p className="mt-2 text-xs text-[#888]">{formatDateTime(job.created_at)}</p>
              </button>
            ))}
          </div>

          {/* Pagination */}
          {jobs.length > PAGE_SIZE && (
            <div className="flex items-center justify-between border-t border-[#e8f0f0] bg-[#f0f7fa]/50 px-4 py-2">
              <p className="text-xs text-[#666]">
                第 {currentPage}/{totalPages} 页
              </p>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-[#e0e0e0] bg-white text-[#555] transition-colors hover:bg-[#f0f7fa] disabled:opacity-40"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ===== Middle Panel: Briefing Content (visible when job selected) ===== */}
      {selectedJob && (
        <div className="flex w-[480px] shrink-0 flex-col rounded-[24px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden">
          {/* Header with back button */}
          <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
            <Button
              variant="ghost"
              size="icon"
              onClick={handleBackToList}
              className="h-9 w-9 shrink-0 rounded-xl text-[#555] hover:bg-[#f0f7fa] hover:text-[#000]"
              title="返回列表"
            >
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#298c88] to-[#00706b]">
              <BrainCircuit className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs uppercase tracking-[0.18em] text-[#888]">跳闸简报</p>
              <h3 className="brand-display text-lg text-[#000] truncate">
                {selectedJob.station} - {selectedJob.device}
              </h3>
            </div>
          </div>

          {/* Briefing content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {previewLoading ? (
              <div className="flex items-center justify-center py-10 text-[#666]">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="ml-2">加载简报...</span>
              </div>
            ) : (
              <div className="prose prose-sm max-w-none">
                <MarkdownRenderer content={previewContent} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===== Right Panel: AI Chat ===== */}
      <div className="flex flex-1 flex-col rounded-[24px] border border-[#e0e0e0] bg-white shadow-md overflow-hidden">
        {/* Chat Header */}
        <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#4760ff] to-[#21406b]">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="brand-display text-lg text-[#000]">{BRAND_NAME}</h3>
          </div>
          <div className="flex items-center gap-2">
            {selectedJob && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleNewChat}
                className="h-7 gap-1 border-[#e0e0e0] text-xs text-[#555] hover:bg-[#f0f7fa]"
                title="新对话"
              >
                <RefreshCw className="h-3 w-3" />
                新对话
              </Button>
            )}
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              {isConnected ? (
                <Wifi className="h-3.5 w-3.5 text-green-500" />
              ) : (
                <WifiOff className="h-3.5 w-3.5 text-destructive" />
              )}
              <span>{isConnected ? "已连接" : "未连接"}</span>
            </div>
          </div>
        </div>

        {/* Chat Messages */}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-5 py-4">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
                <BrainCircuit className="h-8 w-8 text-white" />
              </div>
              <p className="brand-display text-lg text-[#21406b]">{BRAND_NAME} 故障分析助手</p>
              <p className="mt-2 max-w-sm text-sm text-[#888] leading-6">
                {selectedJob
                  ? "简报已加载，可以开始提问分析故障原因"
                  : "请从左侧选择一份跳闸简报，然后向我提问"}
              </p>
              {selectedJob && (
                <div className="mt-4 rounded-2xl border border-[#e8f0f0] bg-[#f0f7fa]/60 px-4 py-3 text-left max-w-md">
                  <p className="text-xs text-[#888]">当前简报</p>
                  <p className="mt-1 text-sm font-medium text-[#000]">
                    {selectedJob.station} - {selectedJob.device}
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={cn("flex items-start gap-3", msg.role === "user" && "flex-row-reverse")}
                >
                  {msg.role === "assistant" && (
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-sm">
                      <BrainCircuit className="h-4 w-4 text-white" />
                    </div>
                  )}
                  <div
                    className={cn(
                      "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm",
                      msg.role === "user"
                        ? "rounded-tr-sm bg-[#298c88] text-white"
                        : "rounded-tl-sm bg-white/90 text-slate-700 border border-[#e8f0f0]",
                    )}
                  >
                    {msg.role === "user" ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      <MarkdownRenderer content={msg.content} />
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {isWaiting && progressText && (
            <div className="mt-4 flex items-start gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-sm">
                <BrainCircuit className="h-4 w-4 text-white" />
              </div>
              <div className="rounded-2xl rounded-tl-sm bg-white/90 px-4 py-2.5 text-sm text-slate-600 shadow-sm flex items-center gap-2 border border-[#e8f0f0]">
                <span className="flex gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
                  <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
                </span>
                <span className="truncate max-w-xs">{progressText}</span>
              </div>
            </div>
          )}
        </div>

        {/* Chat Input */}
        <div className="border-t border-[#e8f0f0] px-4 py-3">
          <div className="flex items-end gap-2">
            <Textarea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSendClick();
                }
              }}
              placeholder={
                selectedJob
                  ? `询问关于 ${selectedJob.station} ${selectedJob.device} 的故障分析...`
                  : "请先选择一份跳闸简报..."
              }
              rows={1}
              disabled={!selectedJob}
              className="resize-none border-[#e0e0e0] bg-[#f0f7fa] focus-visible:ring-[#298c88] text-sm min-h-[44px] max-h-[120px]"
            />
            {isWaiting ? (
              <Button
                size="icon"
                variant="destructive"
                onClick={handleStop}
                className="h-[44px] w-[44px] shrink-0 rounded-xl"
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                size="icon"
                onClick={handleSendClick}
                disabled={!chatInput.trim() || !selectedJob}
                className="h-[44px] w-[44px] shrink-0 rounded-xl bg-[#298c88] hover:bg-[#0d5d57]"
              >
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
          <p className="mt-1.5 text-xs text-[#888]">Enter 发送 · Shift+Enter 换行</p>
        </div>
      </div>
    </div>
  );
}
