## Context

`/assistant/` already serves a public authless chat shell. The new requirement is not to mutate that experience, but to add a separate app-oriented shell at `/agentplayground`. This shell should feel like an operational console, not a chat surface.

The first app is `G 文件对比`, which needs historical task rows, modal file submission, a backend compare execution flow, and downloadable report outputs. Future apps are expected, but they may not use the same right-hand workspace layout.

## Goals / Non-Goals

**Goals:**
- Add `/agentplayground` without changing `/assistant/`.
- Make playground access authless-only.
- Show a default welcome page before app selection.
- Add a fixed app list with `G 文件对比` as the first app.
- Store each app under `~/.nanobot/agentplayground/<app_id>/`.
- Store each app's SQLite database in its own app root as `app.db`.
- Process each app's jobs serially in the first version.

**Non-Goals:**
- Dynamic app publishing in this step.
- Converting `/assistant/` into a multi-app shell.
- Forcing all future apps into a table layout.
- Using one global `agentplayground.db`.
- Running multiple jobs from the same app concurrently in this phase.

## Decisions

### 1. Same repo, second shell

Implement `agentplayground` inside the current project so deployment, branding, uploads, downloads, and app execution stay shared. Keep the shell and route tree separate from `/assistant/`.

### 2. Public-only route contract

When `WEBUI_AUTH_DISABLED=true`, `/agentplayground` is available. When it is false, direct access redirects to `/assistant/`.

Both `/agentplayground` and `/agentplayground/<app_id>` use the same public-only gate. A direct known app route should open the matching workspace; an unknown app id should not break the shell.

### 3. App shell versus app workspace

The shell owns:

- app list
- selection state
- welcome panel
- shared route/layout framing

Each app owns:

- workspace component
- table/form/detail layout
- API hooks
- app-specific database
- job directories
- execution queue

### 4. Each app owns an isolated root

Use:

```text
~/.nanobot/agentplayground/<app_id>/
```

For `G 文件对比`:

```text
~/.nanobot/agentplayground/g-file-compare/
  app.db
  skills/
    g-file-contrast/
      SKILL.md
      scripts/
        run_job.py
        compare_g_files.py
  jobs/
    <job_id>/
      inputs.json
      inputs/
        d5000/
          <D5000原文件名>
        new-gen/
          <新一代原文件名>
      report.txt
      result.json
```

The existing chat workspace remains:

```text
~/.nanobot/workspace
```

The app execution layer must not mutate or reuse the chat `AgentLoop.workspace`. App-specific skill runners must be loaded from the app root, not from `~/.nanobot/workspace/skills`.

### 5. Each app owns its schema

Because `app.db` belongs to one app, `g-file-compare` can store its business fields directly in a single `jobs` table. This avoids a global common table that would either overfit the first app or become sparse as future apps diverge.

### 6. First app uses a task table

`G 文件对比` should render a table with:

- `D5000 文件`
- `新一代文件`
- `状态`
- `下载`

The `新增` action opens a modal for the two-file upload flow.

### 7. First version uses serial processing

Users may create many jobs, but `g-file-compare` should process only one job at a time. Additional jobs remain `queued` until the worker picks them up. This keeps the first version predictable and leaves concurrency as a later worker-count change.

The queue should treat `processing` rows left behind by a crashed or restarted backend as recoverable before starting new work. The first version may either requeue them or mark them failed with a clear error, but it must not leave them permanently stuck as active work.

### 8. Shared public history

The app history is deployment-wide, not user-scoped. In public mode, any visitor can see the retained `G 文件对比` rows and download completed reports. This matches the current requirement for a shared application workspace and avoids introducing account-level ownership before authentication is part of the playground.

## Risks / Trade-offs

- Serial processing may queue jobs under load, but it avoids premature concurrency problems.
- Per-app SQLite databases make cross-app analytics harder, but they give stronger business isolation and simpler app schemas.
- App execution must not depend on prompt-only path discipline; the service/runner boundary should pass app root and job id rather than arbitrary paths.
- The public shared history exposes uploaded file names and completed reports to all visitors, so this surface should only be enabled in deployments where that visibility is acceptable.

## Migration Plan

1. Update the current implementation from global playground DB to per-app `app.db`.
2. Move `g-file-compare` files out of the chat workspace and into `~/.nanobot/agentplayground/g-file-compare/jobs/<job_id>/`.
3. Collapse the shared `jobs` + `g_file_compare_jobs` schema into the app-specific `jobs` table.
4. Add an app-level serial queue.
5. Keep `/assistant/` behavior unchanged.
