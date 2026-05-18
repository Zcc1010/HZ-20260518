# Runtime Diagnostics Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple local nginx from the root compose file and add opt-in runtime diagnostics for WebSocket, agent loop, and provider timing.

**Architecture:** Keep all diagnostics behind environment flags so production behavior stays unchanged when disabled. Implement diagnostics as a dedicated startup patch module so the runtime-only instrumentation stays isolated from business logic and can be enabled through compose env vars.

**Tech Stack:** Python, FastAPI WebSocket routes, loguru, Docker Compose, pytest

---

### Task 1: Remove Root Compose Nginx Coupling

**Files:**
- Modify: `docker-compose.yml`
- Create: `deployment/local-nginx/docker-compose.yml`

**Step 1: Remove the `nginx` service from the root compose file**

**Step 2: Add a separate local nginx compose file that depends on the existing `webui` service**

**Step 3: Verify the root compose remains usable without nginx**

**Step 4: Commit with the diagnostics changeset**

### Task 2: Add Opt-In Runtime Diagnostics

**Files:**
- Create: `webui/patches/diagnostics.py`
- Modify: `webui/patches/__init__.py`
- Modify: `webui/api/routes/ws.py`
- Modify: `webui/patches/provider.py`
- Modify: `webui/__main__.py`
- Modify: `deployment/release/docker-compose.yml`

**Step 1: Add a shared diagnostics helper with env-gated logging**

**Step 2: Log WebSocket session/task lifecycle, disconnect, cancel, and per-message timing**

**Step 3: Log provider call start/end, duration, retry waits, and response metadata**

**Step 4: Patch agent loop entry points to expose local pre-provider timing**

**Step 5: Expose the diagnostics env vars in release compose**

### Task 3: Add Minimal Regression Coverage

**Files:**
- Create: `tests/test_diagnostics_patch.py`

**Step 1: Write a failing test for env parsing / diagnostics enablement**

**Step 2: Run the test to verify it fails**

**Step 3: Implement the minimal diagnostics helper needed for the test**

**Step 4: Run the focused test and confirm it passes**

### Task 4: Verification

**Step 1: Run the focused pytest file**

**Step 2: Run a lightweight import/compose sanity check**

**Step 3: Review `git diff` and create the second commit**
