## Why

The current attachment flow only uploads files and appends their URLs into the chat message. This is not enough for internal deployments that expect the running agent to actually read Office documents at runtime. We need a first-class document ingestion path for common Office formats and a clear fallback path for legacy and unsupported formats.

## What Changes

- Add runtime document parsing for uploaded office files with automatic extraction as the first path.
- Install `markitdown` and `libreoffice` in the runtime container so uploaded Office documents can be converted and parsed inside the running WebUI service.
- Add an agent-facing document parsing tool so parsing can be retried or triggered on demand when automatic extraction is missing or insufficient.
- Keep `ofd` explicitly out of scope for this phase and report it as unsupported.

## Capabilities

### New Capabilities
- `document-auto-ingestion`: Parse uploaded office documents into markdown/text automatically before the model sees them.
- `document-tool-parse`: Allow the running agent to explicitly re-parse a stored document during a conversation.

### Modified Capabilities
- `attachment-upload`: Extend upload results with parse metadata instead of returning only a raw URL.

## Impact

- Affected backend code: `webui/api/routes/config.py`, upload helpers, new document parsing service/tool module(s), and possibly chat request assembly where attachment payloads are composed.
- Affected frontend code: attachment upload handling in `web/src/hooks/useConfig.ts` and `web/src/components/chat/ChatInput.tsx`.
- Affected deployment: runtime image gains `libreoffice`; Python dependencies gain `markitdown`.
- `ofd` remains unsupported in this phase and is documented as a gap rather than being silently attempted.
