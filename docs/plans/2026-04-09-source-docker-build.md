# Source Docker Build Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Docker and Compose run the current customized repository source instead of the published `nanobot-webui` package image.

**Architecture:** Replace the release-oriented Dockerfile with a source-based multi-stage build: a Bun frontend build stage plus a Python runtime stage that installs the local package and serves the bundled static assets. Update Compose and Make targets so default local deployment uses an isolated data directory, a non-conflicting host port, and WebUI-only authless defaults.

**Tech Stack:** Docker, Docker Compose, Bun, Python 3.11, uv, FastAPI, nanobot-webui packaging

---

### Task 1: Source-based Docker image

**Files:**
- Modify: `Dockerfile`

**Step 1: Replace package-version install with local source build**

Build the frontend inside Docker, copy `web/dist` into `webui/web/dist`, then install the current repository with `uv pip install --system .`.

**Step 2: Keep runtime entrypoint compatible**

Preserve `scripts/docker-entrypoint.sh` so runtime CLI/env handling stays unchanged.

### Task 2: Parallel-safe local Compose defaults

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Switch Compose from remote image to local build**

Use `build: .` so `docker compose up --build` runs the current workspace code.

**Step 2: Set safe local defaults**

Use host port `18781`, isolated data path `~/.nanobot-webui`, and enable `WEBUI_ONLY=true` plus `WEBUI_AUTH_DISABLED=true`.

### Task 3: Developer shortcuts

**Files:**
- Modify: `Makefile`

**Step 1: Keep Docker helper commands aligned with the new source-based flow**

Make `make build` and `make up` target the local source image/compose workflow without assuming PyPI release packaging.

### Task 4: Verification

**Files:**
- Verify only

**Step 1: Validate Docker and Compose file syntax**

Run lightweight checks such as `docker compose config` if available, otherwise inspect generated config-relevant files for consistency.

**Step 2: Sanity-check image assumptions**

Confirm the Dockerfile copies frontend assets and installs the local package instead of `nanobot-webui==<version>`.
