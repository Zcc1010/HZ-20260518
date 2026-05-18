# Agent Playground Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a public-only `/agentplayground` shell with a welcome page, app list, and a first `G 文件对比` table workspace backed by per-app SQLite job storage and downloadable report artifacts.

**Architecture:** Keep `/assistant/` unchanged and add a second public shell at `/agentplayground`. Use a fixed in-code app registry, per-app roots under `~/.nanobot/agentplayground/<app_id>/`, one `app.db` per app, and app-specific workspace rendering so future apps can diverge from the first table-based UI.

**Tech Stack:** React, React Router, TanStack Query, FastAPI, SQLite, existing upload/download plumbing, existing authless bootstrap flow.

---

### Task 1: Capture the product contract in spec/docs

**Files:**
- Create: `openspec/changes/add-agentplayground-and-g-file-compare/proposal.md`
- Create: `openspec/changes/add-agentplayground-and-g-file-compare/design.md`
- Create: `openspec/changes/add-agentplayground-and-g-file-compare/tasks.md`
- Create: `openspec/changes/add-agentplayground-and-g-file-compare/.openspec.yaml`
- Create: `openspec/changes/add-agentplayground-and-g-file-compare/specs/agentplayground/spec.md`

**Step 1: Write the spec files**

Describe:
- `/agentplayground` public-only routing
- welcome page behavior
- fixed app list behavior
- `G 文件对比` table contract
- job lifecycle and download behavior

**Step 2: Review spec coherence**

Run: `sed -n '1,240p' openspec/changes/add-agentplayground-and-g-file-compare/proposal.md`
Expected: proposal clearly scopes the shell, routing, and first app

**Step 3: Commit**

```bash
git add openspec/changes/add-agentplayground-and-g-file-compare
git commit -m "docs: add agentplayground openspec change"
```

### Task 2: Add failing backend tests for public routing and SQLite job behavior

**Files:**
- Create: `tests/test_agentplayground_routes.py`
- Create: `tests/test_g_file_compare_jobs.py`
- Modify: `webui/api/server.py`

**Step 1: Write a failing route test**

Cover:
- authless on: `/agentplayground` returns the new shell entry or SPA fallback
- authless off: `/agentplayground` redirects to `/assistant/`

**Step 2: Write a failing job persistence test**

Cover:
- creating a `G 文件对比` job writes one row to `~/.nanobot/agentplayground/g-file-compare/app.db`
- uploaded files are stored under `~/.nanobot/agentplayground/g-file-compare/jobs/<job_id>/`
- completed jobs return `result_file_name` and a downloadable artifact path

**Step 3: Run the tests to verify red**

Run:
- `./.venv/bin/python -m pytest -q tests/test_agentplayground_routes.py`
- `./.venv/bin/python -m pytest -q tests/test_g_file_compare_jobs.py`

Expected: FAIL because the playground routes/services do not exist yet.

**Step 4: Commit**

```bash
git add tests/test_agentplayground_routes.py tests/test_g_file_compare_jobs.py
git commit -m "test: add failing agentplayground coverage"
```

### Task 3: Implement per-app SQLite storage and service layer

**Files:**
- Create: `webui/services/agentplayground/paths.py`
- Create: `webui/services/agentplayground/db.py`
- Create: `webui/services/agentplayground/models.py`
- Create: `webui/services/agentplayground/registry.py`
- Create: `webui/services/g_file_compare/service.py`
- Modify: `webui/api/gateway.py`

**Step 1: Implement per-app path resolution**

Resolve:

- `~/.nanobot/agentplayground/<app_id>/`
- `~/.nanobot/agentplayground/<app_id>/app.db`
- `~/.nanobot/agentplayground/<app_id>/jobs/<job_id>/`

Do not place app files under `~/.nanobot/workspace`.

**Step 2: Implement the app-specific SQLite schema**

For `g-file-compare/app.db`, add one `jobs` table containing lifecycle fields plus `D5000`, `新一代`, and result metadata.

**Step 3: Implement minimal CRUD/query helpers**

Add functions for:
- init app schema
- create compare job
- list compare jobs
- mark processing/completed/failed

**Step 4: Wire the service into the runtime container**

Expose the DB/service from the backend service container so routes can use it.

**Step 5: Run the persistence tests**

Run: `./.venv/bin/python -m pytest -q tests/test_g_file_compare_jobs.py`
Expected: PASS, with app data stored outside the chat workspace.

**Step 6: Commit**

```bash
git add webui/services/agentplayground webui/services/g_file_compare webui/api/gateway.py
git commit -m "feat: add agentplayground sqlite job storage"
```

### Task 4: Add backend APIs and authless gating

**Files:**
- Create: `webui/api/routes/agentplayground.py`
- Create: `webui/api/routes/g_file_compare.py`
- Modify: `webui/api/models.py`
- Modify: `webui/api/server.py`

**Step 1: Add API models**

Define request/response schemas for:
- app list
- compare job row
- create compare job request

**Step 2: Add route handlers**

Support:
- list registered apps
- list `G 文件对比` jobs
- create `G 文件对比` job with two uploaded files
- download through the existing file route contract

**Step 3: Enforce authless-only access**

When `WEBUI_AUTH_DISABLED` is false:
- playground endpoints redirect or reject for the frontend shell flow

**Step 4: Run route tests**

Run:
- `./.venv/bin/python -m pytest -q tests/test_agentplayground_routes.py`
- `./.venv/bin/python -m pytest -q tests/test_file_downloads.py`

Expected: PASS

**Step 5: Commit**

```bash
git add webui/api/routes/agentplayground.py webui/api/routes/g_file_compare.py webui/api/models.py webui/api/server.py
git commit -m "feat: add agentplayground backend routes"
```

### Task 5: Add the playground frontend shell

**Files:**
- Create: `web/src/pages/AgentPlayground.tsx`
- Create: `web/src/components/agentplayground/AppList.tsx`
- Create: `web/src/components/agentplayground/WelcomePanel.tsx`
- Create: `web/src/lib/agentplayground/registry.ts`
- Modify: `web/src/App.tsx`

**Step 1: Add a failing frontend route smoke test or at minimum build expectation**

If no frontend test harness is present, use the build as the safety net and document the lack of route tests.

**Step 2: Add `/agentplayground` routes**

Behavior:
- authless on: render playground shell
- authless off: redirect to `/assistant/`

**Step 3: Render the left app list and default welcome page**

Keep:
- fixed app registry
- welcome prompt until an app is selected

**Step 4: Build the frontend**

Run: `npm run build`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/pages/AgentPlayground.tsx web/src/components/agentplayground web/src/lib/agentplayground/registry.ts web/src/App.tsx
git commit -m "feat: add agentplayground shell"
```

### Task 6: Implement the G file compare table workspace

**Files:**
- Create: `web/src/components/agentplayground/gfilecompare/GFileCompareWorkspace.tsx`
- Create: `web/src/components/agentplayground/gfilecompare/CreateGCompareDialog.tsx`
- Create: `web/src/hooks/useGFileCompare.ts`
- Modify: `web/src/i18n/locales/zh.json`
- Modify: `web/src/i18n/locales/en.json`

**Step 1: Add the table workspace**

Columns:
- `D5000 文件`
- `新一代文件`
- `状态`
- `下载`

**Step 2: Add the modal**

Fields:
- two file uploads
- submit/cancel actions

**Step 3: Connect the API hooks**

Implement:
- job list query
- create job mutation
- optimistic refresh after submit

**Step 4: Build the frontend**

Run: `npm run build`
Expected: PASS

**Step 5: Commit**

```bash
git add web/src/components/agentplayground/gfilecompare web/src/hooks/useGFileCompare.ts web/src/i18n/locales/zh.json web/src/i18n/locales/en.json
git commit -m "feat: add g file compare workspace"
```

### Task 7: Add app-level serial queue and execution boundary

**Files:**
- Modify: `webui/services/g_file_compare/service.py`
- Create: `webui/services/g_file_compare/queue.py`
- Modify: `webui/api/routes/g_file_compare.py`
- Modify: `tests/test_g_file_compare_jobs.py`

**Step 1: Write a failing serial queue test**

Cover:
- multiple created jobs remain queued
- worker processes one job at a time
- service transitions one job through processing to completed before the next starts

**Step 2: Implement the serial queue**

The queue should call a service execution boundary for a single job. Do not hold database transactions while executing the job.

**Step 3: Keep the execution boundary app-root/job-id based**

The exact skill implementation is separate, but the service boundary should be shaped as:

```python
execute_job(app_root: Path, job_id: str) -> Path
```

Do not pass arbitrary user-controlled input/output paths.

**Step 4: Run the targeted tests**

Run: `./.venv/bin/python -m pytest -q tests/test_g_file_compare_jobs.py`
Expected: PASS

**Step 5: Commit**

```bash
git add webui/services/g_file_compare/service.py webui/api/routes/g_file_compare.py tests/test_g_file_compare_jobs.py
git commit -m "feat: execute g file compare jobs"
```

### Task 8: Final verification

**Files:**
- Modify: `openspec/changes/add-agentplayground-and-g-file-compare/tasks.md`

**Step 1: Run backend verification**

Run:
- `./.venv/bin/python -m pytest -q tests/test_agentplayground_routes.py tests/test_g_file_compare_jobs.py tests/test_file_downloads.py`

Expected: PASS

**Step 2: Run frontend verification**

Run:
- `npm run build`

Expected: PASS

**Step 3: Update task checklist**

Mark completed items in `openspec/changes/add-agentplayground-and-g-file-compare/tasks.md`.

**Step 4: Commit**

```bash
git add openspec/changes/add-agentplayground-and-g-file-compare/tasks.md
git commit -m "docs: mark agentplayground tasks complete"
```
