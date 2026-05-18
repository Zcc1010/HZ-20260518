## Why

This deployment is intended to run as a branded internal Web management console, not as a public multi-user product. The current nanobot-webui flow still assumes mandatory login and the default Nanobot orange brand, which adds friction for local/internal use and does not match the desired "数智小徽" presentation.

## What Changes

- Add a configurable authless mode that bypasses JWT login for both REST and WebSocket entry points while preserving the existing auth code path for deployments that still need login.
- Change the frontend shell, title, high-exposure pages, and static assets to a "数智小徽" visual system based on the supplied reference: government-light blue surfaces, blue-purple gradients, white translucent cards, and branded PNG assets.
- Remove login from the default user journey when authless mode is enabled by redirecting the app shell directly into the main interface.
- Replace the current Nanobot branding text, browser metadata, and bundled public icons with 数智小徽 branding.

## Capabilities

### New Capabilities
- `authless-access`: Allow internal deployments to run the WebUI without interactive login while keeping API and WebSocket access usable.
- `shuzhi-theme-shell`: Rebrand the frontend shell and shipped static assets to the 数智小徽 visual style.

### Modified Capabilities

## Impact

- Affected backend code: `webui/api/deps.py`, `webui/api/routes/auth.py`, `webui/api/routes/ws.py`, `webui/api/server.py`, `webui/api/users.py`, config helpers that surface runtime flags.
- Affected frontend code: `web/src/App.tsx`, auth state/bootstrap, layout/navigation/chat presentation, `web/index.html`, `web/src/index.css`, `web/tailwind.config.ts`, and bundled assets under `web/public/`.
- Affected deployment behavior: new runtime flag for authless mode, updated browser/PWA branding assets, and a no-login default path for the branded internal console.
