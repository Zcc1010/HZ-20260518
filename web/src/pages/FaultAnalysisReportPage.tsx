import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { nanoid } from "nanoid";
import {
  Loader2,
  ArrowLeft,
  MessageSquare,
  Send,
  Square,
  Wifi,
  WifiOff,
  BrainCircuit,
  RefreshCw,
  Download,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { cn } from "../lib/utils";
import { withBasePath } from "../lib/basePath";
import { MarkdownRenderer } from "../components/shared/MarkdownRenderer";
import { BRAND_NAME } from "../lib/branding";
import { ChatWebSocket, type WsMessage } from "../lib/ws";
import { useChatStore, type ChatMessage } from "../stores/chatStore";

interface FaultAnalysisJob {
  id: string;
  status: string;
  created_at: string;
  updated_at: string;
  error_message?: string;
  station: string;
  device: string;
  device_type: string;
  voltage_level: string;
  result_file_name?: string;
  download_url?: string;
  preview_url?: string;
  progress: number;
  progress_message?: string;
}

async function fetchJob(jobId: string): Promise<FaultAnalysisJob> {
  const res = await fetch(withBasePath(`/api/fault-analysis/jobs/${jobId}`));
  if (!res.ok) throw new Error("Failed to fetch job");
  return res.json();
}

async function fetchPreview(jobId: string): Promise<string> {
  const res = await fetch(withBasePath(`/api/fault-analysis/jobs/${jobId}/preview`));
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

function formatDateTime(isoString: string): string {
  if (!isoString) return "";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return isoString;
  }
}

export default function FaultAnalysisReportPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const equipmentName = searchParams.get("equipmentName") || "";
  const navigate = useNavigate();

  const [job, setJob] = useState<FaultAnalysisJob | null>(null);
  const [previewContent, setPreviewContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const displayStation = job?.station || equipmentName.split(" ")[0] || "未知站点";
  const displayDevice = job?.device || equipmentName.split(" ").slice(1).join(" ") || equipmentName || "未知设备";

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
  const contextSentRef = useRef(false);
  const jobRef = useRef<FaultAnalysisJob | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [chatInput, setChatInput] = useState("");

  // Polling for processing jobs
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startPolling = useCallback((targetJobId: string) => {
    setPolling(true);
    const poll = async () => {
      try {
        const currentJob = await fetchJob(targetJobId);
        setJob(currentJob);

        if (currentJob.status === "completed") {
          setPolling(false);
          if (currentJob.preview_url) {
            const content = await fetchPreview(targetJobId);
            setPreviewContent(content);
          }
          return;
        }
        if (currentJob.status === "failed") {
          setPolling(false);
          setError(currentJob.error_message || "分析失败");
          return;
        }
        pollTimerRef.current = setTimeout(poll, 3000);
      } catch {
        pollTimerRef.current = setTimeout(poll, 5000);
      }
    };
    pollTimerRef.current = setTimeout(poll, 3000);
  }, []);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);

  // Download from data platform and create job
  const downloadAndCreate = useCallback(async (eventId: string) => {
    try {
      const res = await fetch(withBasePath(`/api/fault-analysis/jobs/download-by-id/${eventId}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ equipmentName }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || "下载失败");
      }
      let newJob = await res.json();
      // 如果 station/device 为空但 URL 带了 equipmentName，回填数据库
      if (!newJob.station && !newJob.device && equipmentName) {
        try {
          const patchRes = await fetch(withBasePath(`/api/fault-analysis/jobs/${newJob.id}`), {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              station: equipmentName,
              device: equipmentName,
            }),
          });
          if (patchRes.ok) {
            newJob = await patchRes.json();
          }
        } catch { /* ignore */ }
      }
      setJob(newJob);
      if (newJob.status === "completed" && newJob.preview_url) {
        const content = await fetchPreview(newJob.id);
        setPreviewContent(content);
        setLoading(false);
      } else {
        setLoading(false);
        startPolling(newJob.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "从数据平台下载录波文件失败");
      setLoading(false);
    }
  }, [startPolling, equipmentName]);

  // Fetch job & preview
  useEffect(() => {
    if (!jobId) {
      setError("缺少任务 ID");
      setLoading(false);
      return;
    }
    fetchJob(jobId)
      .then(async (data) => {
        // 如果 station/device 为空但 URL 带了 equipmentName，回填数据库
        if (!data.station && !data.device && equipmentName) {
          try {
            const patchRes = await fetch(withBasePath(`/api/fault-analysis/jobs/${data.id}`), {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                station: equipmentName,
                device: equipmentName,
              }),
            });
            if (patchRes.ok) {
              data = await patchRes.json();
            }
          } catch { /* ignore */ }
        }
        setJob(data);
        if (data.status === "completed" && data.preview_url) {
          const content = await fetchPreview(jobId);
          setPreviewContent(content);
          setLoading(false);
        } else if (data.status === "processing" || data.status === "queued") {
          setLoading(false);
          startPolling(data.id);
        } else if (data.status === "failed") {
          setError(data.error_message || "分析失败");
          setLoading(false);
        } else {
          setLoading(false);
        }
      })
      .catch(() => {
        // Job not found, try downloading from data platform
        downloadAndCreate(jobId);
      });
  }, [jobId, startPolling, downloadAndCreate]);

  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  // Clear chat when entering
  useEffect(() => {
    useChatStore.getState().clearMessages();
    contextSentRef.current = false;
  }, [jobId]);

  // WebSocket
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
      `以下是电网故障智能分析报告的完整内容，请基于这份报告回答后续问题。\n\n` +
      `--- 报告开始 ---\n${previewContent}\n--- 报告结束 ---\n\n` +
      `任务 ID：${job?.id || jobId}\n` +
      `厂站：${displayStation}\n` +
      `设备：${displayDevice}\n` +
      `设备类型：${job?.device_type || "未知"}\n` +
      `电压等级：${job?.voltage_level || "未知"}\n\n`;
    ctx += `重要行为规则：\n`;
    ctx += `- 当你重新生成或修改了报告后，必须告知用户"左侧报告已自动更新"。\n`;
    ctx += `- 不要主动提供下载链接，除非用户明确要求下载。\n\n`;
    ctx += `用户问题：${userQuestion}`;
    return ctx;
  };

  const handleNewChat = () => {
    useChatStore.getState().clearMessages();
    contextSentRef.current = false;
    assistantMsgIdsRef.current = {};
  };

  const handleSendClick = () => {
    const text = chatInput.trim();
    if (!text || isWaiting || !job) return;

    if (!contextSentRef.current && previewContent) {
      contextSentRef.current = true;
      handleSend(buildContextMessage(text), text);
    } else {
      handleSend(text);
    }
    setChatInput("");
  };

  // Loading state
  if (loading || polling) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gradient-to-br from-[#f0f7fa] to-[#e8f4f3]">
        <div className="flex flex-col items-center gap-6 rounded-3xl bg-white/80 px-12 py-10 shadow-lg backdrop-blur-sm">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <Loader2 className="h-8 w-8 animate-spin text-white" />
          </div>
          <div className="text-center">
            <p className="text-lg font-medium text-[#333]">
              {polling ? "正在生成分析报告" : "加载分析报告"}
            </p>
            {polling && job?.progress_message && (
              <p className="mt-2 text-sm text-[#298c88]">{job.progress_message}</p>
            )}
            <p className="mt-2 text-sm text-[#888]">
              {polling ? "请耐心等待..." : "请稍候..."}
            </p>
          </div>
          {polling && job?.progress !== undefined && job.progress > 0 && (
            <div className="w-48 overflow-hidden rounded-full bg-[#e8f0f0]">
              <div
                className="h-1.5 rounded-full bg-gradient-to-r from-[#298c88] to-[#00b3a6] transition-all duration-500"
                style={{ width: `${job.progress}%` }}
              />
            </div>
          )}
        </div>
      </div>
    );
  }

  // Error state
  if (error || !job) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gradient-to-br from-[#f0f7fa] to-[#e8f4f3]">
        <div className="flex flex-col items-center gap-6 rounded-3xl bg-white/80 px-12 py-10 shadow-lg backdrop-blur-sm">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <BrainCircuit className="h-8 w-8 text-white" />
          </div>
          <div className="text-center">
            <p className="text-lg font-medium text-[#333]">未找到分析报告</p>
            {jobId && (
              <p className="mt-1 text-sm text-[#555]">任务 ID: {jobId}</p>
            )}
            <p className="mt-2 text-sm text-[#888]">{error || "该任务暂无分析报告"}</p>
          </div>
          <Button
            variant="outline"
            onClick={() => navigate("/fault-analysis")}
            className="h-10 rounded-xl border-[#d0e0e0] text-[#555] hover:bg-[#f0f7fa]"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            返回故障分析
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#f2f3f7]">
      {/* ===== Left: Report Content ===== */}
      <div className="flex w-[50%] shrink-0 flex-col border-r border-[#e0e0e0] bg-white">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate("/fault-analysis")}
            className="h-9 w-9 shrink-0 rounded-xl text-[#555] hover:bg-[#f0f7fa] hover:text-[#000]"
            title="返回故障分析"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <BrainCircuit className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">故障分析报告</p>
            <h3 className="brand-display text-lg text-[#000] truncate">
              {displayStation} - {displayDevice}
            </h3>
          </div>
          {job.download_url && (
            <a
              href={withBasePath(job.download_url)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[#e0e0e0] px-3 py-1.5 text-xs text-[#555] hover:bg-[#f0f7fa] transition-colors"
              title="下载报告"
            >
              <Download className="h-3.5 w-3.5" />
              下载
            </a>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {job.updated_at && (
            <div className="mb-4 flex items-center gap-2 text-xs text-[#888]">
              <span>报告生成时间：{formatDateTime(job.updated_at)}</span>
            </div>
          )}
          <div className="prose prose-sm max-w-none">
            <MarkdownRenderer content={previewContent} />
          </div>
        </div>
      </div>

      {/* ===== Right: AI Chat ===== */}
      <div className="flex flex-1 flex-col bg-white">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#298c88] to-[#0d5d57]">
            <MessageSquare className="h-5 w-5 text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="brand-display text-lg text-[#000]">{BRAND_NAME}</h3>
          </div>
          <div className="flex items-center gap-2">
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

        {/* Messages */}
        <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-5 py-4">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
                <BrainCircuit className="h-8 w-8 text-white" />
              </div>
              <p className="brand-display text-lg text-[#21406b]">{BRAND_NAME} 故障分析助手</p>
              <p className="mt-2 max-w-sm text-sm text-[#888] leading-6">
                报告已加载，可以开始提问分析故障原因
              </p>
              <div className="mt-4 rounded-2xl border border-[#e8f0f0] bg-[#f0f7fa]/60 px-4 py-3 text-left max-w-md">
                <p className="text-xs text-[#888]">当前分析</p>
                <p className="mt-1 text-sm font-medium text-[#000]">
                  {displayStation} - {displayDevice}
                </p>
                <p className="text-xs text-[#888] mt-0.5">
                  {job.device_type} · {job.voltage_level}
                </p>
              </div>
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

        {/* Input */}
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
              placeholder={`询问关于 ${displayStation} ${displayDevice} 的故障分析...`}
              rows={1}
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
                disabled={!chatInput.trim()}
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
