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
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { cn } from "../lib/utils";
import { withBasePath } from "../lib/basePath";
import { MarkdownRenderer } from "../components/shared/MarkdownRenderer";
import { BRAND_NAME } from "../lib/branding";
import { ChatWebSocket, type WsMessage } from "../lib/ws";
import { useChatStore, type ChatMessage } from "../stores/chatStore";

interface WaveRecordJob {
  id: string;
  app_id: string;
  status: string;
  created_at: string;
  file_name: string;
  preview_url?: string;
  station?: string;
  device?: string;
  external_id?: string;
  progress?: number;
  progress_message?: string;
  error_message?: string;
}

async function fetchJob(jobIdOrExternalId: string): Promise<WaveRecordJob> {
  // 先尝试通过 external_id 查询
  try {
    const res = await fetch(withBasePath(`/api/wave-record-parser/jobs/by-external-id/${encodeURIComponent(jobIdOrExternalId)}`));
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // ignore
  }

  // 回退：查询所有任务，按内部 id 匹配
  const res = await fetch(withBasePath("/api/wave-record-parser/jobs"));
  if (!res.ok) throw new Error("Failed to fetch jobs");
  const jobs: WaveRecordJob[] = await res.json();
  const job = jobs.find((j) => j.id === jobIdOrExternalId || j.external_id === jobIdOrExternalId);
  if (!job) throw new Error("未找到简报");
  return job;
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

export default function TripBriefingPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [searchParams] = useSearchParams();
  const equipmentName = searchParams.get("equipmentName") || "";
  const navigate = useNavigate();

  // --- Job & preview state ---
  const [job, setJob] = useState<WaveRecordJob | null>(null);
  const [previewContent, setPreviewContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Display name falls back to route equipmentName when job data is empty
  const displayStation = job?.station || equipmentName.split(" ")[0] || "未知站点";
  const displayDevice = job?.device || equipmentName.split(" ").slice(1).join(" ") || equipmentName || "未知设备";

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
  const contextSentRef = useRef(false);
  const jobRef = useRef<WaveRecordJob | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [chatInput, setChatInput] = useState("");

  // --- Download by ID ---
  const handleDownloadById = useCallback(async () => {
    if (!jobId) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const res = await fetch(withBasePath(`/api/wave-record-parser/jobs/download-by-id/${encodeURIComponent(jobId)}`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "下载失败");
      }
      let newJob: WaveRecordJob = await res.json();
      // 如果 station/device 为空但 URL 带了 equipmentName，回填数据库
      if (!newJob.station && !newJob.device && equipmentName) {
        try {
          const patchRes = await fetch(withBasePath(`/api/wave-record-parser/jobs/${newJob.id}`), {
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
      setError(null);
      // 不跳转路由，保留原始外部事件ID和equipmentName参数
      // 如果任务还在处理中，开始轮询
      if (newJob.status === "queued" || newJob.status === "processing") {
        startPolling(newJob.id);
      } else if (newJob.status === "completed" && newJob.preview_url) {
        const content = await fetchPreview(newJob.preview_url);
        setPreviewContent(content);
        setDownloading(false);
      }
    } catch {
      setDownloadError("下载失败，请稍后重试");
      setDownloading(false);
    }
  }, [jobId, navigate]);

  // --- Polling for job status ---
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startPolling = useCallback((targetJobId: string) => {
    const poll = async () => {
      try {
        const res = await fetch(withBasePath(`/api/wave-record-parser/jobs`));
        if (!res.ok) return;
        const jobs: WaveRecordJob[] = await res.json();
        const currentJob = jobs.find(j => j.id === targetJobId);
        if (!currentJob) return;

        setJob(currentJob);

        if (currentJob.status === "completed") {
          setDownloading(false);
          if (currentJob.preview_url) {
            const content = await fetchPreview(currentJob.preview_url);
            setPreviewContent(content);
          }
          return;
        }

        if (currentJob.status === "failed") {
          setDownloading(false);
          setDownloadError("生成失败，请重试");
          return;
        }

        // 继续轮询
        pollTimerRef.current = setTimeout(poll, 3000);
      } catch {
        pollTimerRef.current = setTimeout(poll, 5000);
      }
    };
    pollTimerRef.current = setTimeout(poll, 3000);
  }, []);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  // --- Fetch job & preview ---
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
            const patchRes = await fetch(withBasePath(`/api/wave-record-parser/jobs/${data.id}`), {
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
          const content = await fetchPreview(data.preview_url);
          setPreviewContent(content);
          setLoading(false);
        } else if (data.status === "queued" || data.status === "processing") {
          // 任务还在处理中，开始轮询
          setDownloading(true);
          setLoading(false);
          startPolling(data.id);
        } else if (data.status === "failed") {
          setError("简报生成失败");
          setLoading(false);
        } else {
          setLoading(false);
        }
      })
      .catch(() => {
        setError("未找到该跳闸简报");
        setLoading(false);
      });
  }, [jobId, startPolling]);

  // Keep jobRef in sync with job state
  useEffect(() => {
    jobRef.current = job;
  }, [job]);

  // --- Clear chat when entering ---
  useEffect(() => {
    useChatStore.getState().clearMessages();
    contextSentRef.current = false;
  }, [jobId]);

  // --- WebSocket ---
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
        // 检测报告是否被修改，自动刷新左侧预览
        try {
          const state = useChatStore.getState();
          const lastAssistant = [...state.messages].reverse().find((m) => m.role === "assistant");
          if (lastAssistant && /已更新|已写回|已保存|已修改|已成功/.test(lastAssistant.content)) {
            const currentJob = jobRef.current;
            if (currentJob?.preview_url) {
              fetchPreview(currentJob.preview_url).then((content) => setPreviewContent(content));
            }
          }
        } catch { /* ignore */ }
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
      `任务 ID：${job?.id || jobId}\n` +
      `站点：${displayStation}\n` +
      `设备：${displayDevice}\n\n`;
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

  // --- Loading / Error states ---
  if (loading || downloading) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gradient-to-br from-[#f0f7fa] to-[#e8f4f3]">
        <div className="flex flex-col items-center gap-6 rounded-3xl bg-white/80 px-12 py-10 shadow-lg backdrop-blur-sm">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <Loader2 className="h-8 w-8 animate-spin text-white" />
          </div>
          <div className="text-center">
            <p className="text-lg font-medium text-[#333]">
              {downloading ? "正在下载录波文件" : "加载跳闸简报"}
            </p>
            {downloading && job?.progress_message && (
              <p className="mt-2 text-sm text-[#298c88]">{job.progress_message}</p>
            )}
            <p className="mt-2 text-sm text-[#888]">
              {downloading ? "正在生成简报，请耐心等待..." : "请稍候..."}
            </p>
          </div>
          {downloading && job?.progress !== undefined && job.progress > 0 && (
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

  if (error || !job) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gradient-to-br from-[#f0f7fa] to-[#e8f4f3]">
        <div className="flex flex-col items-center gap-6 rounded-3xl bg-white/80 px-12 py-10 shadow-lg backdrop-blur-sm">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <BrainCircuit className="h-8 w-8 text-white" />
          </div>
          <div className="text-center">
            <p className="text-lg font-medium text-[#333]">未找到简报</p>
            {jobId && (
              <p className="mt-1 text-sm text-[#555]">
                事件ID: {jobId}
                {equipmentName && ` | 装置: ${equipmentName}`}
              </p>
            )}
            <p className="mt-2 text-sm text-[#888]">
              {downloadError || "该故障事件暂无简报数据，点击下方按钮下载录波并生成"}
            </p>
          </div>
          <div className="flex flex-col items-center gap-3">
            <Button
              onClick={handleDownloadById}
              disabled={downloading}
              className="h-11 rounded-xl bg-gradient-to-r from-[#298c88] to-[#00706b] px-8 text-white shadow-md hover:from-[#0d5d57] hover:to-[#005a55] hover:shadow-lg transition-all"
            >
              {downloading ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  正在下载...
                </>
              ) : (
                "下载并生成简报"
              )}
            </Button>
            <Button
              variant="outline"
              onClick={() => navigate("/agentplayground/wave-record-parser")}
              className="h-10 rounded-xl border-[#d0e0e0] text-[#555] hover:bg-[#f0f7fa]"
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              返回录波解析
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-[#f2f3f7]">
      {/* ===== Left: Briefing Content ===== */}
      <div className="flex w-[50%] shrink-0 flex-col border-r border-[#e0e0e0] bg-white">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[#e8f0f0] px-5 py-4">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate("/agentplayground/wave-record-parser")}
            className="h-9 w-9 shrink-0 rounded-xl text-[#555] hover:bg-[#f0f7fa] hover:text-[#000]"
            title="返回录波解析"
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
          <div className="flex h-10 w-10 items-center justify-center rounded-[16px] bg-gradient-to-br from-[#298c88] to-[#00706b]">
            <BrainCircuit className="h-5 w-5 text-white" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">跳闸简报</p>
            <h3 className="brand-display text-lg text-[#000] truncate">
              {displayStation} - {displayDevice}
            </h3>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
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
            <p className="text-xs uppercase tracking-[0.18em] text-[#888]">AI 对话</p>
            <h3 className="brand-display text-lg text-[#000]">{BRAND_NAME} 故障分析助手</h3>
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
                简报已加载，可以开始提问分析故障原因
              </p>
              <div className="mt-4 rounded-2xl border border-[#e8f0f0] bg-[#f0f7fa]/60 px-4 py-3 text-left max-w-md">
                <p className="text-xs text-[#888]">当前简报</p>
                <p className="mt-1 text-sm font-medium text-[#000]">
                  {displayStation} - {displayDevice}
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
