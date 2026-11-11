# Task 3 Report: Source-aware DOCX verification

## Status
DONE_WITH_CONCERNS (see concerns).

## What changed
- `output_integrity.py`
  - `IntegrityReport.warnings` is now `list[{severity, code, message}]`; `warning_payload(report, limit=10)` wraps any legacy string as `{severity, code:"legacy", message}`.
  - New kwargs: `parse_meta`, `verify_role_assignment=True` (falls back to `store["parse_meta"]`).
  - Source-line classification: `hard` (missing line carrying employer/title/bullet text or a %/$ figure) -> blocking `source_lines`; `soft` (reflow/reword) -> info `source_lines_soft`; `changed` (line present but %/$ figure absent) -> blocking `source_numbers`. `checks["source_lines"]` = `{ok, expected, found(hard+soft+changed), hard, soft, changed_numbers}`; `ok` ignores soft.
  - Employment evidence: `has_work_history` + zero roles + no preserved `unassigned_experience_bullets` in output -> blocking `expected_experience_missing`. If unassigned bullets are preserved -> info `experience_roles_unassigned`.
  - Role-scoped bullets: heading = company+title found within 200 normalized chars; bullet found only in another located role's span -> blocking `bullet_wrong_role` and status `failed`. Skipped with <2 located headings, duplicate anchors, bullets <4 words.
  - `_docx_text` now reads body in document order (paragraphs and tables interleaved) so positions are meaningful.
  - OCR-used, suppressed sections -> info only; unread pages remain blocking.
  - Status: wrong assignment or core-field ratio < 0.5 -> `failed`; any blocking -> `needs_review`; else `passed`.
- `resume_generation_service._integrity_report`: passes `parse_meta` (store, else candidate).
- `generate.py`: `X-Review-Warnings` = `quote(json.dumps(warning_payload(report)))` (objects, max 10).
- `frontend/src/app/page.tsx`: accepts string or object warnings; blocking shown bold, info shown as muted "Note:" lines.
- `corpus_quality_eval.py`: per-format `raw_line_cov` (diagnostic) and `integrity_source_lines` labelled separately in JSON and MD; warnings stored as messages plus `warnings_structured`.
- Tests: updated `test_source_line_missing_from_output_needs_review` -> `test_source_lines_alone_do_not_force_needs_review` (semantics intentionally changed); added tests for fact-bearing missing line, changed number, OCR info, zero-roles evidence (4 cases), wrong-employer bullet (fail), correct assignment, disable flag, `warning_payload`.

## Verification
- `backend\.venv\Scripts\python.exe -m pytest tests -q` -> 133 passed, 1 skipped.
- `tests/test_output_integrity.py` -> 21 passed.
- Frontend `npx tsc --noEmit` clean. `eslint src/app/page.tsx` has 1 pre-existing error (`set-state-in-effect` at `loadFormats`), not from this change.
- No component test harness; UI paths verified by type check only (info-only/needs_review/failed rendering not exercised in browser).

## Concerns
1. Tests were written before the implementation but I did not capture a separate red run.
2. Wrong-assignment => `failed` is strict; heading detection relies on company+title proximity and could misfire on unusual templates (guarded by skip rules). Worth watching in the corpus eval.
3. "Approved label remaps" input does not exist in the codebase, so not wired.
4. `source_numbers` only checks %/$ figures (not bare integers) to limit false positives.
5. Zero roles + preserved unassigned bullets passes (info) per brief step 4; arguably still deserves review.
6. `corpus_quality_eval.py` was untracked and is committed for the first time here. Corpus eval not re-run.

## Review fix round (Important findings)
- **Zero roles + evidence + preserved unassigned bullets** now yields blocking `experience_roles_unassigned` -> status `needs_review` (was info/`passed`). `expected_experience_missing` remains for the unpreserved case. Test renamed `test_zero_roles_with_preserved_unassigned_bullets_needs_review`; concern 5 above is resolved.
- **Header compatibility:** `X-Review-Warnings` is again a URL-quoted JSON list of message strings (blocking first, max 10). New additive `X-Review-Warning-Details` = URL-quoted JSON list of `{severity, code, message}` (blocking first, max 10). Both exposed via CORS in `app/main.py` (`expose_headers`). Frontend `parseReview` prefers Details, falls back to `X-Review-Warnings` strings.
- **Truncation:** `warning_payload` stable-sorts blocking first before capping at 10; new `warning_messages` shares that selection so info can never push blocking out.
- Tests added: blocking-survives-truncation, legacy-strings-vs-details headers + CORS expose. (`tests/test_resume_api.py` does not exist; header tests live in `tests/test_output_integrity.py`.)
- Verification: full backend suite 135 passed, 1 skipped; `tests/test_output_integrity.py` all passed; frontend `npx tsc --noEmit` clean.
