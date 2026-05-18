## 1. Spec and scaffolding

- [x] 1.1 Add openspec proposal/design/tasks/spec for `agentplayground`
- [x] 1.2 Add route and persistence test coverage for the new shell and compare jobs

## 2. Backend storage and APIs

- [x] 2.1 Add SQLite-backed job storage
- [x] 2.2 Add playground and `G 文件对比` backend routes
- [x] 2.3 Gate `/agentplayground` behind authless mode and redirect to `/assistant/` otherwise
- [x] 2.4 Move `G 文件对比` to per-app root `~/.nanobot/agentplayground/g-file-compare`
- [x] 2.5 Store `G 文件对比` data in per-app `app.db`
- [x] 2.6 Process `G 文件对比` jobs through an app-level serial queue
- [x] 2.7 Add recovery handling for stale `processing` jobs on backend startup
- [x] 2.8 Ensure download metadata is only active for completed jobs

## 3. Frontend shell

- [x] 3.1 Add `/agentplayground` route and welcome page
- [x] 3.2 Add left-side app list with fixed registered apps
- [x] 3.3 Keep `/assistant/` behavior unchanged
- [x] 3.4 Support direct `/agentplayground/g-file-compare` route and unknown app fallback

## 4. G file compare workspace

- [x] 4.1 Add the table workspace with `D5000 文件 / 新一代文件 / 状态 / 下载`
- [x] 4.2 Add the `新增` modal with two-file upload
- [x] 4.3 Refresh the table after job creation and on status updates
- [x] 4.4 Keep history globally shared across visitors in public mode
- [x] 4.5 Disable report download action until a job reaches `completed`

## 5. Verification

- [x] 5.1 Run targeted backend tests for playground routing, per-app storage, serial queue, and downloads
- [x] 5.2 Run frontend production build
- [x] 5.3 Mark the tasks complete after verification
