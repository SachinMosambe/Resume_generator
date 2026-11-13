### Task 4: Intake — OCR, legacy DOC, quarantine (Wave C)

**Files:**
- Modify: `backend/app/services/pdf_parser.py`, `pdf_ocr.py`, `doc_converter.py`
- Modify: `backend/app/api/routes/generate.py` (422 messages)
- Create: `backend/tests/test_intake_gate.py`
- Extend golden fixtures: scanned stub, mixed PDF, `.doc`, non-resume, sparse valid resume

**Interfaces:**
- `extraction_meta`: keep `ocr_pages`; ensure `ocr_missing_pages`, `doc_converted`, optional `quarantine_reason`
- Human-readable page refs in warnings (1-based)

- [ ] **Step 1: Failing intake tests**

```python
def test_ocr_unavailable_whole_scan_returns_clear_error(monkeypatch):
    # simulate image-only PDF + ocr_available False → 422 path / OcrUnavailableError
    ...

def test_mixed_pdf_partial_draft_marks_missing_pages():
    meta = {"ocr_pages": [1], "ocr_missing_pages": [2]}
    # integrity info/blocking per Wave B rules
    ...

def test_doc_missing_libreoffice_422(monkeypatch):
    ...

def test_non_resume_quarantine_422():
    ...

def test_sparse_valid_resume_not_quarantined():
    ...
```

- [ ] **Step 2: Implement / verify OCR merge in page order**

Reuse `pdf_ocr.py`. Merge readable + OCR text in source order. Track recovered vs still-unreadable pages separately. Confirm Tesseract present in runtime docs / CI image for golden OCR fixtures.

- [ ] **Step 3: Legacy `.doc`**

`doc_converter.py`: convert via LibreOffice; on failure → HTTP 422 suggesting `.docx` upload.

- [ ] **Step 4: Non-resume quarantine**

Heuristic gate (certificates, I-94, travel history) → 422 with actionable reason. Must not reject education-only or sparse but valid resumes.

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/test_intake_gate.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pdf_parser.py backend/app/services/pdf_ocr.py backend/app/services/doc_converter.py backend/app/api/routes/generate.py backend/tests/test_intake_gate.py
git commit -m "feat: harden intake for OCR, legacy DOC, and non-resume rejection"
```

**Exit check:** Image-only and mixed PDF exercise success + partial/unavailable paths. `.doc` exercises convert + missing-converter. Scored OCR/DOC fixtures ≥90% with dependencies enabled.

---

