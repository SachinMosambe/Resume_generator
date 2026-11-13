# Task 2 report: Deterministic parse recovery (Wave A)

Commit: see `git log -1` ("feat: recover Dice, split-header, and bullet-only experience in faithful parse").
Tests: `backend\.venv\Scripts\python.exe -m pytest tests -q` -> 119 passed, 1 skipped (full backend suite). Targeted: corpus recovery + parse_confidence + test_resume_reading all green.
Note: system python lacks `pymupdf`; use `backend/.venv`.

## Changes
- `detailed_resume_parser.py`
  - `_extract_experience` is now a thin wrapper over `_extract_experience_detailed` -> `(roles, orphan_bullets)`; existing loop untouched except additions below.
  - `_PAREN_TITLE` + lookahead: `Company` line (blank lines allowed) then `(Title) 03/19 - Present` creates a role (title, company, duration); following bullets attach by the existing loop. Existing `_DATE_PATTERN` was deliberately NOT widened (2-digit-year numerics would risk false positives).
  - `Company — Title — Dates` on one line: `_parse_job_header_line` now splits `Company — <role-word title>` (title must be role-word, company must not be, <=6 words).
  - Orphan bullets: bullets inside an Experience section before any role header, and bullets under date-only headers (no employer/title; previously silently dropped by `_save_current`), are collected.
  - `parse_resume_detailed`: when no roles and `detect_employment_evidence(...).has_work_history`, sets `unassigned_experience_bullets`; always sets `parse_meta` via `score_parse`.
  - Name guard: `_looks_like_tech_label` (all words in a tech-token set, e.g. "React Native.") rejected in `_person_name_line` and the fallback loop of `_extract_name`.
- `parse_confidence.py`: `score_parse` as specified (verbatim logic; `_TECH_NAMES` constant).
- `structured_resume_store.py`: store carries `parse_meta` and `unassigned_experience_bullets`; `apply_store_to_candidate_data` merges them back. Unassigned bullets are never turned into a role.
- Tests: `test_corpus_parse_recovery.py` (9), `test_parse_confidence.py` (6).

## Step 3 (Dice boundary)
Golden `dice_wrapper.txt` already recovered Amazon role + onboarding bullet with the existing `_strip_profile_cover`/`_DICE_NOISE_RE`; no boundary change was needed (no noise-stripping broadened). Added only parse_meta.

## Fixture / assertion calibration
- Brief's `bullet_only` assertion looked for "delivered"/"built", absent from the fixture; changed to the fixture's own text ("onboarding checklist", "weekly finance close"). Fixtures unchanged.
- Brief's paren_title assertions were loose; tightened to exact title "Platform Engineer" / company "Northwind".
- Education-only: `expected_experience_missing` not raised (no evidence).

## Concerns
1. Remaining zero-role goldens (bullets preserved/flagged, not recovered): `ambiguous_headers` (`Litware Analyst Dallas` no-separator header), `title_only` (title line + bullet, no employer/dates), `legacy_doc_contract` (`Title | Company — 03/20 - 11/20`, 2-digit-year dates; manifest scored:false). Outside Task 2 brief; a later task can widen date support carefully.
2. `detailed_resume_parser.py` (~2700 lines) is tangled: `_extract_experience` is a ~350-line state machine with many order-dependent branches; edits were kept additive.
3. `_extract_location` can return skill text ("React Native, Python") from a skills line; not addressed.
4. Tech-token name guard could reject a real person named e.g. "Spring Boot" (all-tech-token names only).
5. Zero-role metric on Wave A fixtures (dice, paren, bullet-only): bullet_only still 0 roles by design (no employer to attach to) but surfaced via `unassigned_experience_bullets` + `ambiguous_role_assignment`.

## Fix: title-only experience roles (Important finding)
Commit: `fix: recover title-only experience roles under Experience heading`
- `detailed_resume_parser.py`: new `_is_title_only_header`; in the experience loop, when no role is open, a short job-title line (<=6 words, <=60 chars, capitalised, contains a role word, no digits/dates/trailing punctuation, not an action-verb sentence, not a section heading/caps label) whose next non-blank line is a bullet starts a role with that title. Company stays empty (never invented); following bullets attach via the existing loop.
- Tests added in `test_corpus_parse_recovery.py`: `test_title_only_experience_role_recovered` (golden `title_only.txt`: title "Product Designer", empty company, "settings screens" bullet preserved, no unassigned bullets), `test_title_only_requires_following_bullet` and `test_sentence_line_before_bullets_is_not_a_title` (false-positive guards). Red before the change (1 failed, 11 passed), green after.
- Evidence: `pytest tests/test_corpus_parse_recovery.py tests/test_resume_reading.py` -> 43 passed; full `pytest tests -q` -> 122 passed, 1 skipped. `bullet_only` / `bullet_only_dated` still 0 roles by design.
- Not recovered: `ambiguous_headers` (`Litware Analyst Dallas`) needs splitting company/title/location without separators; doing so would risk inventing an employer. A second title-only role after bullets of an earlier role is still folded into the previous role's bullets (only the first/opening title-only role is recognised).
