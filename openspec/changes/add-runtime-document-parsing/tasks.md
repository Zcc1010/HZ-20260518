## 1. Runtime dependencies

- [ ] 1.1 Add `markitdown` to the Python dependency/runtime path
- [ ] 1.2 Install headless `libreoffice` packages in the Docker runtime image
- [ ] 1.3 Document the runtime size/capability trade-offs

## 2. Upload-time parsing

- [ ] 2.1 Add a document ingestion service that classifies attachment types
- [ ] 2.2 Parse `doc/docx/xls/xlsx/ppt/pptx` automatically after upload
- [ ] 2.3 Persist parse artifacts and return structured upload metadata
- [ ] 2.4 Return explicit unsupported status for OFD uploads

## 3. Chat integration

- [ ] 3.1 Update frontend upload handling to keep parse metadata, not only the URL
- [ ] 3.2 Update chat message assembly to inject extracted text when available
- [ ] 3.3 Define size/failure fallback behavior for large or unparsed documents

## 4. Runtime tool support

- [ ] 4.1 Add an agent-facing document parsing tool that reuses the ingestion service
- [ ] 4.2 Support re-parse or delayed parse of stored uploaded files

## 5. Verification

- [ ] 5.1 Verify JSON/API contracts and frontend build
- [ ] 5.2 Smoke-test upload parsing for docx/xlsx/pptx and one legacy binary format
- [ ] 5.3 Record OFD as unsupported explicitly
