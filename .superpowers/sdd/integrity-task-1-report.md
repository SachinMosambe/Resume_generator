# Task 1 Report: List Missing Hard Source Lines

## Status

DONE

## TDD evidence

- RED: Added the brief's exact test and ran it in the backend virtual environment. It failed with `ImportError: cannot import name 'list_missing_hard_source_lines'`.
- GREEN: Implemented the helper and reran the focused test. Result: `1 passed`.
- Regression: Ran `tests/test_output_integrity.py`. Result: `31 passed, 1 warning` (the warning is an existing PyMuPDF deprecation warning).
- Lint: No diagnostics in either changed task file.

## Files changed

- `backend/app/services/output_integrity.py`
  - Added shared source-line classification output while preserving the existing hard/soft/changed thresholds.
  - Added shared fact collection used by both the integrity check and the new public helper.
  - Added `list_missing_hard_source_lines`, returning ordered unique stripped raw hard-missing lines.
- `backend/tests/test_output_integrity.py`
  - Added the exact focused test from the task brief.

## Self-review

- The helper normalizes plain output text using the same normalization used by DOCX integrity checks.
- Hard-line decisions remain centralized and use the existing skip, date, minimum-word, minimum-share, metric, bullet, and parsed-fact rules unchanged.
- De-duplication preserves first-seen source order.
- The task commit contains only the two authorized task files; unrelated staged and working-tree changes were preserved outside it. This report remains an execution artifact outside that commit.
