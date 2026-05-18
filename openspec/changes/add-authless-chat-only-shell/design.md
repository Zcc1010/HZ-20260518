## Context

The current authless implementation deliberately synthesizes a stable local admin identity in the backend so existing REST and WebSocket flows remain usable without rewriting permission checks. That backend choice is still sound. The problem is the frontend treats authless mode as a full admin session, which exposes dashboard, settings, tools, user management, and other controls that are not needed in the target deployment.

The requested behavior is narrower: when login is disabled, the UI should look like a normal user-facing chat surface. Only conversation history and the active chat view should remain visible. This must hold for both desktop and mobile.

## Goals / Non-Goals

**Goals:**
- Make authless mode enter `/chat` by default.
- Hide dashboard, settings, and all admin navigation in authless mode.
- Preserve conversation history and the active chat experience.
- Keep the backend authless identity unchanged to avoid destabilizing API and WebSocket integrations.

**Non-Goals:**
- Rework backend authless mode to synthesize a non-admin role.
- Add a new permission model or extra backend role checks.
- Redesign the authenticated admin experience.

## Decisions

### 1. Keep authless admin identity in the backend and introduce a frontend-only restricted view

Authless mode will continue to bootstrap with the synthesized backend admin user. The frontend will derive a separate "authless restricted shell" behavior from `authlessEnabled` instead of from `user.role`.

Why:
- It avoids touching stable backend authless integration paths.
- It keeps the scope limited to UI and routing.
- It is reversible without changing session ownership or API behavior.

### 2. Route authless mode directly to `/chat`

The default route, `/login`, and route fallbacks should all land on `/chat` when authless mode is enabled. Admin-only or dashboard pages should redirect back to `/chat`.

Why:
- It matches the intended entry point: chat first, not dashboard first.
- It eliminates dead-end or confusing navigation when most pages are hidden.

### 3. Treat authless chat list like a normal user view

The chat page currently uses `user.role === "admin"` to decide whether all sessions are visible. In authless mode, that check should be narrowed so chat history follows the current user's own `web:<user_id>:` namespace instead of showing all sessions.

Why:
- It matches the user-facing expectation of a normal chat console.
- It avoids exposing extra session records just because the backend identity is admin.

### 4. Reduce mobile and desktop chrome separately

Desktop sidebar should keep only chat navigation and minimal branding. Mobile bottom tabs should only keep the chat tab in authless mode, and the mobile top bar should drop the avatar/settings controls that imply account management.

Why:
- The mobile shell has a different control surface than desktop.
- Hiding only desktop navigation would still leave settings access on mobile.

## Risks / Trade-offs

- [Frontend-only restriction is not a security boundary] → Mitigation: document clearly that this is a UI narrowing step only; backend authless mode still maps to a local admin identity.
- [Hard redirects can surprise existing deep links] → Mitigation: only apply the redirect narrowing when `authlessEnabled` is true.
- [Chat history filtering may hide existing admin-created sessions] → Mitigation: authless mode keeps using the stable `local-admin` user id, so its own `web:local-admin:*` sessions remain visible.

## Migration Plan

1. Add a new openspec change for the authless chat-only shell behavior.
2. Update route guards and route defaults for authless mode.
3. Narrow desktop and mobile navigation in authless mode.
4. Narrow chat session filtering in authless mode.
5. Run a frontend production build to confirm route and asset changes still compile.
