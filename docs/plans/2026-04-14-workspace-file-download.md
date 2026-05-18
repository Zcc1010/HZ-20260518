# Workspace File Download Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let the WebUI deliver workspace-generated files as downloadable attachments using anonymous long-lived token links.

**Architecture:** Extend the existing `message(..., media=[...])` web capture path so assistant messages can carry structured attachments. Persist attachment metadata in session history, expose files through a new tokenized download route, and render attachments in the chat UI as file cards with download actions.

**Tech Stack:** Python, FastAPI, WebSocket, session JSONL persistence, React, Zustand, TypeScript, pytest

---

### Task 1: Define Attachment Metadata and Download Token Helpers

**Files:**
- Create: `webui/api/files.py`
- Test: `tests/test_file_downloads.py`

**Step 1: Write a failing test for generating attachment metadata from a workspace file**

Cover:

- normal workspace file
- missing file
- file outside workspace

**Step 2: Run the focused test to confirm it fails**

Run: `pytest -q tests/test_file_downloads.py -k metadata`

**Step 3: Implement a helper that validates a path is inside workspace and returns attachment metadata**

Fields:

- `id`
- `name`
- `mime_type`
- `size`
- `token`
- `download_url`

**Step 4: Run the focused test and confirm it passes**

Run: `pytest -q tests/test_file_downloads.py -k metadata`

### Task 2: Add Anonymous Token Download Route

**Files:**
- Create: `webui/api/routes/files.py`
- Modify: `webui/api/server.py`
- Test: `tests/test_file_downloads.py`

**Step 1: Write a failing route test for `GET /api/files/d/{token}`**

Cover:

- valid token returns file
- unknown token returns `404`
- token pointing outside workspace returns `403` or `404` per final implementation choice

**Step 2: Run the focused route test to confirm it fails**

Run: `pytest -q tests/test_file_downloads.py -k download`

**Step 3: Implement the download route and register the router**

Requirements:

- no login required
- token is the only access credential
- response uses attachment download headers

**Step 4: Run the focused route test and confirm it passes**

Run: `pytest -q tests/test_file_downloads.py -k download`

### Task 3: Extend WebSocket Capture to Preserve `media`

**Files:**
- Modify: `webui/api/routes/ws.py`
- Modify: `webui/api/gateway.py`
- Test: `tests/test_websocket_attachments.py`

**Step 1: Write a failing test for web-channel capture preserving both text and media**

Cover:

- `message(content="...", media=[...])` reaches the websocket path
- captured payload includes attachment metadata

**Step 2: Run the focused test to confirm it fails**

Run: `pytest -q tests/test_websocket_attachments.py`

**Step 3: Change the in-memory web capture queue from plain text to structured payloads**

Requirements:

- preserve `content`
- preserve `media`
- convert valid workspace media paths into attachment metadata

**Step 4: Make the final `done` websocket frame include `attachments`**

**Step 5: Run the focused test and confirm it passes**

Run: `pytest -q tests/test_websocket_attachments.py`

### Task 4: Persist Attachment Metadata in Session History

**Files:**
- Modify: `webui/api/routes/ws.py`
- Modify: `web/src/pages/Chat.tsx`
- Test: `tests/test_websocket_attachments.py`

**Step 1: Write a failing test for assistant session messages retaining `attachments`**

Cover:

- attachment-bearing assistant messages are saved
- session reload can reconstruct them

**Step 2: Run the focused test to confirm it fails**

Run: `pytest -q tests/test_websocket_attachments.py -k persist`

**Step 3: Update backend message persistence to include `attachments` on assistant messages**

**Step 4: Update frontend history hydration to map `attachments` from server messages into `ChatMessage`**

**Step 5: Run the focused test and confirm it passes**

Run: `pytest -q tests/test_websocket_attachments.py -k persist`

### Task 5: Extend Frontend Message Models

**Files:**
- Modify: `web/src/lib/ws.ts`
- Modify: `web/src/stores/chatStore.ts`
- Modify: `web/src/components/chat/ChatWindow.tsx`
- Test: `web` unit test file if the repo already has a frontend test setup; otherwise verify manually

**Step 1: Add shared attachment types to WebSocket messages and chat store messages**

Fields:

- `id`
- `name`
- `mime_type`
- `size`
- `download_url`

**Step 2: Update websocket `done` handling to preserve attachments when adding assistant messages**

**Step 3: Update any history-load path that converts server messages into store messages**

**Step 4: Verify TypeScript compiles**

Run: `npm run build` or the repo’s existing frontend build command

### Task 6: Render Downloadable File Cards

**Files:**
- Modify: `web/src/components/chat/MessageBubble.tsx`

**Step 1: Add a small attachment card component for assistant messages**

Display:

- file name
- human-readable size
- download button or direct anchor

**Step 2: Render attachments below assistant message content**

**Step 3: Keep the first version simple**

Do not add:

- inline previews
- drag sorting
- upload-state reuse

**Step 4: Verify manually in the browser**

Manual checks:

- file card appears after agent sends a file
- clicking it downloads the file
- multiple attachments render correctly

### Task 7: Tighten Prompt and Runtime Expectations

**Files:**
- Modify: `webui/patches/prompt.py`

**Step 1: Review the existing prompt text about `message(..., media=[...])`**

**Step 2: Add one short clarification that WebUI users will receive downloadable links/cards for workspace files**

**Step 3: Keep the prompt change minimal**

Do not change unrelated runtime rules.

### Task 8: End-to-End Verification

**Files:**
- Test: `tests/test_file_downloads.py`
- Test: `tests/test_websocket_attachments.py`

**Step 1: Run backend tests**

Run: `pytest -q tests/test_file_downloads.py tests/test_websocket_attachments.py tests/test_token_estimation_patch.py`

**Step 2: Run Python syntax verification**

Run: `python -m py_compile webui/api/routes/files.py webui/api/routes/ws.py webui/api/files.py`

**Step 3: Run compose config verification**

Run: `docker compose -f deployment/release/docker-compose.yml config`

**Step 4: Do one manual browser verification**

Scenario:

- ask agent to generate a workspace file
- ensure WebUI shows file card
- click download
- refresh page and confirm historical message still downloads

**Step 5: Commit**

```bash
git add webui/api/files.py webui/api/routes/files.py webui/api/server.py webui/api/routes/ws.py webui/patches/prompt.py web/src/lib/ws.ts web/src/stores/chatStore.ts web/src/components/chat/ChatWindow.tsx web/src/components/chat/MessageBubble.tsx web/src/pages/Chat.tsx tests/test_file_downloads.py tests/test_websocket_attachments.py docs/plans/2026-04-14-workspace-file-download-design.md docs/plans/2026-04-14-workspace-file-download.md
git commit -m "feat: add workspace file download delivery"
```
