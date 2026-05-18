# Chat Streaming and LaTeX Rendering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add real streaming assistant rendering in the WebUI chat and enable Markdown LaTeX formula rendering.

**Architecture:** Introduce explicit websocket streaming events for assistant text so the frontend can create one streaming assistant bubble and append deltas into it. Keep tool hints as separate messages. Extend the markdown pipeline with math plugins and KaTeX styling while preserving existing GFM and code highlighting behavior.

**Tech Stack:** Python, FastAPI WebSocket, React, Zustand, TypeScript, react-markdown, remark-math, rehype-katex, Vite

---

### Task 1: Define Streaming Event Types

**Files:**
- Modify: `web/src/lib/ws.ts`
- Modify: `webui/api/models.py` if shared websocket payload models are used there

**Step 1: Add failing type-level expectations for new websocket event kinds if a frontend test harness exists**

If no frontend test harness exists, use the smallest possible compile-time change and verify through `npm run build`.

**Step 2: Extend websocket message types**

Add:

- `stream_start`
- `stream_delta`
- `stream_end`

**Step 3: Run frontend build to verify types still compile**

Run: `cd web && npm run build`

### Task 2: Emit Explicit Streaming Events From WebSocket Backend

**Files:**
- Modify: `webui/api/routes/ws.py`
- Test: `tests/test_websocket_streaming.py`

**Step 1: Write a failing backend test for assistant streaming events**

Cover:

- streaming text produces `stream_start`
- subsequent deltas produce `stream_delta`
- completion produces `stream_end`
- tool hints still do not enter the text delta path

**Step 2: Run the focused test and confirm it fails**

Run: `pytest -q tests/test_websocket_streaming.py`

**Step 3: Update the websocket route to send explicit streaming events**

Requirements:

- assistant正文增量和工具提示分离
- session key always preserved
- existing `done` event remains for final reconciliation

**Step 4: Run the focused test and confirm it passes**

Run: `pytest -q tests/test_websocket_streaming.py`

### Task 3: Make the Frontend Render One Streaming Assistant Bubble

**Files:**
- Modify: `web/src/components/chat/ChatWindow.tsx`
- Modify: `web/src/stores/chatStore.ts`

**Step 1: Implement a single streaming assistant lifecycle**

Rules:

- `stream_start` creates one assistant message with `isStreaming=true`
- `stream_delta` appends to that same message
- `stream_end` clears the streaming state

**Step 2: Update `done` handling to avoid duplicate assistant text**

If a streaming assistant bubble already exists, `done` should not append the same content again.

**Step 3: Keep tool hints as separate tool messages**

**Step 4: Run frontend build to confirm it compiles**

Run: `cd web && npm run build`

### Task 4: Add Backend Regression Coverage for Streaming Semantics

**Files:**
- Create: `tests/test_websocket_streaming.py`

**Step 1: Cover text-only streaming**

**Step 2: Cover text plus tool hints interleaving**

**Step 3: Cover fallback behavior when no streaming events are emitted**

**Step 4: Run the focused test file**

Run: `pytest -q tests/test_websocket_streaming.py`

### Task 5: Add Math Rendering Dependencies

**Files:**
- Modify: `web/package.json`

**Step 1: Add required dependencies**

Add:

- `remark-math`
- `rehype-katex`
- `katex`

**Step 2: Install/update lockfile**

Use the repo’s current package manager in `web/`.

**Step 3: Verify dependency install is reflected in the lockfile**

### Task 6: Enable LaTeX in Markdown Rendering

**Files:**
- Modify: `web/src/components/chat/MessageBubble.tsx`
- Modify: `web/src/main.tsx` or `web/src/index.css`

**Step 1: Add a failing formula-rendering check if a frontend test harness exists**

If no harness exists, verify by build plus manual browser check.

**Step 2: Wire `remark-math` and `rehype-katex` into `ReactMarkdown`**

**Step 3: Import KaTeX CSS**

**Step 4: Ensure existing GFM and syntax highlighting still work**

**Step 5: Run frontend build**

Run: `cd web && npm run build`

### Task 7: Light Visual Polish For Streaming and Math

**Files:**
- Modify: `web/src/components/chat/MessageBubble.tsx`
- Modify: `web/src/index.css` if needed

**Step 1: Keep the streaming cursor visually subtle and stable**

**Step 2: Ensure KaTeX blocks do not break message width or spacing**

**Step 3: Preserve current brand style**

Do not redesign the whole chat surface.

### Task 8: End-to-End Verification

**Files:**
- Test: `tests/test_websocket_streaming.py`

**Step 1: Run backend tests**

Run: `pytest -q tests/test_websocket_streaming.py tests/test_token_estimation_patch.py`

**Step 2: Run frontend build**

Run: `cd web && npm run build`

**Step 3: Run Python syntax verification**

Run: `python -m py_compile webui/api/routes/ws.py`

**Step 4: Manual verification**

Scenarios:

- normal assistant reply streams as one bubble
- tool call emits separate tool hint bubble
- `$x^2$` renders inline
- `$$\\int_0^1 x dx$$` renders as a block
- file attachment cards still render and download

**Step 5: Commit**

```bash
git add webui/api/routes/ws.py web/src/lib/ws.ts web/src/stores/chatStore.ts web/src/components/chat/ChatWindow.tsx web/src/components/chat/MessageBubble.tsx web/src/main.tsx web/src/index.css web/package.json web/package-lock.json tests/test_websocket_streaming.py docs/plans/2026-04-14-chat-streaming-latex-design.md docs/plans/2026-04-14-chat-streaming-latex.md
git commit -m "feat: add chat streaming and LaTeX rendering"
```
