# Task 1 Report: Source employment evidence

## Status

Completed Steps 1–5 using test-driven development.

Commit: `441c08a feat: detect source employment evidence independent of parse`

## Changes

- Added `backend/tests/test_source_evidence.py` using the three existing synthetic golden text fixtures.
- Added `backend/app/services/source_evidence.py`.
- Implemented `EmploymentEvidence` and `detect_employment_evidence(source_text)`.
- Evidence references contain only opaque zero-based line indexes, capped at 20.
- The implementation does not log resume text or evidence content.

## TDD evidence

1. Added the requested tests before production code.
2. Initial test execution failed during test setup because repository dependencies were missing.
3. Installed the declared backend requirements and implemented the minimal detector from the brief.
4. Final command:
   `PYTHONPATH=backend py -3.12 -m pytest backend/tests/test_source_evidence.py -v`
5. Result: `2 passed in 0.02s`.

## Concerns

- The exact brief command requires `backend` on `PYTHONPATH` in this Windows environment.
- The initial red run was blocked by missing test-environment dependencies before collection reached the expected missing detector module.

## Important quality finding fix

- Tightened `_EXP_HEAD` to accept only complete headings: Experience, Work History, Employment History, Job History, and Professional Experience.
- Added a regression test proving Dice-style `Employment Type` metadata plus an education year does not imply work history.
- Red: `1 failed, 2 passed` before the regex fix.
- Green: `3 passed in 0.02s` after the fix; existing Dice, bullet-only, and education-only coverage remains green.
