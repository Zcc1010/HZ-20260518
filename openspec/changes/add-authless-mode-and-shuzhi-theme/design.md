## Context

`nanobot-webui` is a React/Vite frontend served by a FastAPI backend that directly embeds `nanobot-ai` runtime objects in-process. Authentication is currently mandatory for both REST requests and `/ws/chat`, and the frontend shell assumes a login-first flow. The requested deployment is an internal branded console where login is unnecessary, but the existing auth system must remain recoverable because other deployments may still need it.

The visual refresh is also cross-cutting. The current theme tokens, public icons, login page, sidebar, and chat empty state are Nanobot-branded and orange-led. The reference "数智小徽" design instead uses light blue shells, blue-purple gradient emphasis, branded PNG assets, and a custom title font for selected headings.

## Goals / Non-Goals

**Goals:**
- Add a runtime-switchable authless mode that makes REST and WebSocket usage work without interactive login.
- Keep the existing authenticated behavior intact when authless mode is disabled.
- Rebrand the browser shell and key UI surfaces to 数智小徽 with updated static assets.
- Focus visual work on the highest-value surfaces: shell metadata, sidebar, chat empty/welcome experience, session list styling, and shared theme tokens.

**Non-Goals:**
- Rebuild every admin page to match Open WebUI one-for-one.
- Remove the auth implementation from the codebase.
- Change nanobot runtime behavior, session model, or channel integrations beyond what authless access needs.
- Introduce a new multi-user permission model for anonymous usage.

## Decisions

### 1. Use a backend runtime flag instead of deleting auth

Add a small runtime config helper that resolves whether authless mode is enabled, preferably from environment to match Docker usage. Auth dependencies and WebSocket auth will branch on this flag and return a synthesized local admin identity when auth is disabled.

Why this approach:
- It keeps the existing auth code path available.
- It minimizes the number of call sites that need to change.
- It matches the deployment goal: internal toggle, not a product-wide auth redesign.

Alternative considered:
- Hard-delete login and JWT verification. Rejected because it would make recovery to authenticated mode expensive and risky.

### 2. Use a synthesized admin identity for authless sessions

In authless mode, backend dependencies should provide a stable pseudo-user record such as `id="local-admin"` / `username="数智小徽"` / `role="admin"`. WebSocket chat should reuse the same identity so session keys remain consistent.

Why this approach:
- Existing route handlers already depend on `current_user`.
- Frontend admin-gated routes can stay enabled without a second permission branch.
- Chat session ownership remains deterministic.

Alternative considered:
- Making every endpoint fully unauthenticated and removing role checks. Rejected because it creates more branching and duplicates logic.

### 3. Keep authless awareness in frontend bootstrap and route guards

Frontend auth state should gain an authless bootstrap path so route guards can treat authless mode as already authenticated. `/login` should redirect away in authless mode rather than being the primary entry page.

Why this approach:
- It avoids user-visible login dead ends.
- It lets the existing page tree stay mostly intact.
- It keeps the change localized to bootstrap, store, and guards.

Alternative considered:
- Keeping login page mounted and faking a token only after visiting it. Rejected because the requested behavior is "不要登录页面".

### 4. Recreate the reference style as an equivalent React implementation

Do not attempt a literal port from Open WebUI's Svelte structure. Instead, map the reference branding into this app's React/Tailwind architecture: theme tokens in `index.css`, token mapping in `tailwind.config.ts`, PNG/font assets in `web/public`, and targeted updates to sidebar/chat/high-visibility surfaces.

Why this approach:
- The component trees differ substantially.
- Equivalent visual output is enough; structural parity is not necessary.
- It reduces churn in working business pages.

Alternative considered:
- Broad page-by-page redesign to mimic Open WebUI layout exactly. Rejected because it expands scope and risk without improving the requested deployment goal.

### 5. Prioritize shipped public assets over dynamic asset loading

Bundle the 数智小徽 assets into `web/public` so the existing frontend build and Python static serving path keep working without extra backend file routing.

Why this approach:
- It matches the current Vite/public asset flow.
- It avoids changes in FastAPI static mounting behavior.
- It keeps Docker/package builds straightforward.

## Risks / Trade-offs

- [Anonymous admin mode increases exposure] → Mitigation: implement it behind an explicit runtime flag and document that it is only suitable for local or internal deployments.
- [REST and WebSocket auth may diverge] → Mitigation: use one shared backend helper for authless-mode detection and one synthesized identity source.
- [Brand port may feel incomplete on lower-priority pages] → Mitigation: focus on shell-level tokens and high-exposure components so untouched pages still inherit the new palette.
- [Static asset replacement can break icons/PWA metadata] → Mitigation: update browser metadata and shipped public assets together, then run a production build check.
- [Existing persisted auth state can conflict with authless bootstrap] → Mitigation: make frontend bootstrap authoritative when authless mode is enabled and avoid depending on an old token.

## Migration Plan

1. Add authless runtime config and backend/user-context branching.
2. Update frontend auth bootstrap and route guards so authless mode bypasses login.
3. Replace public branding assets and shell metadata.
4. Apply theme-token and layout/chat branding updates.
5. Run frontend build validation and smoke-check that the main shell no longer routes through login.

Rollback:
- Disable the authless runtime flag to restore the existing authenticated flow.
- Revert the theme/static asset changes independently if branding needs to be rolled back without touching auth behavior.

## Open Questions

- None for implementation. The approved scope is internal authless deployment plus 数智小徽 branding, with login removed from the default flow.
