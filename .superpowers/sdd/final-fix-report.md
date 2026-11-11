# Final whole-branch review: Important fixes

## 1. Ambiguous fixtures
- `GOLDEN_STATUS_OK["needs_review"]` is now `{"needs_review"}`; a clean `passed` no longer satisfies it
  (the `allow_unassigned_bullets` special case is gone, the rule is uniform).
- `ambiguous_status_problems(manifest)`: fixtures whose id/pattern contains `ambiguous` or `empty_title`
  must declare `expected_status: needs_review`; `--golden` exits 2 otherwise.
- `golden_expectation_failures` now also asserts `expected_name` appears in the rendered DOCX.
- New parse-confidence reasons (`parse_confidence.score_parse`): `role_identity_garbled` (company is a
  date/date range, or equals the title) and `overlapping_role_dates` (one employer's range sits inside
  another's for >= 6 months). `ambiguous_role_assignment` now also fires when unassigned bullets sit next
  to parsed roles. Before this, `ambiguous_tech_token_name`, `ambiguous_overlapping_dates` and
  `empty_title_under_company` all came out `passed`.

## 2. Parse reasons surfaced (`output_integrity._parse_reason_findings`)
- `identity_ambiguous` -> blocking only if the rendered name is missing / a placeholder / not found in the source text.
- `source_backed_titles_unresolved` -> blocking only when `employment_evidence.has_work_history`.
- `role_identity_garbled`, `overlapping_role_dates` -> blocking.
- Messages carry counts/codes only, no resume text (test asserts this).

## 3. Bullet-only: rendered, not dead branch
- Parser keeps orphan bullets also when other roles parsed (previously dropped silently; this was the
  lost `monthly books` bullet in `ambiguous_role_headers`), de-duplicated against role bullets.
- `structured_resume_store.attach_unassigned_experience` adds a placeholder role
  (title "Role details need review", empty company/dates) to the Experience section (creates the section
  if absent). Wired in `ResumeGenerationService.generate` right after the document is built, so every
  renderer (schema DOCX, skeleton fill, PDF) gets it. Idempotent.
- Integrity: `experience_roles_unassigned` message now says bullets appear under that heading;
  `experience_bullets_unassigned` (roles + unassigned) is blocking; `unassigned_bullets_missing` fires if
  they are not actually in the DOCX.

## 4. CI / docs
- `ci.yml` backend job: `pip install -r requirements.txt pytest`, then `pytest -q` (LLM env flags off). Golden job unchanged.
- README: 422 list now mentions unconvertible `.doc` and quarantined non-resume uploads; `needs_review` row lists the new reasons.

## Verification
- Before: golden subset of 6 ambiguous/bullet-only fixtures failed (9/18); HEAD bullet-only fixtures lost bullets in DOCX.
- After: full golden `--golden --formats aptino,capgemini,suresh`: 40 fixtures / 120 runs, passed_pct 120/120, exit 0.
- Focused tests: 88 passed. Full `backend/.venv` pytest: 266 passed, 1 skipped (tesseract-gated).

## Remaining concerns
- `overlapping_role_dates` is a heuristic (containment >= 6 months across different employers); legitimate
  concurrent contracts will get a review flag. Tune or downgrade to info if the private corpus shows noise.
- CI pytest not yet run on Linux runner (no tesseract/libreoffice in the backend job; tests that need them skip or mock).
- Golden is not a required check (branch-protection setting, not YAML).
- The tracked `test/format/Capgemini-Format.doc` predates this work and is real-template content; untouched.
