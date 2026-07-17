import { useAuthStore } from "../stores/authStore";
import { withBasePath } from "./basePath";

export type WsMessageType =
  | "session_info"
  | "progress"
  | "stream_start"
  | "stream_delta"
  | "stream_end"
  | "subagent_progress"
  | "done"
  | "error"
  | "revoke_ok";

export interface AttachmentInfo {
  id: string;
  name: string;
  mime_type: string;
  size: number;
  download_url: string;
}

export interface WsMessage {
  type: WsMessageType;
  content?: string;
  session_key?: string;
  tool_hint?: boolean;
  resuming?: boolean;
  index?: number;
  attachments?: AttachmentInfo[];
}

type MessageHandler = (msg: WsMessage) => void;
type StatusHandler = (connected: boolean) => void;

export class ChatWebSocket {
  private ws: WebSocket | null = null;
  private onMessage: MessageHandler;
  private onStatusChange: StatusHandler | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private shouldReconnect = false;
  private reconnectDelay = 3000;
  private readonly maxReconnectDelay = 30000;
  private url: string;
  private sessionKey: string | null = null;
  private boundOnVisibilityChange: (() => void) | null = null;

  constructor(onMessage: MessageHandler, onStatusChange?: StatusHandler) {
    this.onMessage = onMessage;
    this.onStatusChange = onStatusChange ?? null;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.host;
    this.url = `${proto}://${host}${withBasePath("/ws/chat")}`;
  }

  connect(sessionKey?: string) {
    const { token, authlessEnabled } = useAuthStore.getState();
    if (!token && !authlessEnabled) return;

    if (sessionKey) this.sessionKey = sessionKey;

    this.shouldReconnect = true;

    // 监听页面可见性变化，从后台切回时立即重连
    if (!this.boundOnVisibilityChange) {
      this.boundOnVisibilityChange = () => {
        if (document.visibilityState === "visible" && this.shouldReconnect && !this.isConnected) {
          this._reconnectNow();
        }
      };
      document.addEventListener("visibilitychange", this.boundOnVisibilityChange);
    }

    const query = new URLSearchParams();
    if (token) {
      query.set("token", token);
    }
    if (this.sessionKey) {
      query.set("session", this.sessionKey);
    }
    const wsUrl = query.size > 0 ? `${this.url}?${query.toString()}` : this.url;

    try {
      this.ws = new WebSocket(wsUrl);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
      this.reconnectDelay = 3000; // 重置退避
      this.onStatusChange?.(true);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);
        this.onMessage(msg);
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = () => {
      this.onStatusChange?.(false);
      if (this.shouldReconnect) {
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, this.reconnectDelay);
    // 指数退避，最大 30 秒
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay);
  }

  private _reconnectNow() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectDelay = 3000;
    this.connect();
  }

  send(content: string, sessionKey?: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "message", content, session_key: sessionKey }));
    }
  }

  setSession(sessionKey: string) {
    this.sessionKey = sessionKey;
  }

  cancel(sessionKey?: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel", session_key: sessionKey }));
    }
  }

  /** Revoke (delete) a message by index in a session. */
  revoke(sessionKey: string, index: number) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "revoke", session_key: sessionKey, index }));
    }
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.boundOnVisibilityChange) {
      document.removeEventListener("visibilitychange", this.boundOnVisibilityChange);
      this.boundOnVisibilityChange = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  get isConnected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
