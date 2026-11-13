# Safe zero-role edge wave report

Status: DONE (all 3 patterns shipped; full pytest and golden exit 0)

## Commits
- 91a2963 feat: parse letter-spaced employment dates
- c1c612e feat: recover Role/Company blocks without dates
- (HEAD) feat: recover portfolio engagement work history

## Patterns
1. Letter-spaced dates: `_collapse_letter_spaced_dates` in `_prepare_resume_text`. It collapses only full month/year or year ranges
   (e.g. `A U G U S T 2 0 2 3 - P R E S E N T`). Prose such as "A B C rollout" is untouched. `output_integrity._SOURCE_DATE`
   now treats letter-spaced date lines like other dated headers, so the source-lines check does not false-flag them.
2. Role:/Company:/Client: without dates: `_parse_labeled_role_block(allow_undated=True)`. Only inside a chosen experience
   section, only with explicit `Label:` colons. Needs Role + Company/Client, or one label followed by a bullet. Duration stays "".
3. Portfolio engagements: bare client line above `Role:` is read as company. Alternate headings (now also `Clients`) are
   accepted without dates only when every entry has a company and a labelled title. Otherwise the section is not job history.

## Tests
- Recovery tests: 42 in test_corpus_parse_recovery.py (13 new: positive and negative guards).
- Full `pytest tests -q`: 298 passed, 1 skipped.
- Golden `--formats aptino,capgemini,suresh`: GOLDEN PASS exit 0, 50 scored fixtures x 3 = 150/150 passed,
  zero_role 0/43 (0%). Three new scored fixtures: letter_spaced_dates_roles, role_label_no_dates_blocks, portfolio_clients_role_labels.

## Skipped
- Optional offline corpus zero-role compare: not run (no sanitized corpus used; real resumes contain PII).