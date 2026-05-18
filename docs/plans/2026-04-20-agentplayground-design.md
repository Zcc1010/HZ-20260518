# Agent Playground Design

## Context

The current WebUI has one authless-facing shell under `/assistant/`, optimized for chat. A new public-facing surface is needed for operational apps such as `G 文件对比`, but the existing chat UI must remain unchanged. The new surface should live at `/agentplayground`, only be available when `WEBUI_AUTH_DISABLED=true`, and redirect back to `/assistant/` otherwise.

The first app is `G 文件对比`. Its workspace is a task table rather than a chat flow. Future apps are expected, but their right-hand workspaces may not all look like tables, so the shell must separate platform navigation from per-app workspace rendering.

The system model is intentionally app-isolated: each app owns its own workspace, its own SQLite database, and its own job directories. The chat workspace must never be switched or reused for app execution.

## Goals

- Add a second public entrypoint at `/agentplayground` without changing `/assistant/`.
- Restrict `/agentplayground` to authless/public deployments.
- Render a dedicated playground shell with left-side app list and right-side welcome/app workspace.
- Ship `G 文件对比` as the first app with a table workspace and modal-driven task creation.
- Keep each app isolated under `~/.nanobot/agentplayground/<app_id>/`.
- Persist each app's job history in its own `app.db`.
- Run app jobs through an app-level serial queue.

## Non-Goals

- Rebuild the existing `/assistant/` chat shell.
- Add dynamic app registration or admin publishing in this phase.
- Generalize all app workspaces into one common table UI.
- Share one global `agentplayground.db` across apps.
- Execute multiple jobs from the same app concurrently in the first version.

## Product Decisions

### 1. Same repository, second public shell

`/agentplayground` should be implemented inside the current project, not as a new repository. This keeps deployment, branding, file handling, and skill execution shared while preventing the chat app from being polluted by app-platform concerns.

### 2. Public-only access

The playground should only exist in authless/public mode. When authless mode is disabled:

- frontend navigation should not expose the playground entry
- direct access to `/agentplayground` should redirect to `/assistant/`

### 3. Two-column playground shell

The playground itself should not reuse the chat session list layout. It should use:

- left column: app list
- right column: welcome panel or selected app workspace

The default state is a welcome page prompting the user to choose an app. This avoids forcing `G 文件对比` as the implied default forever.

### 4. App shell is generic, app workspace is specific

The platform should only standardize:

- app registry
- app selection
- authless gating
- app root path resolution
- common download token dispatch

Each app owns:

- workspace component
- API hooks
- app database schema
- job directory structure
- execution queue

`G 文件对比` uses a table workspace now, but future apps may use forms, inspectors, step flows, or dashboards.

### 5. Each app owns a stable workspace root

Use stable app ids as internal path names. Chinese names are display-only.

For `G 文件对比`:

```text
~/.nanobot/
  workspace/                         # existing chat workspace, unchanged
  agentplayground/
    g-file-compare/
      app.db
      skills/
        g-file-contrast/
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

The app root `~/.nanobot/agentplayground/g-file-compare` is the app's workspace. Do not point any app execution at the chat workspace, and do not mutate `container.agent.workspace`.

App-specific skills live under the app root. For `G 文件对比`, the runner path is:

```text
~/.nanobot/agentplayground/g-file-compare/skills/g-file-contrast/scripts/run_job.py
```

The backend must not load this app runner from `~/.nanobot/workspace/skills`, because that directory belongs to the chat agent and would make the app skill visible in the chat UI.

### 6. Each app owns its own SQLite database

Do not use a global `agentplayground.db`. Store the first app's database at:

```text
~/.nanobot/agentplayground/g-file-compare/app.db
```

Because this DB belongs only to `g-file-compare`, its schema can be app-specific and does not need a shared `jobs` + app detail split.

### 7. First version uses an app-level serial queue

Users may create multiple jobs, but the backend should process one `g-file-compare` job at a time:

```text
queued -> processing -> completed
queued -> processing -> failed
```

This avoids early concurrency complexity around DB locks, app workspace writes, and skill execution. The file layout still uses `jobs/<job_id>/`, so future worker concurrency can be added later.

## Information Architecture

### Routes

- `/assistant/`
  - existing chat application, unchanged
- `/agentplayground`
  - playground shell root
- `/agentplayground/:appId`
  - selected app workspace

When authless mode is disabled, both `/agentplayground` and `/agentplayground/:appId` should redirect to `/assistant/`.

### Playground Layout

Left app rail:

- title: `应用广场`
- app items
  - `G 文件对比`

Right workspace:

- default: welcome page with product copy and a clickable app card/list
- selected `g-file-compare`: `G 文件对比` workspace

## G File Compare Workspace

### Visual Thesis

This page should feel like an operational console rather than a marketing surface: pale government-blue shell, precise spacing, quiet typography, one clear primary action, and a dense-but-readable task table.

### Workspace Structure

Top bar:

- title: `G 文件对比`
- primary button: `新增`

Table columns:

- `D5000 文件`
- `新一代文件`
- `状态`
- `下载`

Supported states:

- `排队中`
- `处理中`
- `已完成`
- `失败`

### Create Dialog

The `新增` button opens a modal containing:

- `D5000 文件` upload
- `新一代文件` upload
- primary action: `开始生成`
- cancel action

Submitting the dialog should create a job row immediately, store both files in the app job directory, and enqueue the job.

## Data Model

### SQLite location

For `G 文件对比`:

```text
~/.nanobot/agentplayground/g-file-compare/app.db
```

### Table: `jobs`

Because the DB is app-specific, the `jobs` table may contain app-specific fields:

- `id`
- `status`
- `created_at`
- `updated_at`
- `created_by`
- `error_message`
- `d5000_file_name`
- `d5000_file_path`
- `new_gen_file_name`
- `new_gen_file_path`
- `result_file_name`
- `result_file_path`
- `result_json_path`
- `result_download_token`
- `result_mime_type`
- `result_file_size`

Use short transactions and SQLite WAL/busy timeout settings. Do not hold database transactions while a skill job runs.

## Execution Flow

1. User opens `/agentplayground`.
2. User selects `G 文件对比`.
3. User clicks `新增`.
4. Frontend uploads the two files and posts a create-job request.
5. Backend creates:

```text
~/.nanobot/agentplayground/g-file-compare/jobs/<job_id>/
```

6. Backend stores the uploaded files under source-specific directories and preserves original names:

```text
jobs/<job_id>/inputs.json
jobs/<job_id>/inputs/d5000/<D5000原文件名>
jobs/<job_id>/inputs/new-gen/<新一代原文件名>
```

7. Backend writes the app-specific `jobs` row with `status=queued`.
8. The app-level worker processes queued jobs one at a time.
9. Worker sets `status=processing`.
10. Worker calls the app execution boundary. The exact skill implementation is separate, but it must read/write inside the app workspace and current job directory.
11. Execution produces:

```text
jobs/<job_id>/report.txt
jobs/<job_id>/result.json
```

12. Backend records result metadata and download token, then sets `status=completed`.
13. Frontend refreshes the table and enables `下载`.

Failure flow:

- store `error_message`
- mark status `failed`
- keep the row and job directory visible for investigation

## Backend Architecture

Recommended modules:

- `webui/api/routes/agentplayground.py`
- `webui/api/routes/g_file_compare.py`
- `webui/services/agentplayground/paths.py`
- `webui/services/agentplayground/registry.py`
- `webui/services/g_file_compare/service.py`
- `webui/services/g_file_compare/queue.py`

Recommended responsibilities:

- route layer: request validation, authless gating, HTTP response models
- registry: fixed app definitions available to the playground shell
- paths: resolve `~/.nanobot/agentplayground/<app_id>` and app job directories
- service: app-specific SQLite, file persistence, status transitions, download token lookup
- queue: one-worker serial execution for the app

## Frontend Architecture

Recommended modules:

- `web/src/pages/AgentPlayground.tsx`
- `web/src/components/agentplayground/AppList.tsx`
- `web/src/components/agentplayground/WelcomePanel.tsx`
- `web/src/components/agentplayground/gfilecompare/GFileCompareWorkspace.tsx`
- `web/src/components/agentplayground/gfilecompare/CreateGCompareDialog.tsx`
- `web/src/lib/agentplayground/registry.ts`

Recommended responsibilities:

- page: route-level selection and authless redirect handling
- app list: render fixed registered apps
- welcome panel: default empty state
- workspace component: app-specific layout and data fetching
- dialog: file upload form and submit lifecycle

## Risks

- App execution may be slower than a normal CRUD workflow.
  - Mitigation: keep explicit row statuses and optimistic row creation.
- Serial execution may create a queue during heavy use.
  - Mitigation: expose `queued` clearly; add worker concurrency later only after app workspace isolation is proven.
- The first app may tempt over-generalization.
  - Mitigation: keep shell generic, keep app databases and workspaces app-specific.
- The execution boundary must not mutate the chat `AgentLoop`.
  - Mitigation: treat `/root/.nanobot/workspace` and `/root/.nanobot/agentplayground/<app_id>` as separate roots.

## Verification

- frontend build succeeds with the new `/agentplayground` entry
- `/assistant/` remains unchanged
- `/agentplayground` redirects to `/assistant/` when authless mode is off
- `/agentplayground` renders welcome page when authless mode is on
- `G 文件对比` table shows created history rows
- create dialog stores files under `~/.nanobot/agentplayground/g-file-compare/jobs/<job_id>/`
- `app.db` lives under `~/.nanobot/agentplayground/g-file-compare/app.db`
- queued jobs are processed serially
- completed jobs expose a downloadable report file
