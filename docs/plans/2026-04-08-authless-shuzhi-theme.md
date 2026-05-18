# Authless Shuzhi Theme Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a runtime-switchable authless mode and rebrand the frontend shell to the approved 数智小徽 style without breaking the existing authenticated mode.

**Architecture:** The backend keeps its current auth system but gains a small authless bypass that returns a synthesized local admin identity for REST and WebSocket flows. The frontend keeps the existing route tree and state model, but adds an authless bootstrap path and replaces shared branding/theme assets so the shell presents as 数智小徽.

**Tech Stack:** Python, FastAPI, React 18, TypeScript, Vite, Zustand, Tailwind CSS, OpenSpec

---

### Task 1: Authless backend scaffolding

**Files:**
- Modify: `webui/api/deps.py`
- Modify: `webui/api/routes/auth.py`
- Modify: `webui/api/routes/ws.py`
- Create or modify: `webui/utils/webui_config.py`

**Step 1: Add authless-mode helpers**

Create a single backend helper that answers:
- whether authless mode is enabled
- what synthesized local admin user record should be returned

**Step 2: Thread authless mode through REST auth**

Update request dependencies so bearer-token validation is bypassed only when authless mode is enabled. Keep the existing JWT flow unchanged when the mode is off.

**Step 3: Thread authless mode through WebSocket auth**

Update `/ws/chat` authentication so tokenless websocket sessions are accepted only in authless mode and map to the synthesized local admin identity.

**Step 4: Run targeted sanity checks**

Check Python imports and obvious syntax regressions in the touched backend files.

### Task 2: Frontend authless bootstrap

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/stores/authStore.ts`
- Modify: `web/src/lib/api.ts`
- Modify: `web/src/lib/ws.ts`
- Modify: `web/src/main.tsx` if needed for bootstrapping

**Step 1: Add authless frontend state**

Allow the auth store to represent the synthesized local admin user when authless mode is enabled.

**Step 2: Update route guards**

Make `PrivateRoute`, `AdminRoute`, and `/login` routing bypass login when authless mode is active.

**Step 3: Keep request plumbing compatible**

Ensure the REST client and WebSocket client continue to send tokens when present, but do not break when authless mode leaves them absent.

**Step 4: Run a focused frontend type/build check later with the branding changes**

Do not run partial build verification until static assets and route changes are all in place.

### Task 3: 数智小徽 branding assets and shell tokens

**Files:**
- Modify: `web/index.html`
- Modify: `web/src/index.css`
- Modify: `web/tailwind.config.ts`
- Modify: `web/src/theme/ThemeProvider.tsx` if default theme behavior needs alignment
- Add or replace files under: `web/public/`

**Step 1: Copy approved static assets**

Bring in the selected PNG assets and `syhtjzt.otf` font into the frontend public bundle.

**Step 2: Replace shell branding**

Update browser title, mobile app title, favicon/app icon references, and shared branding strings from Nanobot to 数智小徽.

**Step 3: Replace core theme tokens**

Switch the shared palette, shadows, and typography foundations to the 数智小徽 design language so untouched pages inherit the new shell style.

### Task 4: High-exposure UI surfaces

**Files:**
- Modify: `web/src/components/layout/Sidebar.tsx`
- Modify: `web/src/components/layout/AppLayout.tsx`
- Modify: `web/src/pages/Chat.tsx`
- Modify: `web/src/components/chat/ChatWindow.tsx`
- Modify: `web/src/pages/Login.tsx` only if needed to avoid stale branding on fallback routes

**Step 1: Restyle sidebar and shell chrome**

Apply the approved brand logo treatment, navigation visuals, and light-blue shell presentation.

**Step 2: Restyle chat empty state and session shell**

Use the reference robot/background direction and branded typography on the chat landing state and session list chrome.

**Step 3: De-prioritize login page**

Keep it from being the default entry. Only update its branding if it remains reachable as a fallback route.

### Task 5: Verification and task completion

**Files:**
- Modify: `openspec/changes/add-authless-mode-and-shuzhi-theme/tasks.md`

**Step 1: Run the frontend build**

Run the project frontend build and fix any type, asset, or bundling errors.

**Step 2: Run targeted backend validation**

Run lightweight Python validation for the auth-related modules changed in this session.

**Step 3: Mark completed OpenSpec tasks**

Update the relevant checkboxes in `tasks.md` as the work lands.
