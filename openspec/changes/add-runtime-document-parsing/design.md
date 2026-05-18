## Context

Today the chat attachment flow uploads a file and returns a URL. The frontend then appends the URL into the outgoing message, which means the model can only act on the attachment if the provider itself can fetch and interpret that URL. This is unreliable for internal deployments and does not satisfy the requirement that the running nanobot instance should be able to process office documents itself.

The required behavior is broader:
- Office attachments should be parsed automatically after upload, with the parsed text made available to the first model turn.
- The agent should still have a runtime tool to re-parse or inspect a stored file on demand.
- `doc/docx/xls/xlsx/ppt/pptx` should use a common runtime stack.
- `ofd` is not part of this phase and must be reported as unsupported.

## Goals / Non-Goals

**Goals:**
- Support runtime parsing for `doc`, `docx`, `xls`, `xlsx`, `ppt`, and `pptx`.
- Prefer automatic parsing immediately after upload.
- Keep an explicit runtime tool for on-demand parsing.
- Preserve uploaded originals and cache parsed results on disk.

**Non-Goals:**
- Full WYSIWYG fidelity for Office layouts.
- Editing Office documents in place.
- `ofd` parsing in this phase.
- Shipping the full MiniMax `.docx` authoring pipeline into this runtime service.

## Decisions

### 1. Use `markitdown` as the primary extractor and LibreOffice as a conversion fallback

`markitdown` will be the first parser because it gives one normalized output format for text-heavy ingestion. `libreoffice` will be installed in the runtime image to convert legacy Office binaries and to improve fallback coverage for documents that `markitdown` cannot parse directly.

Why:
- One normalized extraction surface is better than format-specific prompt hacks.
- LibreOffice is valuable as a converter, not as the sole ingestion strategy.
- This aligns with the runtime requirement inside the container.

### 2. Parse on upload and store a cached extraction beside the original

When a supported document is uploaded, the backend will:
1. persist the original file,
2. attempt extraction,
3. store a parsed markdown/text artifact,
4. return both the file URL/path and parse metadata to the frontend.

Why:
- The first model turn can use extracted text immediately.
- Later tool calls can reuse cached content instead of re-running conversion every time.
- Failures can be surfaced explicitly.

### 3. Keep a runtime document parsing tool for retries and late binding

Automatic parsing covers the normal path, but the agent still needs a tool to:
- retry a failed parse,
- re-read a large document in a narrower way,
- parse a file that was uploaded earlier.

Why:
- Automatic ingestion alone is brittle.
- This satisfies the “两者都要，优先自动解析” requirement without duplicating logic.

### 4. Model the frontend attachment payload as structured metadata, not only a URL

The upload response should include fields like:
- `url`
- `filename`
- `local_path`
- `parsed_text_path`
- `parsed_markdown`
- `parse_status`
- `document_type`

The chat composer can then inject extracted text when available instead of only appending a markdown link.

Why:
- The current “append raw URL” strategy is too weak.
- Structured metadata lets us distinguish images from documents and success from fallback.

### 5. Report OFD explicitly as unsupported

This phase should not attempt to parse `ofd`. The ingestion service should classify it and return an explicit unsupported status instead of routing it into the Office conversion path.

Why:
- LibreOffice coverage for OFD is not reliable enough to use as a runtime assumption.
- Explicit failure is safer than fake support.

## Risks / Trade-offs

- [Runtime image size increases] → Mitigation: install only the LibreOffice packages required for headless conversion and document the size trade-off.
- [Old binary formats are slower and less reliable] → Mitigation: convert `doc/xls/ppt` through LibreOffice before extraction and surface parse failures explicitly.
- [Large Excel workbooks can explode in size] → Mitigation: emit sheet-delimited output and cap sheet/row extraction in the parser layer.
- [Automatic extraction can pollute prompts] → Mitigation: enforce size caps and fall back to “document attached, parse on demand” when the extracted content is too large.
- [OFD remains unsupported] → Mitigation: report unsupported status clearly instead of silently failing.

## MiniMax Skill Assessment

The MiniMax `minimax-docx` skill is useful as a workflow reference for structured DOCX handling, but it is not a fit for this runtime ingestion problem:
- it is DOCX-specific,
- it is focused on document generation/editing with OpenXML SDK (.NET),
- it explicitly converts `.doc` into `.docx` first,
- it does not solve `xlsx`, `pptx`, or `ofd`.

We should borrow the discipline of explicit pipelines and validation, but not the implementation stack.

## Migration Plan

1. Add an openspec change and implementation plan.
2. Add runtime dependencies (`markitdown`, `libreoffice`) to the container and Python environment.
3. Introduce a document ingestion service with per-format adapters.
4. Extend upload responses with parse metadata and persist parsed artifacts.
5. Update the chat composer to prefer extracted text for document attachments.
6. Add a runtime document parsing tool that reuses the same ingestion service.
7. Return explicit unsupported status for OFD.
