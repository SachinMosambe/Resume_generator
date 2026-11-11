# Task 5 report: Optional LLM structure repair

## Status
DONE. Committed on `main`. Flag `RESUME_LLM_PARSE_FALLBACK` defaults to False.

## Changes
- `services/llm_structure_repair.py` (new): `maybe_repair_parse(source_text, parsed, *, client=None)`.
  - Eligibility: (no roles and `has_work_history`) OR `confidence < 0.55` OR (empty-title ratio >= 0.5 with `source_backed_titles_unresolved`). No roles and no employment evidence (education-only) is never eligible. Already `llm_repaired` is never repeated.
  - One LLM call, no JSON/validation retry loops, wall-clock timeout (`RESUME_LLM_PARSE_TIMEOUT_SECONDS`, 45s). Default client reuses `app.agents.tools.llm_client.llm_call_json_with_metrics` (Bedrock); tests inject a stub `client(system, user)`.
  - Validation (all-or-nothing): pydantic schema; each company/title/location must normalize-match source; durations match as substring or all tokens present in source; every bullet must exist in source AND lie inside the source block of its assigned employer (wrong-employer rejection); existing deterministic roles, titles and bullets must survive. Any failure, timeout or client error returns the deterministic `parsed` object untouched.
  - On accept: only `experience` and leftover `unassigned_experience_bullets` change; `parse_meta` is re-scored and `llm_repaired=True` (plus `pre_repair_confidence`). No resume text is logged.
- `core/config.py`: `RESUME_LLM_PARSE_FALLBACK=False`, `RESUME_LLM_PARSE_TIMEOUT_SECONDS=45`.
- `services/resume_generation_service.py`: single call right after `parse_resume_detailed`, only when flag is True, wrapped in try/except. Also now carries `parse_meta` and `unassigned_experience_bullets` into the merged candidate data so the store/integrity (and `llm_repaired`) see them (previously dropped at top level).
- `tests/test_llm_structure_repair.py` (new): 16 tests, all LLM calls stubbed.

## Verification
- `pytest tests/test_llm_structure_repair.py`: 16 passed.
- Full backend suite: 179 passed, 1 skipped.
- Golden/scored CI never enables the flag; wiring tests assert the repair function is not called when off and called once when on.

## Concerns
- Carrying `parse_meta` into the merged data means output-integrity's experience-gap check now sees parse_meta in the normal generation path (it was effectively empty before). Suite still green, but it may add review warnings on real weak parses.
- Source-block association uses employer-name anchors: an employer name repeated inside another role's bullets can cause a safe false rejection, never a false accept.
- Dates are verified token-wise (not ordered/paired), so a swapped but source-present date range across roles is not caught.
- No live Bedrock call was run (stubs only).


## Fix round: tighten source checks (important findings)
Status: DONE. Flag `RESUME_LLM_PARSE_FALLBACK` still defaults to False.

- **Dates:** `_duration_in_source` now requires the duration's tokens to appear as one contiguous run in the source token stream (punctuation/dash style agnostic). Scattered tokens no longer pass, so an invented `2017 - Present` built from different roles' years is rejected. Empty duration is still allowed by validation but no longer wipes a deterministic duration (see merge).
- **Survival:** on accept, `_merge_roles` matches each repaired role to its deterministic role (company key, then title; repeated companies consumed in order) and keeps old fields when the repair omits/clears them. Verified deterministic `duration` and `location` are authoritative; repair only fills those fields when empty. `technologies` is no longer forced to `[]` when the original had values.
- **Role blocks:** company anchors now prefer job-header occurrences (non-bullet line that starts with the name, or has a date on the same/adjacent line) via a normalized-to-raw offset map. Mentions inside bullets neither start nor truncate a block; falls back to all occurrences when no header-like one exists. Bullets assigned under an employer only mentioned in another role's bullet are rejected.
- **Tests (+5, 21 total):** invented range from other roles' years; contiguous duration with different punctuation accepted; verified duration/location/technologies survive; company mentioned in another role's bullet does not split the block; bullet under a merely-mentioned employer rejected. 4 of the new tests fail on the previous implementation.
- **Verification:** `tests/test_llm_structure_repair.py` 21 passed; full backend suite (`backend/.venv`) 184 passed, 1 skipped.
- **Remaining limits:** durations are matched globally, not tied to the role's own header; header detection is heuristic (plain layouts fall back to all occurrences); a wrapped bullet continuation line starting with the company name could still look like a header.


## Fix round: preserve verified duration and location
Status: DONE.

- `_merge_roles` now treats a non-empty deterministic `duration` or `location` as authoritative. An accepted LLM repair may only fill either field when the matching deterministic role has it empty.
- Added a regression case where the repair proposes Beta LLC's source-backed duration and location for Acme Inc. The repair may still be accepted, but Acme's verified deterministic values remain unchanged.
- TDD verification: the new regression failed before the merge change (`2017 - 2019` replaced `2020 - Present`) and passed afterward.
- Verification: `pytest tests/test_llm_structure_repair.py -v` using `backend/.venv`: 22 passed.
