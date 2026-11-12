# Integrity Task 3 Report

## Status

Implemented and verified the first-pass line-extraction recovery behavior: when the rule parser finds zero roles, a non-empty, non-lumped LLM result is accepted even when the normal coverage gate is weak.

## Changes

- Kept lumped-result rejection intact.
- Added the empty-rule-role override to the `better` decision without changing comparisons for non-empty rule parses.
- Added a regression test with 0.5 rule/LLM coverage, a non-lumped incomplete grounded role, and a failed normal gate.

## TDD Evidence

- Red: the new regression test failed with `used` equal to `False` when the empty-rule override was absent; 17 passed, 1 failed.
- Green: `tests/test_llm_line_extractor.py -v` completed with 18 passed.
- IDE diagnostics reported no linter errors in the two scoped Python files.

## Concerns

The requested command path and test path assume different working directories. Verification used the specified virtual environment from the `backend` directory as `.venv\Scripts\python.exe -m pytest tests/test_llm_line_extractor.py -v`.
