# Task 5 report: wire recovery into ResumeGenerationService.generate

Status: DONE

## Changes
- `backend/app/services/resume_generation_service.py` (+73/-1): import `integrity_recovery`; new `_maybe_integrity_recover(...)`; `generate()` now calls it right after the first `_integrity_report` and sets `self.last_report` from the chosen draft.
- `backend/tests/test_integrity_recovery.py` (+154): 6 wiring tests.

## Behavior
`_maybe_integrity_recover(candidate, client_format, store, detailed_data, document, format_metadata, header_logos, footer_logos, docx_bytes, report) -> (docx_bytes, report, store, document)`
- If `report` exists and `should_recover`: `recover_store(source_text, store, report, <docx text>)`.
- If `meta.used`: rebuild via `apply_store_to_candidate_data` -> `_generate_professional_document` -> `attach_unassigned_experience`, carry over footer/header branding keys, run format validation (critical findings => abort recovery), re-render ONCE, second `_integrity_report`, `prefer_recovered` decides. If preferred, store/docx/report/document swap and `candidate.extracted_data["structured_resume"]` is updated.
- `store.parse_meta.integrity_recovery` is always recorded (`{"used": False}` when not attempted; `preferred`/`error` otherwise).
- Whole block wrapped in try/except: recovery failure never raises; first draft is kept.

## Tests
- TDD: tests written first (failed on missing method), then implemented.
- `tests/test_integrity_recovery.py + test_llm_line_extractor.py + test_output_integrity.py`: 73 passed. Full backend suite: 368 passed, 1 skipped.

## Concerns
- The working tree copy of `resume_generation_service.py` had large pre-existing uncommitted changes from other work. To avoid committing them, only my hunks were staged (HEAD + my edits) and committed; the other changes remain uncommitted in the working tree.
- Not covered by an end-to-end `generate()` test (stubbed helper-level tests); `_generate_professional_document` rebuilds its store internally from `candidate_data`, so recovered roles flow through that path as in the first render.
