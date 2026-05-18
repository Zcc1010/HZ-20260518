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
  private url: string;
  private sessionKey: string | null = null;

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

    const query = new URLSearchParams();
    if (token) {
      query.set("token", token);
    }
    if (this.sessionKey) {
      query.set("session", this.sessionKey);
    }
    const wsUrl = query.size > 0 ? `${this.url}?${query.toString()}` : this.url;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
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
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
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
    this.ws?.close();
    this.ws = null;
  }

  get isConnected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
