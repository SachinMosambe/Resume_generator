# Task 4 report: integrity recovery module

**Status:** DONE_WITH_CONCERNS (minor, see below)
**Commit:** `6ab6967` feat: add grounded integrity recovery helpers (only `backend/app/services/integrity_recovery.py`, `backend/tests/test_integrity_recovery.py`)
**Tests:** `tests/test_integrity_recovery.py` 14 passed; with `test_llm_line_extractor.py` + `test_output_integrity.py` 63 passed.

## Implemented
- `recovery_enabled`, `hard_source_miss_count`, `has_wrong_role`, `should_recover`, `prefer_recovered` per brief.
- `recover_store(source_text, store, report, output_text="", *, client=None) -> (store, meta)`:
  - missing hard lines via `list_missing_hard_source_lines` (against `output_text`, or the store's own text if empty) -> 1-based line hints.
  - `extract_experience` run through a budget wrapper (`RESUME_INTEGRITY_RECOVERY_MAX_CALLS` cap, `..._TIMEOUT_SECONDS` deadline + future timeout).
  - aborts on lumped result (`error="lumped"`), no roles, or no improvement; returns the same `store` object unchanged in those cases and on any exception.
  - merge replaces `experience` with grounded roles (carries `technologies` for matching company+title) and sets `unassigned_experience_bullets`; swapped only if estimated hard misses strictly drop.
  - meta: `used, llm_calls, error, missing_in, missing_out_estimate, llm_roles, elapsed_ms`.
- No text is generated; all text comes from the extractor's source-verified output. Thresholds and `ResumeGenerationService` untouched.

## Concerns
- `output_text` is the 4th param with default `""` (brief showed it required; default keeps the brief's 3-arg test form working). Task 5 should pass the real DOCX text.
- `missing_out_estimate` is estimated from store text, not a re-rendered DOCX; the caller must still re-run integrity and use `prefer_recovered`.
- Timeout cannot kill an in-flight Bedrock call (thread abandoned; no further calls are allowed after deadline).
- Uses private helpers from `llm_line_extractor` (`_default_client`, `_is_lumped`, `_key`).
- Tests were written first but the red run was not captured separately (module absence = import failure); all pass now.
- Worktree contains many unrelated uncommitted changes; they were left alone.


## Review fix pass (Important findings)

- Wrong-role / zero-role-with-work-evidence: candidate accepted (used=True) without requiring `after < before`; Task 5 `prefer_recovered` decides post-render. source_lines-only path still requires the hard-line drop.
- Any `result.error`, empty roles, or lumped result -> original store, used=False (no partial chunk acceptance).
- Company preservation: when prior store had roles, every prior company (lle._key) must appear in recovered roles, else used=False, error `dropped_company`. Zero-role prior store skips the check.
- Timeout/exception paths now set `llm_calls` from the budget; `missing_out_estimate` defaults to None (only set once actually computed).
- Tests added: wrong-role path used=True; errored extract used=False; dropped-company used=False; timeout meta (estimate None).
- Result: `cd backend; .venv\Scripts\python.exe -m pytest tests/test_integrity_recovery.py -v` -> 18 passed.
