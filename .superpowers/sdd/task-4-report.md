# Task 4 report: Intake — OCR, legacy DOC, quarantine

## Status
DONE (with concerns below). Committed on `main`.

## Changes
- `services/pdf_ocr.py`: `OcrUnavailableError` now carries `.pages`; new `format_page_refs()` (1-based, "page 2", "pages 1-2 and 5").
- `services/pdf_parser.py`: `extraction_meta` gains `doc_converted`; `.doc` branch sets it and cleans up the temp conversion dir; whole-scan failure raises only when OCR recovered nothing (partial recovery proceeds and reports `ocr_missing_pages`); error carries unread pages. OCR merge already ran in source page order; `ocr_pages` (recovered) and `ocr_missing_pages` (unreadable) stay separate.
- `services/doc_converter.py`: user-facing failure message no longer leaks converter logs (detail stays in server logs); both messages tell the user to re-save as `.docx`.
- `services/intake_gate.py` (new, not in brief's file list): `assess_resume_intake(text)` quarantine heuristic.
- `services/output_integrity.py`: unread / OCR'd pages now named ("page 2"); message prefix unchanged.
- `api/routes/generate.py`: 422 for OCR-unavailable (names pages), `.doc` conversion failure (`DocConversionError` previously fell into the generic message), and non-resume quarantine (also sets `extraction_meta["quarantine_reason"]`).
- `tests/test_intake_gate.py` (new): 28 tests.

## Quarantine heuristic
Quarantine only if BOTH: (a) a non-resume marker (certificate, I-94/travel record, invoice/pay stub/bank statement) appears in the first 8 lines or hits >= 2 times, AND (b) fewer than 2 resume-structure signals (distinct section headings, date range, email/phone, >= 2 bullets). No markers => always passes, so sparse, education-only and skills-only resumes are safe. A real resume that mentions "I-94" or lists a certificate has >= 2 signals and passes.

## Verification
- `backend/.venv/Scripts/python.exe -m pytest tests/test_intake_gate.py -v`: 28 passed.
- Full backend suite: 163 passed, 1 skipped (real-Tesseract test).
- Ran the gate over 72 real files from `test/resume` and `Sachin resume AI` (sampled): 0 false quarantines.
- Every golden resume case passes the gate; both `non_resume_*` stubs are quarantined.

## Concerns
- Tesseract and LibreOffice are NOT installed here; OCR/DOC success and failure paths are monkeypatched. The "scored OCR/DOC fixtures >= 90% with dependencies enabled" exit check was not run. Golden scanned/mixed/legacy_doc binary builders in `build_golden_fixtures.py` are still `NotImplementedError` stubs (outside this task's file list).
- Real scanned I-94 / travel-history PDFs in the corpus hit the OCR-unavailable 422 (scan, no text) rather than the quarantine gate when OCR is off; with OCR on they'd reach the gate.
- Error `detail` strings changed slightly for `.doc` failures and OCR-unavailable (still contains "scanned").
- CI/runtime docs for installing Tesseract were not updated.
