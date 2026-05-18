## Why

`WEBUI_AUTH_DISABLED=true` solves login friction, but the current frontend still renders the full admin shell. For this deployment, authless mode is intended to behave like a focused internal chat console, not a system-admin workbench.

## What Changes

- Add an authless-only frontend shell mode that routes directly into `/chat`.
- Hide dashboard, settings, and all admin navigation when authless mode is enabled on both desktop and mobile.
- Keep the backend authless synthesized admin identity unchanged, and only narrow the UI surface in the frontend.
- Treat authless chat history like a normal user view so only the current session namespace is shown in the chat page.

## Capabilities

### New Capabilities
- `authless-chat-shell`: Present authless deployments as a chat-only shell with conversation history and chat composer only.

### Modified Capabilities
- `authless-access`: Continue to allow tokenless access, but no longer expose the admin-facing frontend shell by default.

## Impact

- Affected frontend code: `web/src/App.tsx`, `web/src/pages/Chat.tsx`, `web/src/components/layout/Sidebar.tsx`, `web/src/components/layout/MobileBottomTabs.tsx`, and `web/src/components/layout/MobileTopBar.tsx`.
- No backend auth or role contract changes are required for this step.
- Deployment behavior is unchanged; only the authless UI surface is reduced.
