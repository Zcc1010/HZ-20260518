## Why

The current authless deployment only exposes a chat-focused shell under `/assistant/`. A new public-facing operational app area is needed for workflows like `G 文件对比`, but the existing chat UI must remain intact.

The first app requires a task table, modal file upload flow, skill-driven execution, and downloadable report history. Future apps are expected, but they may use different workspace shapes, so the new shell must separate app selection from app-specific workspaces.

## What Changes

- Add a second public entrypoint at `/agentplayground`.
- Restrict `/agentplayground` to authless/public mode and redirect to `/assistant/` otherwise.
- Add a dedicated playground shell with a left-side app list and a right-side welcome/workspace area.
- Add `G 文件对比` as the first registered app with a table workspace and create-job dialog.
- Store each app under `~/.nanobot/agentplayground/<app_id>/` with its own `app.db` and job directories.
- Process `G 文件对比` jobs through an app-level serial queue in the first version.

## Capabilities

### New Capabilities
- `agentplayground-shell`: present a public app playground at `/agentplayground`.
- `g-file-compare-workspace`: create, track, and download compare jobs for `G 文件对比`.

### Modified Capabilities
- `authless-access`: continue to allow tokenless public access, now with a second public shell dedicated to apps.

## Impact

- Affected frontend areas: routing, new playground page/components, app registry, `G 文件对比` workspace UI.
- Affected backend areas: new routes, SQLite persistence, compare job service, authless route gating.
- `/assistant/` stays unchanged by design.
