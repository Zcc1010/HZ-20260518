import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { nanoid } from "nanoid";
import { useQueryClient } from "@tanstack/react-query";
import { useChatStore, type ChatMessage } from "../../stores/chatStore";
import { BRAND_ASSETS, BRAND_NAME } from "../../lib/branding";
import { ChatWebSocket, type WsMessage } from "../../lib/ws";
import { MessageBubble, extractArtifactPaths } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { useRevokeMessage } from "../../hooks/useSessions";
import { MessageSquare, BrainCircuit } from "lucide-react";

interface ChatWindowProps {
  urlSessionKey?: string;
  isLoading?: boolean;
  moduleTitle?: string;
  moduleIcon?: React.ElementType;
}

export function ChatWindow({ urlSessionKey, isLoading, moduleTitle, moduleIcon }: ChatWindowProps = {}) {
  const { t } = useTranslation();
  const ModuleIcon = moduleIcon;
  const qc = useQueryClient();
  const {
    currentSessionKey,
    messages,
    showToolMessages,
    addMessage,
    setWaiting,
    setProgress,
    setMessages,
    setCurrentSession,
    toggleToolMessages,
    markFeedbackSubmitted,
  } = useChatStore();

  // Read per-session state for the active session
  const sessionState = useChatStore((s) => {
    const key = s.currentSessionKey ?? "";
    return s.sessionStates[key] ?? { isWaiting: false, progressText: "" };
  });
  const isWaiting = sessionState.isWaiting;
  const progressText = sessionState.progressText;

  const visibleMessages = messages.filter((m) => {
    if (!showToolMessages) {
      if (m.role === "tool" || m.role === "sub_tool") {
        if (!extractArtifactPaths(m.content).length) return false;
      }
      if (m.role === "system") return false;
    }
    return true;
  });

  const wsRef = useRef<ChatWebSocket | null>(null);
  const assistantMsgIdsRef = useRef<Record<string, string>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const handleWsMessageRef = useRef<(msg: WsMessage) => void>(() => {});
  const cancelledRef = useRef(false);
  const [isConnected, setIsConnected] = useState(false);
  const revokeMessage = useRevokeMessage();

  useEffect(() => {
    const ws = new ChatWebSocket(
      (msg) => handleWsMessageRef.current(msg),
      (connected) => setIsConnected(connected),
    );
    wsRef.current = ws;
    ws.connect(useChatStore.getState().currentSessionKey ?? undefined);
    return () => {
      ws.disconnect();
    };
  }, []);

  // Keep the WebSocket's stored session key in sync so that reconnects
  // always use the current session (e.g. after clicking "new chat").
  useEffect(() => {
    if (currentSessionKey) {
      wsRef.current?.setSession(currentSessionKey);
    }
  }, [currentSessionKey]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, progressText]);

  const handleWsMessage = useCallback(
    (msg: WsMessage) => {
      // Determine which session this message belongs to
      const msgSessionKey = msg.session_key;
      const currentKey = useChatStore.getState().currentSessionKey;
      const targetKey = msgSessionKey || currentKey || "";

      const ensureStreamingMessage = () => {
        const state = useChatStore.getState();
        const existingId = assistantMsgIdsRef.current[targetKey];
        if (existingId && state.messages.some((message) => message.id === existingId)) {
          return existingId;
        }
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
        if (!state.messages.some((message) => message.id === streamId)) {
          delete assistantMsgIdsRef.current[targetKey];
          return false;
        }
        setMessages(
          state.messages.map((message) =>
            message.id === streamId ? { ...message, ...patch } : message
          )
        );
        return true;
      };

      if (msg.type === "session_info") {
        // Don't override session if we're navigating from a URL (e.g. feedback page link)
        if (msg.session_key && msg.session_key !== currentKey && !urlSessionKey) {
          setCurrentSession(msg.session_key);
        }
      } else if (msg.type === "stream_start") {
        if (cancelledRef.current) return;
        if (!msgSessionKey || msgSessionKey === currentKey) {
          ensureStreamingMessage();
        }
        setProgress("", targetKey);
      } else if (msg.type === "stream_delta") {
        if (cancelledRef.current) return;
        if ((!msgSessionKey || msgSessionKey === currentKey) && msg.content) {
          const streamId = ensureStreamingMessage();
          useChatStore.getState().appendAssistantText(streamId, msg.content);
        }
        setProgress("", targetKey);
      } else if (msg.type === "stream_end") {
        if (cancelledRef.current) return;
        if (!msgSessionKey || msgSessionKey === currentKey) {
          patchStreamingMessage({ isStreaming: false });
        }
        // Don't delete the ref here — let the "done" handler do final
        // cleanup. Deleting early causes "done" to add a duplicate message
        // because patchStreamingMessage can't find the streaming message.
      } else if (msg.type === "progress") {
        if (msg.content?.trim() && msg.tool_hint && (!msgSessionKey || msgSessionKey === currentKey)) {
          addMessage({
            id: nanoid(),
            role: "tool",
            content: msg.content,
            timestamp: new Date().toISOString(),
          });
        }
        setProgress(msg.content ?? "", targetKey);
      } else if (msg.type === "subagent_progress") {
        // Only show in UI if this is for the currently viewed session
        if (!msgSessionKey || msgSessionKey === currentKey) {
          if (msg.content?.trim()) {
            addMessage({
              id: nanoid(),
              role: "tool",
              content: msg.content,
              timestamp: new Date().toISOString(),
              isSubAgent: true,
            });
          }
        }
      } else if (msg.type === "done") {
        cancelledRef.current = false;
        setProgress("", targetKey);
        setWaiting(false, targetKey);

        const updatedStream = (!msgSessionKey || msgSessionKey === currentKey)
          ? patchStreamingMessage({
              isStreaming: false,
              ...(msg.content ? { content: msg.content } : {}),
              ...(msg.attachments ? { attachments: msg.attachments } : {}),
            })
          : false;
        delete assistantMsgIdsRef.current[targetKey];

        // Only add message to UI if it's for the currently viewed session
        if ((!msgSessionKey || msgSessionKey === currentKey) && !updatedStream) {
          if (msg.content?.trim() || msg.attachments?.length) {
            addMessage({
              id: nanoid(),
              role: "assistant",
              content: msg.content ?? "",
              timestamp: new Date().toISOString(),
              attachments: msg.attachments,
            });
          }
        }

        // Refresh sessions list and the session's messages
        qc.invalidateQueries({ queryKey: ["sessions"] });
        if (targetKey) {
          qc.invalidateQueries({ queryKey: ["sessions", targetKey, "messages"] });
        }
      } else if (msg.type === "error") {
        setProgress("", targetKey);
        setWaiting(false, targetKey);
        if (!msgSessionKey || msgSessionKey === currentKey) {
          patchStreamingMessage({ isStreaming: false });
        }
        delete assistantMsgIdsRef.current[targetKey];

        // Only show error in UI if it's for the currently viewed session
        if (!msgSessionKey || msgSessionKey === currentKey) {
          addMessage({
            id: nanoid(),
            role: "assistant",
            content: `⚠️ ${msg.content ?? t("common.error")}`,
            timestamp: new Date().toISOString(),
          });
        }
      } else if (msg.type === "revoke_ok") {
        // Refresh the session messages after revoke
        const targetKey = msgSessionKey || currentKey || "";
        qc.invalidateQueries({ queryKey: ["sessions", targetKey, "messages"] });
        qc.invalidateQueries({ queryKey: ["sessions"] });
      }
    },
    [addMessage, qc, setCurrentSession, setMessages, setProgress, setWaiting, t]
  );

  useEffect(() => {
    handleWsMessageRef.current = handleWsMessage;
  }, [handleWsMessage]);

  const handleSend = useCallback(
    (content: string) => {
      if (!wsRef.current?.isConnected) {
        wsRef.current?.connect();
      }
      cancelledRef.current = false;
      addMessage({
        id: nanoid(),
        role: "user",
        content,
        timestamp: new Date().toISOString(),
      });
      const key = currentSessionKey ?? "";
      setWaiting(true, key);
      setProgress(t("chat.thinking"), key);
      wsRef.current?.send(content, currentSessionKey ?? undefined);
    },
    [addMessage, currentSessionKey, setProgress, setWaiting, t]
  );

  const handleStop = useCallback(() => {
    const key = currentSessionKey ?? "";
    cancelledRef.current = true;
    wsRef.current?.cancel(key);
    setWaiting(false, key);
    setProgress("", key);
  }, [currentSessionKey, setProgress, setWaiting]);

  const handleRevoke = useCallback(
    (messageId: string) => {
      if (!currentSessionKey) return;
      const msg = messages.find((m) => m.id === messageId);
      if (!msg) return;
      const serverIndex = msg.serverIndex;
      if (serverIndex === undefined) return;
      if (serverIndex >= 0) {
        revokeMessage.mutate({ key: currentSessionKey, index: serverIndex });
      }
    },
    [currentSessionKey, messages, revokeMessage]
  );

  return (
    <div className="flex flex-1 min-h-0 flex-col">
      <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden px-4 py-6">
        {messages.length === 0 ? (
          isLoading ? (
            <div className="flex min-h-[420px] flex-col gap-4 p-6">
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 shrink-0 rounded-full bg-slate-200 animate-pulse" />
                <div className="h-4 w-48 rounded bg-slate-200 animate-pulse" />
              </div>
              <div className="flex items-center gap-3 justify-end">
                <div className="h-4 w-32 rounded bg-slate-200 animate-pulse" />
                <div className="h-8 w-8 shrink-0 rounded-full bg-slate-200 animate-pulse" />
              </div>
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 shrink-0 rounded-full bg-slate-200 animate-pulse" />
                <div className="space-y-2">
                  <div className="h-4 w-64 rounded bg-slate-200 animate-pulse" />
                  <div className="h-4 w-40 rounded bg-slate-200 animate-pulse" />
                </div>
              </div>
            </div>
          ) : (
          <div
            className="brand-chat-shell flex min-h-[420px] flex-col justify-between overflow-hidden rounded-[28px] border border-white/60 px-6 py-7 shadow-[var(--shadow-card)]"
            style={{
              backgroundImage: `linear-gradient(180deg, rgba(255, 255, 255, 0.92), rgba(243, 249, 255, 0.96)), url("${BRAND_ASSETS.background}")`,
            }}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-3">
                <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-xs text-[#298c88] shadow-sm">
                  <MessageSquare className="h-4 w-4" />
                  <span>可以尝试这样问我</span>
                </div>
                <div className="space-y-2">
                  <p className="brand-display brand-gradient-text text-3xl leading-none">{moduleTitle || BRAND_NAME}</p>
                  <p className="max-w-md text-sm leading-7 text-slate-600">{t("chat.noMessages")}</p>
                </div>
              </div>
              <div className="flex h-24 w-24 items-center justify-center rounded-[24px] bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-lg">
                {ModuleIcon ? <ModuleIcon className="h-14 w-14 text-white" /> : <BrainCircuit className="h-14 w-14 text-white" />}
              </div>
            </div>
            <div className="mt-8 rounded-[24px] bg-white/90 px-5 py-4 shadow-sm">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-[#298c88] to-[#00706b]">
                  <MessageSquare className="h-4 w-4 text-white" />
                </div>
                <div>
                  <p className="brand-display text-base text-[#0d5d57]">{moduleTitle || BRAND_NAME}</p>
                </div>
              </div>
            </div>
          </div>
          )
        ) : (
          <div className="space-y-4">
            {visibleMessages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                onRevoke={handleRevoke}
                onMarkFeedbackSubmitted={markFeedbackSubmitted}
                sessionKey={currentSessionKey ?? ""}
                artifactOnly={!showToolMessages && (msg.role === "tool" || msg.role === "sub_tool")}
              />
            ))}
          </div>
        )}
        {isWaiting && progressText && (
          <div className="mt-4 flex items-start gap-3 px-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#298c88] to-[#00706b] shadow-sm">
              <BrainCircuit className="h-4 w-4 text-white" />
            </div>
            <div className="rounded-2xl rounded-tl-sm bg-white/90 px-4 py-2.5 text-sm text-slate-600 shadow-sm flex items-center gap-2">
              <span className="flex gap-1">
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
                <span className="h-1.5 w-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
              </span>
              <span className="truncate max-w-xs">{progressText}</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <ChatInput
        onSend={handleSend}
        disabled={isWaiting}
        onStop={handleStop}
        isWaiting={isWaiting}
        isConnected={isConnected}
        showToolMessages={showToolMessages}
        onToggleToolMessages={toggleToolMessages}
      />
    </div>
  );
}
