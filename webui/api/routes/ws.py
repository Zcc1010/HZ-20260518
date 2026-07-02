"""WebSocket /ws/chat endpoint."""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from webui.api.files import build_attachment_metadata, to_public_attachment

router = APIRouter()

# ---------------------------------------------------------------------------
# Web-channel message capture
#
# When the agent replies via the message() tool instead of returning text
# directly, process_direct() returns "".  The tool calls bus.publish_outbound
# which the channel dispatcher drops (no "web" channel handler exists).
#
# Fix: patch the MessageTool's send_callback once so that messages addressed
# to channel="web" are pushed into per-connection capture queues, letting each
# _run_agent coroutine collect them after process_direct returns.
# ---------------------------------------------------------------------------

# user_id → list[asyncio.Queue[dict[str, Any]]]: one queue per active WebSocket connection
_web_captures: dict[str, list[asyncio.Queue]] = {}
_message_tool_patched = False


class _StreamEventEmitter:
    def __init__(self, send_json: Any, session_key: str) -> None:
        self.send_json = send_json
        self.session_key = session_key
        self.started = False

    async def delta(self, content: str) -> None:
        if not content:
            return
        if not self.started:
            self.started = True
            await self.send_json({"type": "stream_start", "session_key": self.session_key})
        await self.send_json({
            "type": "stream_delta",
            "content": content,
            "session_key": self.session_key,
        })

    async def end(self, *, resuming: bool) -> None:
        if not self.started:
            return
        await self.send_json({
            "type": "stream_end",
            "session_key": self.session_key,
            "resuming": resuming,
        })
        self.started = False


def _friendly_error(response: str) -> str:
    """Replace raw LLM error payloads with user-friendly messages."""
    if not response:
        return response
    text = response.strip()
    # Detect known error patterns
    if "1305" in text and "访问量过大" in text:
        return "当前 AI 服务访问量过大，请稍后再试。"
    if "LLM returned error" in text:
        return "AI 服务暂时不可用，请稍后再试。"
    if text.startswith("Error:") and "rate" in text.lower():
        return "当前请求过于频繁，请稍后再试。"
    return response


def _ensure_message_tool_patched(container: Any) -> None:
    """One-time patch of the AgentLoop's MessageTool send_callback."""
    global _message_tool_patched
    if _message_tool_patched:
        return
    try:
        from nanobot.agent.tools.message import MessageTool
        msg_tool = container.agent.tools.get("message")
        if not isinstance(msg_tool, MessageTool):
            return
        original_callback = msg_tool._send_callback

        async def _patched_send(outbound_msg: Any) -> None:
            # Non-progress web messages → route to capture queues, skip the bus
            if (
                outbound_msg.channel == "web"
                and not (outbound_msg.metadata or {}).get("_progress")
            ):
                queues = _web_captures.get(str(outbound_msg.chat_id), [])
                payload = {
                    "content": outbound_msg.content or "",
                    "media": list(getattr(outbound_msg, "media", None) or []),
                }
                for q in queues:
                    await q.put(payload)
                return  # consumed by WebSocket — don't push to shared bus
            if original_callback:
                await original_callback(outbound_msg)

        msg_tool.set_send_callback(_patched_send)
        _message_tool_patched = True
        logger.debug("MessageTool patched for web-channel capture")
    except Exception as exc:
        logger.warning("Could not patch MessageTool: {}", exc)


def _workspace_root(container: Any) -> Any:
    workspace = getattr(getattr(container, "config", None), "workspace_path", None)
    if workspace is not None:
        return workspace
    return container.config.agents.defaults.workspace


def _attachments_from_media(container: Any, media: list[str] | None) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    if not media:
        return attachments
    workspace = _workspace_root(container)
    for media_path in media:
        try:
            attachments.append(build_attachment_metadata(workspace, media_path))
        except (FileNotFoundError, PermissionError) as exc:
            logger.warning("Skipping invalid web attachment {}: {}", media_path, exc)
    return attachments


def _collect_captured_web_reply(container: Any, capture_q: asyncio.Queue) -> tuple[str, list[dict[str, Any]]]:
    contents: list[str] = []
    attachments: list[dict[str, Any]] = []
    while not capture_q.empty():
        try:
            payload = capture_q.get_nowait()
        except asyncio.QueueEmpty:
            break
        if isinstance(payload, str):
            payload = {"content": payload, "media": []}
        content = (payload or {}).get("content") or ""
        if content:
            contents.append(content)
        attachments.extend(_attachments_from_media(container, (payload or {}).get("media")))
    return "\n\n".join(contents), attachments


def _supports_process_direct_streaming(process_direct: Any) -> bool:
    try:
        signature = inspect.signature(process_direct)
    except (TypeError, ValueError):
        return False
    return "on_stream" in signature.parameters and "on_stream_end" in signature.parameters


def _persist_attachments_to_session(container: Any, session_key: str, response: str, attachments: list[dict[str, Any]]) -> None:
    if not attachments:
        return
    try:
        from datetime import datetime

        session = container.agent.sessions.get_or_create(session_key)
        target_message = None
        for message in reversed(getattr(session, "messages", [])):
            if message.get("role") != "assistant":
                continue
            if response and message.get("content") != response:
                continue
            target_message = message
            break
        if target_message is None:
            target_message = {
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now().isoformat(),
            }
            session.messages.append(target_message)
        target_message["attachments"] = attachments
        session.updated_at = datetime.now()
        container.agent.sessions.save(session)
    except Exception as exc:
        logger.warning("Failed to persist web attachments for session {}: {}", session_key, exc)


async def _auth_websocket(websocket: WebSocket) -> dict | None:
    """Validate the JWT token sent as query param ``token=...``."""
    from webui.api.auth import get_authless_user, is_authless_mode

    if is_authless_mode():
        return get_authless_user()

    # bootstrap endpoint always returns auth_disabled=True, so also allow
    # connections without a token when no users exist in the store.
    token = websocket.query_params.get("token")
    if not token:
        # Try authless fallback — matches bootstrap endpoint behavior
        return get_authless_user()

    from webui.api.auth import decode_access_token
    from webui.api.users import UserStore
    import jwt

    user_store = websocket.app.state.user_store
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        # Token invalid but don't reject — fall back to authless user
        return get_authless_user()

    user = user_store.get_by_id(payload["sub"])
    if not user:
        return get_authless_user()

    return user


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket) -> None:
    """
    WebSocket chat endpoint.

    Query params:
      token=<jwt>              — required for authentication
      session=<session_key>    — optional; if omitted a new ``web:<uid>:<uuid>`` key is created

    Client → Server frames (JSON):
      {"type": "message", "content": "..."}
      {"type": "cancel"}
      {"type": "new_session"}

    Server → Client frames (JSON):
      {"type": "stream_start"}
      {"type": "stream_delta", "content": "..."}
      {"type": "stream_end", "resuming": bool}
      {"type": "session_info", "session_key": "web:..."}
      {"type": "progress",     "content": "...", "tool_hint": bool}
      {"type": "done",         "content": "..."}
      {"type": "error",        "content": "..."}
    """
    user = await _auth_websocket(websocket)
    if user is None:
        return

    await websocket.accept()
    container = websocket.app.state.services

    if container is None:
        await websocket.send_json({"type": "error", "content": "Services not initialised"})
        await websocket.close()
        return

    # Patch MessageTool once so web-channel replies are captured (not dropped)
    _ensure_message_tool_patched(container)

    is_admin = user.get("role") == "admin"

    def _is_allowed_session(key: str) -> bool:
        """Return True if the user is allowed to use this session key."""
        if key.startswith(f"web:{user['id']}"):
            return True
        # Admins can view/chat in any channel session (feishu/telegram/etc.)
        return is_admin

    # Determine or create session key
    requested_key: str | None = websocket.query_params.get("session")
    session_key = (
        requested_key
        if requested_key and _is_allowed_session(requested_key)
        else f"web:{user['id']}:{uuid.uuid4().hex[:8]}"
    )

    await websocket.send_json({"type": "session_info", "session_key": session_key})

    # Per-session task tracking: allows multiple sessions to run concurrently
    # through a single WebSocket connection.
    session_tasks: dict[str, asyncio.Task] = {}

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "cancel":
                # Cancel the task for a specific session, or the current session
                cancel_key = raw.get("session_key") or session_key
                task = session_tasks.get(cancel_key)
                if task and not task.done():
                    task.cancel()
                    await websocket.send_json({
                        "type": "error",
                        "content": "cancelled",
                        "session_key": cancel_key,
                    })

            elif msg_type == "new_session":
                session_key = f"web:{user['id']}:{uuid.uuid4().hex[:8]}"
                await websocket.send_json({"type": "session_info", "session_key": session_key})

            elif msg_type == "revoke":
                # Revoke (delete) a specific message by index from session history
                revoke_key = raw.get("session_key") or session_key
                msg_index = raw.get("index")
                if msg_index is not None and _is_allowed_session(revoke_key):
                    try:
                        session = container.agent.sessions.get_or_create(revoke_key)
                        idx = int(msg_index)
                        if 0 <= idx < len(session.messages):
                            removed = session.messages[idx]
                            # If revoking a user message, also remove the subsequent
                            # assistant/tool messages that form the response pair
                            if removed.get("role") == "user":
                                # Find extent: remove everything until the next user msg
                                end = idx + 1
                                while end < len(session.messages) and session.messages[end].get("role") != "user":
                                    end += 1
                                del session.messages[idx:end]
                            else:
                                del session.messages[idx]
                            from datetime import datetime
                            session.updated_at = datetime.now()
                            container.agent.sessions.save(session)
                            await websocket.send_json({
                                "type": "revoke_ok",
                                "session_key": revoke_key,
                                "index": msg_index,
                            })
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "content": "Invalid message index",
                                "session_key": revoke_key,
                            })
                    except Exception as exc:
                        await websocket.send_json({
                            "type": "error",
                            "content": f"Revoke failed: {exc}",
                            "session_key": revoke_key,
                        })

            elif msg_type == "message":
                content = raw.get("content", "")
                # Allow per-message session override so the client can switch sessions
                # without reconnecting the WebSocket (used by the "new chat" button).
                msg_session_key = raw.get("session_key")
                if msg_session_key and _is_allowed_session(msg_session_key):
                    if msg_session_key != session_key:
                        session_key = msg_session_key
                        await websocket.send_json({"type": "session_info", "session_key": session_key})
                if not content:
                    continue

                effective_key = msg_session_key or session_key

                # Check if this specific session already has an active task
                existing_task = session_tasks.get(effective_key)
                if existing_task and not existing_task.done():
                    await websocket.send_json({
                        "type": "error",
                        "content": "Previous message still processing in this session",
                        "session_key": effective_key,
                    })
                    continue

                async def _on_progress(text: str, *, tool_hint: bool = False, _sk: str = effective_key) -> None:
                    try:
                        await websocket.send_json({
                            "type": "progress",
                            "content": text,
                            "tool_hint": tool_hint,
                            "session_key": _sk,
                        })
                    except Exception:
                        pass

                async def _run_agent(msg: str, sess: str) -> None:
                    # Register a capture queue for this connection so that
                    # message() tool replies addressed to channel="web" are
                    # delivered here instead of being discarded by the dispatcher.
                    capture_q: asyncio.Queue = asyncio.Queue()
                    uid = str(user["id"])
                    _web_captures.setdefault(uid, []).append(capture_q)
                    # Register on_progress so SubAgent background tasks can push
                    # tool-call hints to this WebSocket connection.
                    # Uses "subagent_progress" type so frontend shows them as
                    # persistent tool bubbles (visible even after main agent done).
                    from webui.patches.subagent import register_progress, register_announce, register_save_turn
                    _subagent_chat_key = f"web:{uid}"

                    async def _on_subagent_progress(text: str, tool_hint: bool = True) -> None:
                        try:
                            await websocket.send_json({
                                "type": "subagent_progress",
                                "content": text,
                                "tool_hint": True,
                                "session_key": sess,
                            })
                        except Exception:
                            pass

                    async def _on_subagent_save_turn(all_messages: list) -> None:
                        """Persist SubAgent's full tool-call chain to the main session."""
                        try:
                            from datetime import datetime
                            _TRUNCATE = 500
                            session = container.agent.sessions.get_or_create(sess)
                            session.add_message("system", "[Background task progress]")
                            now = datetime.now().isoformat()
                            for m in all_messages[2:]:
                                role = m.get("role", "")
                                content = m.get("content") or ""
                                if role == "assistant" and m.get("tool_calls"):
                                    session.messages.append({
                                        "role": "sub_tool",
                                        "content": content,
                                        "tool_calls": m["tool_calls"],
                                        "timestamp": now,
                                    })
                                elif role == "tool":
                                    if isinstance(content, str) and len(content) > _TRUNCATE:
                                        content = content[:_TRUNCATE] + "\n... (truncated)"
                                    session.messages.append({
                                        "role": "sub_tool",
                                        "content": content,
                                        "tool_call_id": m.get("tool_call_id", ""),
                                        "name": m.get("name", ""),
                                        "timestamp": now,
                                    })
                                elif role == "assistant":
                                    if not content:
                                        continue
                                    session.messages.append({
                                        "role": "assistant",
                                        "content": content,
                                        "timestamp": now,
                                    })
                            session.updated_at = datetime.now()
                            container.agent.sessions.save(session)
                        except Exception:
                            pass

                    async def _on_subagent_done(text: str) -> None:
                        try:
                            await websocket.send_json({
                                "type": "done",
                                "content": text,
                                "session_key": sess,
                            })
                        except Exception:
                            pass

                    register_progress(_subagent_chat_key, _on_subagent_progress)
                    register_save_turn(_subagent_chat_key, _on_subagent_save_turn)
                    register_announce(_subagent_chat_key, _on_subagent_done)
                    stream_emitter = _StreamEventEmitter(websocket.send_json, sess)
                    try:
                        process_kwargs = {
                            "session_key": sess,
                            "channel": "web",
                            "chat_id": user["id"],
                            "on_progress": _on_progress,
                        }
                        if _supports_process_direct_streaming(container.agent.process_direct):
                            process_kwargs["on_stream"] = stream_emitter.delta
                            process_kwargs["on_stream_end"] = stream_emitter.end
                        result = await container.agent.process_direct(msg, **process_kwargs)
                        # nightly returns OutboundMessage; extract .content
                        response = getattr(result, "content", result) if result else ""
                        response = _friendly_error(response)
                        captured_content, attachments = _collect_captured_web_reply(container, capture_q)
                        if not response:
                            response = captured_content
                        _persist_attachments_to_session(container, sess, response or "", attachments)
                        await websocket.send_json({
                            "type": "done",
                            "content": response or "",
                            "attachments": [to_public_attachment(attachment) for attachment in attachments],
                            "session_key": sess,
                        })
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:
                        logger.error("WebSocket agent error: {}", exc)
                        try:
                            await websocket.send_json({
                                "type": "error",
                                "content": str(exc),
                                "session_key": sess,
                            })
                        except Exception:
                            pass
                    finally:
                        lst = _web_captures.get(uid, [])
                        if capture_q in lst:
                            lst.remove(capture_q)
                        if not lst:
                            _web_captures.pop(uid, None)
                        # Clean up finished task from tracking dict
                        session_tasks.pop(sess, None)

                task = asyncio.create_task(_run_agent(content, effective_key))
                session_tasks[effective_key] = task

    except WebSocketDisconnect:
        for task in session_tasks.values():
            if not task.done():
                task.cancel()
    except Exception as exc:
        logger.error("WebSocket error: {}", exc)
        try:
            await websocket.send_json({"type": "error", "content": str(exc)})
        except Exception:
            pass
