# Runtime Document Ingestion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add runtime document parsing so uploaded Office files are automatically extracted for chat use, with an agent tool fallback and explicit OFD unsupported handling.

**Architecture:** The backend keeps originals in the existing upload path, classifies supported document types, and runs a shared ingestion service. `markitdown` is the primary extractor, LibreOffice is the conversion fallback for legacy Office formats, and the same service powers both automatic upload-time parsing and an on-demand agent tool. OFD is explicitly classified as unsupported in this phase. The frontend upgrades attachment handling from “URL only” to structured upload metadata so extracted text can be injected into the first chat turn.

**Tech Stack:** FastAPI, React/Vite, Docker multi-stage build, `markitdown`, LibreOffice headless conversion, nanobot runtime tools.

---

### Task 1: Add runtime dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile`
- Modify: `README_zh.md`

**Step 1: Add the failing runtime expectation**

Write down the expected dependency contract in comments or docs before code:
- runtime image contains `soffice`
- Python environment can import `markitdown`

**Step 2: Update Python dependency declaration**

Add `markitdown` to the runtime dependencies in `pyproject.toml`.

**Step 3: Update Docker runtime image**

Install the minimal headless LibreOffice packages needed for `doc/docx/xls/xlsx/ppt/pptx` conversion in `Dockerfile`.

**Step 4: Verify dependency availability**

Run:
```bash
docker compose build
docker run --rm nanobot-webui:local sh -lc 'command -v soffice && python -c "import markitdown; print(\"ok\")"'
```
Expected: `soffice` path printed and `ok`.

**Step 5: Commit**

```bash
git add pyproject.toml Dockerfile README_zh.md
git commit -m "feat: add runtime document parsing dependencies"
```

### Task 2: Introduce a shared ingestion service

**Files:**
- Create: `webui/services/document_ingestion.py`
- Test: `tests/webui/services/test_document_ingestion.py`

**Step 1: Write the failing tests**

Cover:
- supported type classification for `doc/docx/xls/xlsx/ppt/pptx/ofd`
- parse result envelope shape
- OFD unsupported status path

**Step 2: Run tests to verify failure**

Run:
```bash
pytest tests/webui/services/test_document_ingestion.py -v
```
Expected: import/module failure.

**Step 3: Implement the minimal ingestion service**

Add:
- file type classifier
- result model/dict contract
- `markitdown` primary path
- LibreOffice conversion hook for legacy binary formats
- OFD unsupported status path

**Step 4: Re-run tests**

Run:
```bash
pytest tests/webui/services/test_document_ingestion.py -v
```
Expected: PASS.

**Step 5: Commit**

```bash
git add webui/services/document_ingestion.py tests/webui/services/test_document_ingestion.py
git commit -m "feat: add shared document ingestion service"
```

### Task 3: Extend upload API to return parse metadata

**Files:**
- Modify: `webui/api/routes/config.py`
- Modify: `webui/api/models.py`
- Test: `tests/webui/api/test_upload_document_parsing.py`

**Step 1: Write the failing API test**

Test that uploading a supported document returns fields like:
- `url`
- `filename`
- `local_path`
- `parse_status`
- `document_type`
- `parsed_text`
- `parsed_text_path`

**Step 2: Run the failing test**

Run:
```bash
pytest tests/webui/api/test_upload_document_parsing.py -v
```
Expected: response shape mismatch.

**Step 3: Implement the upload integration**

Update `/config/s3/upload` so local uploads:
- persist originals,
- invoke the ingestion service,
- persist parsed artifacts,
- return structured metadata.

For S3-backed uploads, decide whether parsing happens before or after object upload and keep original bytes available for parsing before return.

**Step 4: Re-run tests**

Run:
```bash
pytest tests/webui/api/test_upload_document_parsing.py -v
```
Expected: PASS.

**Step 5: Commit**

```bash
git add webui/api/routes/config.py webui/api/models.py tests/webui/api/test_upload_document_parsing.py
git commit -m "feat: parse uploaded documents automatically"
```

### Task 4: Update frontend attachment handling

**Files:**
- Modify: `web/src/hooks/useConfig.ts`
- Modify: `web/src/components/chat/ChatInput.tsx`
- Test: `web/src/components/chat/ChatInput.test.tsx` or equivalent lightweight test

**Step 1: Write the failing UI test or fixture check**

Cover:
- upload response accepts structured metadata
- document attachments inject parsed text into outgoing message
- image attachments keep existing markdown-image behavior

**Step 2: Run the failing test**

Run the project’s frontend test command if present; if absent, create the smallest reproducible assertion possible and use `npm run build` as a type/build guard.

**Step 3: Implement the minimal frontend change**

Change upload handling from `Promise<string>` to structured metadata. Update the send path:
- images stay URL-based,
- document attachments inject extracted text when available,
- failed parses degrade to attachment link plus status marker.

**Step 4: Verify**

Run:
```bash
cd web
npm run build
```
Expected: PASS.

**Step 5: Commit**

```bash
git add web/src/hooks/useConfig.ts web/src/components/chat/ChatInput.tsx
git commit -m "feat: inject parsed document content into chat attachments"
```

### Task 5: Add agent-facing document parsing tool

**Files:**
- Create: `webui/tools/document_parser.py` or equivalent tool module
- Modify: the runtime tool registration path used by this repo
- Test: `tests/webui/tools/test_document_parser.py`

**Step 1: Write the failing tool test**

Test that the tool can:
- parse a stored uploaded file,
- reuse cached parse artifacts when present,
- return explicit unsupported status for OFD.

**Step 2: Run the failing test**

```bash
pytest tests/webui/tools/test_document_parser.py -v
```

**Step 3: Implement the tool**

Wire the tool to the shared ingestion service. Keep it small; do not duplicate parsing logic.

**Step 4: Re-run tests**

```bash
pytest tests/webui/tools/test_document_parser.py -v
```

**Step 5: Commit**

```bash
git add webui/tools/document_parser.py tests/webui/tools/test_document_parser.py
git commit -m "feat: add runtime document parsing tool"
```

### Task 6: Add operational docs and skill guidance

**Files:**
- Modify: `deployment/custom-docker-deploy-zh.md`
- Create or update: local/runtime document-processing skill file if desired

**Step 1: Document supported formats and gaps**

Explicitly document:
- `doc/docx/xls/xlsx/ppt/pptx` support path
- OFD separate status
- multi-sheet Excel output behavior

**Step 2: Document size and fallback behavior**

Describe:
- automatic parse caps
- retry/tool usage
- expected runtime cost of LibreOffice

**Step 3: Verify docs are consistent**

Manual review plus one smoke run of the documented Docker flow.

**Step 4: Commit**

```bash
git add deployment/custom-docker-deploy-zh.md
git commit -m "docs: describe runtime document ingestion support"
```
