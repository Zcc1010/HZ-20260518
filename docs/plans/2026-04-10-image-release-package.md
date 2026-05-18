# Image Release Package Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a repeatable packaging flow that builds the customized Docker image, exports it as a compressed `tar.gz`, and writes a release directory with the deployment files needed for intranet delivery.

**Architecture:** Keep the release flow out of the runtime container logic. A host-side shell script will build the local image, prepare a clean release directory under `deployment/release/`, export the image with `docker save | gzip`, and copy templated deployment files into that directory. The deployment documentation will explain the intranet-side flow: edit `config.json`, import the image, and start with `docker compose`.

**Tech Stack:** Shell script, Docker CLI, Docker Compose, Markdown documentation

---

### Task 1: Add release packaging script

**Files:**
- Create: `scripts/build-image-release.sh`

**Step 1: Write the failing test**

Manual expectation: there is currently no single command that creates `deployment/release/nanobot-webui-local.tar.gz` together with deployment runtime files.

**Step 2: Run test to verify it fails**

Run: `test -x scripts/build-image-release.sh`
Expected: FAIL because the script does not exist yet.

**Step 3: Write minimal implementation**

Create a shell script that:
- builds `nanobot-webui:local` by default
- recreates `deployment/release/`
- exports the image as `nanobot-webui-local.tar.gz`
- copies runtime compose/config template/env template into the release directory
- writes a release README for intranet operators

**Step 4: Run test to verify it passes**

Run: `scripts/build-image-release.sh --help`
Expected: PASS and prints usage.

**Step 5: Commit**

```bash
git add scripts/build-image-release.sh
git commit -m "feat: add image release packaging script"
```

### Task 2: Add release metadata and deployment instructions

**Files:**
- Create: `docs/image-release-package.md`
- Modify: `scripts/build-image-release.sh`

**Step 1: Write the failing test**

Manual expectation: there is currently no tracked document describing the exact external-network packaging flow and intranet import/startup flow for the release directory.

**Step 2: Run test to verify it fails**

Run: `test -f docs/image-release-package.md`
Expected: FAIL because the document does not exist yet.

**Step 3: Write minimal implementation**

Add a concise tracked document describing:
- prerequisites on the packaging host
- packaging command
- expected release directory structure
- intranet deployment steps

Update the packaging script so the generated release README is aligned with the tracked documentation.

**Step 4: Run test to verify it passes**

Run: `test -f docs/image-release-package.md`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/image-release-package.md scripts/build-image-release.sh
git commit -m "docs: describe image release deployment flow"
```

### Task 3: Verify release output

**Files:**
- Test: `deployment/release/`

**Step 1: Write the failing test**

Manual expectation: before running the packaging script, `deployment/release/` should not contain a fresh `nanobot-webui-local.tar.gz` bundle and generated deployment files for this build.

**Step 2: Run test to verify it fails**

Run: `test -f deployment/release/nanobot-webui-local.tar.gz`
Expected: FAIL before packaging.

**Step 3: Write minimal implementation**

Run the packaging script to produce the release output.

**Step 4: Run test to verify it passes**

Run: `test -f deployment/release/nanobot-webui-local.tar.gz && test -f deployment/release/docker-compose.yml && test -f deployment/release/README.md`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/image-release-package.md scripts/build-image-release.sh
git commit -m "chore: verify image release package flow"
```
