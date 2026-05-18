## ADDED Requirements

### Requirement: Authless deployments SHALL expose a public app playground
The system SHALL expose a dedicated `/agentplayground` shell when authless mode is enabled, while leaving the existing `/assistant/` chat shell unchanged.

#### Scenario: Open playground in authless mode
- **WHEN** `WEBUI_AUTH_DISABLED` is enabled and the user opens `/agentplayground`
- **THEN** the frontend SHALL render the playground shell instead of redirecting to `/assistant/`

#### Scenario: Open playground in normal mode
- **WHEN** `WEBUI_AUTH_DISABLED` is disabled and the user opens `/agentplayground`
- **THEN** the system SHALL redirect the user to `/assistant/`

#### Scenario: Open selected app route in normal mode
- **WHEN** `WEBUI_AUTH_DISABLED` is disabled and the user opens `/agentplayground/g-file-compare`
- **THEN** the system SHALL redirect the user to `/assistant/`

### Requirement: Playground SHALL render a welcome page before app selection
The playground shell SHALL show a default welcome page until the user selects an app from the app list.

#### Scenario: Playground default state
- **WHEN** the user first opens `/agentplayground`
- **THEN** the right-hand workspace SHALL render a welcome page prompting the user to choose an app

### Requirement: Playground SHALL list fixed registered apps
The first version of the playground SHALL use a fixed in-code app registry to render its app list.

#### Scenario: Registered app appears in app list
- **WHEN** the playground shell renders
- **THEN** the app list SHALL include `G 文件对比`

#### Scenario: Direct registered app route
- **WHEN** `WEBUI_AUTH_DISABLED` is enabled and the user opens `/agentplayground/g-file-compare`
- **THEN** the frontend SHALL render the playground shell with the `G 文件对比` workspace selected

#### Scenario: Unknown app route
- **WHEN** `WEBUI_AUTH_DISABLED` is enabled and the user opens `/agentplayground/<unknown-app-id>`
- **THEN** the frontend SHALL keep the playground shell available and show a non-destructive unknown-app or welcome state

### Requirement: G file compare SHALL provide a job table workspace
The `G 文件对比` app SHALL render a table-backed workspace showing compare job history.

#### Scenario: Compare workspace columns
- **WHEN** the `G 文件对比` workspace renders
- **THEN** the table SHALL show `D5000 文件`, `新一代文件`, `状态`, and `下载` columns

#### Scenario: Create compare job
- **WHEN** the user clicks `新增` and uploads both required files
- **THEN** the system SHALL create a compare job row with `queued` status and enqueue it for processing

#### Scenario: Missing required input
- **WHEN** the user submits the create dialog without both required files
- **THEN** the system SHALL reject the request without creating a compare job

#### Scenario: Completed compare job
- **WHEN** a compare job finishes successfully
- **THEN** the workspace SHALL show the job as completed and expose a downloadable report artifact

#### Scenario: Failed compare job
- **WHEN** a compare job fails during execution
- **THEN** the workspace SHALL keep the job visible with `failed` status and preserve an error message for troubleshooting

### Requirement: G file compare history SHALL be globally shared in public mode
The `G 文件对比` app SHALL expose one shared job history for the deployment rather than user-scoped histories.

#### Scenario: Any visitor sees existing jobs
- **WHEN** any visitor opens the `G 文件对比` workspace in authless mode
- **THEN** the table SHALL show all retained compare jobs for the app

#### Scenario: Job history retention
- **WHEN** compare jobs complete or fail
- **THEN** their rows and job directories SHALL remain available until an explicit retention cleanup feature is added

### Requirement: Playground job storage SHALL be isolated per app
The playground backend SHALL persist each app under its own app root and SHALL NOT use one global playground database for all apps.

#### Scenario: App-specific database
- **WHEN** a compare job is created
- **THEN** the backend SHALL persist job data in `~/.nanobot/agentplayground/g-file-compare/app.db`

#### Scenario: App-specific job directory
- **WHEN** a compare job is created
- **THEN** the backend SHALL store input and output files under `~/.nanobot/agentplayground/g-file-compare/jobs/<job_id>/`

#### Scenario: Chat workspace isolation
- **WHEN** a compare job is created or executed
- **THEN** the backend SHALL NOT place job files under the chat workspace `~/.nanobot/workspace`

#### Scenario: App root is execution workspace
- **WHEN** the backend executes a compare job
- **THEN** the execution boundary SHALL use `~/.nanobot/agentplayground/g-file-compare` as the app workspace root

#### Scenario: No user-controlled output paths
- **WHEN** the backend stores uploaded inputs or generated outputs
- **THEN** the backend SHALL choose canonical paths under `jobs/<job_id>/` and SHALL NOT trust client-provided filesystem paths

### Requirement: G file compare jobs SHALL process serially in the first version
The first version SHALL allow users to create multiple jobs but SHALL execute at most one `G 文件对比` job at a time.

#### Scenario: Multiple queued jobs
- **WHEN** multiple compare jobs are created
- **THEN** jobs not currently executing SHALL remain in `queued` status until the app worker processes them

#### Scenario: Processing one job
- **WHEN** the app worker starts a queued job
- **THEN** it SHALL mark that job as `processing` and SHALL NOT start another `G 文件对比` job until the current one reaches `completed` or `failed`

#### Scenario: Recover interrupted processing jobs
- **WHEN** the backend starts and finds `processing` jobs from a previous process
- **THEN** it SHALL move them to a recoverable terminal or queued state before processing new queued jobs

### Requirement: G file compare reports SHALL remain downloadable
Completed compare jobs SHALL expose a report download through backend-controlled download metadata.

#### Scenario: Download completed report
- **WHEN** a compare job is `completed` and has a generated report file
- **THEN** the backend SHALL return a download token or URL that resolves to that report file

#### Scenario: Download unavailable before completion
- **WHEN** a compare job is `queued`, `processing`, or `failed`
- **THEN** the workspace SHALL NOT expose an active report download action for that job
