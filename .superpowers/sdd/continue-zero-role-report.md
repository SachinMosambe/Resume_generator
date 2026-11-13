# Continue zero-role recovery report

Status: DONE (3 patterns shipped; full pytest and golden exit 0)

## Commits
- a49e685 feat: read Role/Project labels under company+date headers
- 7de57a8 feat: recover dates-first company/title layouts
- (HEAD) feat: recover separator and plain-line Work History lists

## Patterns
1. Company + date header, then `Role:`/`Project:` lines (`_consume_header_labels`). Probe showed 2 roles but the title was
   polluted as "Role: ..." and the project was lost. Only colon labels, consecutive lines; the title fills only an empty
   header title, project only when empty. Real header titles are never replaced.
2. Dates-first (`_merge_dates_first_headers`, runs before `_merge_date_only_headers`). Applies only when the section's first
   content line is a date-only line. A date merges with exactly two following header lines where exactly one is a title.
   Before: company was empty. Company-first layouts are untouched (guard test: no cross-pairing of dates).
3. Dice/Work History lists (`_split_on_explicit_separator`, plain-line fallback). Handles `Title - Employer`, `Title at Employer`,
   `Employer | Title`; exactly one side may hold a title word. Un-bulleted `Title Employer` lines are read only when every
   line splits cleanly (prose or any leftover keeps the section unparsed).

## Tests
- 12 new recovery tests (positive and negative guards) in test_corpus_parse_recovery.py.
- Full `pytest tests -q`: 307 passed, 1 skipped.
- Golden `--formats aptino,capgemini,suresh`: GOLDEN PASS exit 0, 162/162 passed (54 scored fixtures x 3; 4 new).

## Remaining / not done
- `Title, Employer` comma lists (ambiguous with `Director, Customer Success`), `Title:` label under dated header with company
  line (`Title:` is not a recognised label in the labeled-block path), dates-first with the title trailing the bullets.
- Single text line after a date-only line (company or title) keeps the old lookahead heuristic.
- Offline real-corpus compare not run (PII).

