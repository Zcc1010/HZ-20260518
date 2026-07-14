import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChatWindow } from "../components/chat/ChatWindow";
import { WaveRecordWorkspace } from "../components/agentplayground/waverecord/WaveRecordWorkspace";
import { SettingCheckWorkspace } from "../components/agentplayground/settingcheck/SettingCheckWorkspace";
import { WaveRecordJobList, type WaveRecordJob } from "../components/agentplayground/waverecord/WaveRecordJobList";
import { SettingCheckJobList, type SettingCheckJob } from "../components/agentplayground/settingcheck/SettingCheckJobList";
import { useChatStore, type ChatMessage } from "../stores/chatStore";
import { useSessions, useSessionMessages } from "../hooks/useSessions";
import { useAuthStore } from "../stores/authStore";
import { useDeleteSession } from "../hooks/useSessions";
import { useIsMobile } from "../hooks/useIsMobile";
import { nanoid } from "nanoid";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { ArrowLeft, MessageSquare, Plus, Search, Trash2 } from "lucide-react";
import { cn, formatDate } from "../lib/utils";
import { CHANNEL_ICONS } from "../lib/channelIcons";

type ActiveModule = "chat" | "wave-record" | "setting-check";

/** Extract the channel prefix from a session key, e.g. "feishu", "telegram", "web" */
function channelOf(key: string): string {
  return key.split(":")[0] ?? "web";
}

function rawSessionLabel(key: string): string {
  const parts = key.split(":");
  const channel = channelOf(key);
  if (channel === "web") {
    return parts[2] ?? key;
  }
  return parts[parts.length - 1] ?? key;
}

function looksLikeWebSessionId(label: string): boolean {
  return /^[0-9a-f]{8}$/i.test(label);
}

function compactPreviewText(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/^[#>*`\-\d.\s]+/, "")
    .trim();
}

function sessionDisplayLabel(
  key: string,
  lastMessage: string | undefined,
  fallbackLabel: string,
): string {
  const rawLabel = rawSessionLabel(key);
  if (!(channelOf(key) === "web" && looksLikeWebSessionId(rawLabel))) {
    return rawLabel;
  }
  const previewLabel = compactPreviewText(lastMessage ?? "");
  return previewLabel || fallbackLabel;
}

export default function Chat() {
  const { t } = useTranslation();
  const { sessionKey: urlSessionKey } = useParams<{ sessionKey?: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const authlessEnabled = useAuthStore((s) => s.authlessEnabled);
  const isMobile = useIsMobile();
  const mobileShowChat = useChatStore((s) => s.mobileShowChat);
  const setMobileShowChat = useChatStore((s) => s.setMobileShowChat);
  const { currentSessionKey, setCurrentSession, setMessages } = useChatStore();
  const sessionStates = useChatStore((s) => s.sessionStates);
  const { data: sessions } = useSessions();
  const { data: sessionMsgs, isSuccess: historyLoaded } = useSessionMessages(currentSessionKey ?? "");
  const deleteSession = useDeleteSession();
  const loadedKeyRef = useRef<string | null>(null);
  const loadedCountRef = useRef<number>(0);
  const urlKeyInitializedRef = useRef(false);

  // Active module from pathname
  const activeModule: ActiveModule = useMemo(() => {
    if (location.pathname === "/wave-record") return "wave-record";
    if (location.pathname === "/setting-check") return "setting-check";
    return "chat";
  }, [location.pathname]);

  // Selected job for tools
  const [selectedWaveJob, setSelectedWaveJob] = useState<WaveRecordJob | null>(null);
  const [selectedSettingJob, setSelectedSettingJob] = useState<SettingCheckJob | null>(null);

  // Sync URL sessionKey to store
  useEffect(() => {
    if (urlSessionKey && !urlKeyInitializedRef.current) {
      urlKeyInitializedRef.current = true;
      setCurrentSession(urlSessionKey);
    }
  }, [urlSessionKey]);

  const lastSetMsgsRef = useRef<ChatMessage[]>([]);

  useEffect(() => {
    lastSetMsgsRef.current = [];
  }, [currentSessionKey]);

  useEffect(() => {
    if (!currentSessionKey || !historyLoaded) return;
    const serverCount = (sessionMsgs ?? []).length;
    if (loadedKeyRef.current === currentSessionKey && serverCount === loadedCountRef.current) return;
    loadedKeyRef.current = currentSessionKey;
    loadedCountRef.current = serverCount;
    const msgs = (sessionMsgs ?? [])
      .map((m, idx) => ({ ...m, _serverIdx: idx }))
      .filter((m) =>
        (((typeof m.content === "string" && m.content.trim().length > 0) ||
          ((m.attachments?.length ?? 0) > 0))) &&
        !(m.role === "tool" && m.name === "message") &&
        !(m.role === "system" && m.content === "[Background task progress]")
      )
      .map((m) => ({
        id: nanoid(),
        role: m.role as "user" | "assistant" | "tool" | "system" | "sub_tool",
        content: m.content as string,
        timestamp: m.timestamp ?? new Date().toISOString(),
        name: m.name ?? undefined,
        serverIndex: m._serverIdx,
        toolCalls: m.tool_calls?.map((tc) => ({
          id: tc.id,
          name: tc.function?.name ?? "",
          input: tc.function?.arguments,
        })),
        attachments: m.attachments ?? undefined,
      }));
    const prevIds = new Set(lastSetMsgsRef.current.map((m) => m.id));
    const localToPreserve = useChatStore.getState().messages.filter(
      (m) =>
        !prevIds.has(m.id) &&
        m.role === "assistant" &&
        m.content.startsWith("⚠️")
    );
    const merged = localToPreserve.length > 0 ? [...msgs, ...localToPreserve] : msgs;
    lastSetMsgsRef.current = merged;
    setMessages(merged);
  }, [currentSessionKey, historyLoaded, sessionMsgs, setMessages]);

  const isAdmin = !authlessEnabled && user?.role === "admin";
  const myPrefix = `web:${user?.id}:`;
  const [search, setSearch] = useState("");
  const mySessions = useMemo(
    () =>
      isAdmin
        ? (sessions ?? []).slice().sort((a, b) =>
            (b.updated_at ?? "").localeCompare(a.updated_at ?? "")
          )
        : (sessions?.filter((s) => s.key.startsWith(myPrefix)) ?? []),
    [isAdmin, myPrefix, sessions]
  );

  useEffect(() => {
    if (mySessions.length === 0) return;
    if (urlSessionKey) return;
    if (activeModule !== "chat") return;
    const keyExists = currentSessionKey && mySessions.some((s) => s.key === currentSessionKey);
    if (!keyExists && !currentSessionKey?.startsWith(myPrefix)) {
      setCurrentSession(mySessions[0].key);
    }
  }, [mySessions, currentSessionKey, setCurrentSession, myPrefix, urlSessionKey, activeModule]);

  const displaySessions = useMemo(() => {
    const isLocalNew =
      currentSessionKey?.startsWith(myPrefix) &&
      !mySessions.some((s) => s.key === currentSessionKey);
    if (isLocalNew && currentSessionKey) {
      return [{ key: currentSessionKey, updated_at: new Date().toISOString(), last_message: undefined }, ...mySessions];
    }
    return mySessions;
  }, [currentSessionKey, myPrefix, mySessions]);

  const filteredSessions = useMemo(() => {
    if (!search.trim()) return displaySessions;
    const q = search.toLowerCase();
    return displaySessions.filter((s) => {
      const label = sessionDisplayLabel(s.key, s.last_message, t("chat.newChat")).toLowerCase();
      const preview = (s.last_message ?? "").toLowerCase();
      return label.includes(q) || preview.includes(q);
    });
  }, [displaySessions, search, t]);

  const newChat = () => {
    const hexId = Array.from(crypto.getRandomValues(new Uint8Array(4)), (b) =>
      b.toString(16).padStart(2, "0")
    ).join("");
    const key = `web:${user?.id}:${hexId}`;
    loadedKeyRef.current = key;
    loadedCountRef.current = 0;
    setCurrentSession(key);
    navigate("/chat", { replace: true });
    if (isMobile) setMobileShowChat(true);
  };

  const switchSession = (key: string) => {
    setCurrentSession(key);
    navigate("/chat", { replace: true });
    if (isMobile) setMobileShowChat(true);
  };

  // B panel title
  const bPanelTitle = useMemo(() => {
    switch (activeModule) {
      case "chat": return t("chat.sessions", "会话列表");
      case "wave-record": return t("chat.waveRecord", "录波解析");
      case "setting-check": return t("chat.settingCheck", "定值校核");
    }
  }, [activeModule, t]);

  return (
    <div className={cn(
      "flex min-h-0",
      isMobile ? "flex-1 flex-col" : "h-full gap-4 p-5"
    )}>
      {/* B Panel - List Area (hidden for tools) */}
      <aside
        className={cn(
          "flex shrink-0 flex-col overflow-hidden",
          isMobile
            ? cn("w-full flex-1 min-h-0 pt-14 bg-background", mobileShowChat && "hidden")
            : cn("w-64 min-w-0 rounded-[24px] brand-panel", activeModule !== "chat" && "hidden")
        )}
        style={isMobile ? undefined : { width: "16rem", minWidth: 0, maxWidth: "16rem", boxShadow: "var(--shadow-card)" }}
      >
        {/* B Panel Header */}
        <div className={cn(
          "shrink-0 flex items-center justify-between border-b border-[#e8f0f0]",
          isMobile ? "px-4 py-3" : "px-3 py-2.5"
        )}>
          <h3 className={cn(
            "font-semibold text-[#0d5d57]",
            isMobile ? "text-base" : "text-sm"
          )}>
            {bPanelTitle}
          </h3>
          {activeModule === "chat" && (
            <button
              onClick={newChat}
              title={t("chat.newChat")}
              className="flex h-7 w-7 items-center justify-center rounded-full text-[#298c88] transition-colors hover:bg-[#e8f0f0] hover:text-[#0d5d57]"
            >
              <Plus className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* B Panel Content */}
        {activeModule === "chat" && (
          <>
            {/* Search */}
            <div className={cn("shrink-0", isMobile ? "px-4 pt-2 pb-3" : "px-3 py-2")}>
              <div className="relative">
                <Search className={cn(
                  "absolute top-1/2 -translate-y-1/2 text-muted-foreground/50",
                  isMobile ? "left-3.5 h-4 w-4" : "left-2.5 h-3.5 w-3.5"
                )} />
                <Input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("chat.searchSessions")}
                  className={cn(
                    "border-0 bg-white/80 focus-visible:ring-1 focus-visible:ring-[#549dff]",
                    isMobile ? "h-10 pl-10 text-base rounded-xl" : "h-8 pl-8 text-xs rounded-lg"
                  )}
                />
              </div>
            </div>

            {/* Session list */}
            <div className="flex-1 overflow-y-auto min-h-0">
              <div className={cn(isMobile ? "space-y-0.5 px-2 pb-24" : "space-y-0.5 px-2")}>
                {filteredSessions.map((s) => {
                  const channel = channelOf(s.key);
                  const displayLabel = sessionDisplayLabel(s.key, s.last_message, t("chat.newChat"));
                  const maxLen = isMobile ? 28 : 20;
                  const label = displayLabel.length > maxLen ? displayLabel.slice(0, maxLen) + "…" : displayLabel;
                  const active = s.key === currentSessionKey;
                  const sessionBusy = sessionStates[s.key]?.isWaiting ?? false;
                  return (
                    <div
                      key={s.key}
                      className={cn(
                        "group relative flex cursor-pointer items-center gap-3 rounded-xl transition-colors",
                        isMobile ? "px-3 py-3" : "px-3 py-2",
                        active
                          ? "brand-hover-border bg-white text-[#0d5d57]"
                          : "hover:bg-[#e8f0f0]"
                      )}
                      onClick={() => switchSession(s.key)}
                    >
                      <div className={cn(
                        "flex shrink-0 items-center justify-center rounded-full leading-none",
                        isMobile ? "h-10 w-10 text-lg" : "h-8 w-8 text-sm",
                        active ? "bg-[#dcecec]" : "bg-white/80"
                      )}>
                        {CHANNEL_ICONS[channel] ?? "💬"}
                      </div>
                      <div className="min-w-0 flex-1 overflow-hidden">
                        <div className="flex items-baseline justify-between gap-1">
                          <span className={cn(
                            "truncate font-medium leading-snug",
                            isMobile ? "text-sm" : "text-xs"
                          )}>
                            {label}
                          </span>
                          <span className={cn(
                            "shrink-0 text-[10px] leading-snug",
                            active ? "text-[#298c88]" : "text-muted-foreground/70"
                          )}>
                            {formatDate(s.updated_at)}
                          </span>
                        </div>
                        <p className={cn(
                          "mt-0.5 truncate leading-snug",
                          isMobile ? "text-xs" : "text-[10px]",
                          active ? "text-[#0d5d57]" : "text-muted-foreground"
                        )}>
                          {sessionBusy ? (
                            <span className="inline-flex items-center gap-1">
                              <span className="flex gap-0.5">
                                <span className="h-1 w-1 rounded-full bg-primary animate-bounce [animation-delay:0ms]" />
                                <span className="h-1 w-1 rounded-full bg-primary animate-bounce [animation-delay:150ms]" />
                                <span className="h-1 w-1 rounded-full bg-primary animate-bounce [animation-delay:300ms]" />
                              </span>
                              <span className="text-primary/70">Processing…</span>
                            </span>
                          ) : (s.last_message || "—")}
                        </p>
                      </div>
                      <Button
                        size="icon"
                        variant="ghost"
                        className={cn(
                          "shrink-0 transition-opacity",
                          isMobile
                            ? cn("h-8 w-8 opacity-0 active:opacity-100", active && "opacity-100 text-[#298c88] hover:bg-[#e8f0f0]")
                            : cn("h-6 w-6 opacity-0 group-hover:opacity-100", active && "opacity-100 text-[#298c88] hover:bg-[#e8f0f0]")
                        )}
                        onClick={(e) => {
                          e.stopPropagation();
                          if (active) {
                            const idx = displaySessions.findIndex((x) => x.key === s.key);
                            const next = displaySessions[idx + 1] ?? displaySessions[idx - 1];
                            if (next) switchSession(next.key); else newChat();
                          }
                          deleteSession.mutate(s.key);
                        }}
                      >
                        <Trash2 className={cn(isMobile ? "h-4 w-4" : "h-3 w-3")} />
                      </Button>
                    </div>
                  );
                })}
                {filteredSessions.length === 0 && (
                  <div className={cn(
                    "flex flex-col items-center justify-center text-muted-foreground",
                    isMobile ? "py-16 gap-2" : "py-8 gap-1"
                  )}>
                    <MessageSquare className={cn(isMobile ? "h-10 w-10 opacity-20" : "h-8 w-8 opacity-20")} />
                    <p className={cn(isMobile ? "text-sm" : "text-xs")}>{t("common.noData")}</p>
                  </div>
                )}
              </div>
            </div>
          </>
        )}

        {activeModule === "wave-record" && (
          <WaveRecordJobList
            selectedJobId={selectedWaveJob?.id ?? null}
            onSelect={setSelectedWaveJob}
          />
        )}

        {activeModule === "setting-check" && (
          <SettingCheckJobList
            selectedJobId={selectedSettingJob?.id ?? null}
            onSelect={setSelectedSettingJob}
          />
        )}

        {/* FAB — mobile only */}
        {isMobile && activeModule === "chat" && (
          <button
            onClick={newChat}
            title={t("chat.newChat")}
            className="fixed bottom-20 right-5 z-30 flex h-14 w-14 items-center justify-center rounded-full text-white shadow-lg transition-transform active:scale-95"
            style={{ background: "linear-gradient(135deg, #0dccff 0%, #4760ff 56%, #f760ff 100%)", boxShadow: "0 10px 24px rgba(71,96,255,0.28)" }}
          >
            <Plus className="h-6 w-6" />
          </button>
        )}
      </aside>

      {/* C Panel - Content Area */}
      <div
        className={cn(
          "flex flex-col overflow-hidden",
          isMobile
            ? cn("w-full flex-1 min-h-0", !mobileShowChat && "hidden")
            : "flex-1 rounded-[28px] brand-panel"
        )}
        style={isMobile ? undefined : { boxShadow: "var(--shadow-card)" }}
      >
        {/* Mobile back button header */}
        {isMobile && (
          <div className="flex h-12 shrink-0 items-center gap-2 px-3">
            <Button
              size="icon"
              variant="ghost"
              className="h-9 w-9"
              onClick={() => setMobileShowChat(false)}
            >
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <span className="flex-1 truncate text-sm font-medium">
              {activeModule === "chat"
                ? (currentSessionKey ? sessionDisplayLabel(currentSessionKey, undefined, t("chat.newChat")) : t("nav.chat"))
                : bPanelTitle
              }
            </span>
          </div>
        )}

        {/* Content */}
        <div className="flex flex-col flex-1 overflow-hidden">
          {activeModule === "chat" && (
            <ChatWindow urlSessionKey={urlSessionKey} isLoading={!!currentSessionKey && !historyLoaded} />
          )}
          {activeModule === "wave-record" && <WaveRecordWorkspace selectedJob={selectedWaveJob} />}
          {activeModule === "setting-check" && <SettingCheckWorkspace selectedJob={selectedSettingJob} />}
        </div>
      </div>
    </div>
  );
}
