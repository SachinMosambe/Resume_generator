# Continue zero-role recovery 2 report

Status: DONE (2 patterns shipped, one commit each; full pytest and golden exit 0)

## Commits
- 3770b69 feat: read Title: labels under dated company headers
- (HEAD) feat: read single company line after date in dates-first layouts

## Patterns
1. `Title:` label under a dated company header. Probing showed the direct case (`Company  date` then `Title: X`) already
   worked. Two variants still left "Title: X" polluting the title:
   - `Company  date` / location crumb / `Title: X`: the lookahead now reads a title label (`_title_label_value`) and strips it.
   - `Company` / `Title: X` / date-only line: `_merge_date_only_headers` folds it into `X | Company date`.
   Label vocabulary widened by `Job Role:` and `Position Held:`. Guards: Project labels never become titles, labels with a
   date in the value are ignored, a real header title is never replaced, and a `Title:` line after bullets stays a bullet.
2. Dates-first, single non-title line after a date (`_merge_dates_first_headers`). Applies only to sections whose first
   content line is a date-only line. Exactly one header-text line (no role word, not a location) followed by a bullet or
   another date-only line is read as the employer, with the title left empty. Before: the employer became the job title
   and the company was empty. Unchanged: one-line titles, sentence lines, company-first layouts.

## Tests
- Added 7 recovery tests (2 new fixtures; positive and negative guards) in test_corpus_parse_recovery.py.
- Full `pytest tests -q`: 314 passed, 1 skipped.
- Golden `--formats aptino,capgemini,suresh`: GOLDEN PASS exit 0, 168/168 passed (56 scored fixtures x 3; 2 new),
  zero_role 0/49, silent_omission 0/168.

## Remaining / not done
- Title trailing after the bullets in a dates-first layout (ambiguous with a title that precedes the next date): not attempted.
- `Title:` after a `Client:` line (Client starts its own labeled block), `Location:` lines under a header become bullets.
- `Title, Employer` comma lists; unbulleted single-line prose after a date in dates-first layouts is left to the old path.
- Offline real-corpus compare not run (PII).
