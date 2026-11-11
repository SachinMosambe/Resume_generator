# Task 7 report: Golden CI gate (Wave F)

## Status
DONE_WITH_CONCERNS. Committed on `main`: `1a87c7f ci: enforce corpus golden quality gates on pull requests`.

## What shipped
- `backend/scripts/corpus_quality_eval.py`: `--golden` (plus `--fixtures a,b` filter). `main(argv)` now returns an exit code.
  - Reads `tests/fixtures/golden/manifest.json`, scored fixtures only, one run per fixture x format: intake -> parse -> `ResumeGenerationService`.
  - Prints each gate with numerator/denominator, pct, PASS/FAIL, failing IDs (`fixture@format`), and per-run deviations. Writes `eval_reports/golden_latest.json`.
  - Exit 0 iff every enforceable gate is met. Exit 1 on a gate miss or zero measured runs. Exit 2 on setup errors (unknown fixture, requested format missing, `RESUME_LLM_PARSE_FALLBACK` true).
  - `RESUME_LLM_PARSE_FALLBACK` is forced `false` when `--golden` is on argv, and checked again at run time.
  - Gates and thresholds come from the manifest, unchanged: passed >=85, zero_role <=3, empty_title <=5, bad_name <=5, scanned >=90, doc >=90, style =100, failed <=2.
  - Added one zero-tolerance gate, `silent_omission_pct` (<=0): expected content missing from a run whose status is `passed` (not flagged for review). This is what fails on a dropped bullet even when the aggregate rate is above 85%.
  - Scanned/DOC gates report `n/a (not enforced)` with a note, because their fixtures are `scored:false` stubs. They are never silently green.
- Capgemini style in CI: `tests/fixtures/golden/synthetic_formats.py` builds an anonymized Capgemini-style ClientFormat DOCX in memory (right-aligned name, `Avenir 45` on every run, Capgemini headings/order). It does not need the font installed, because the assertions read the DOCX XML. The golden runner always uses the synthetic template. `test_format_style_asserts.py` falls back to it when the real template is missing, so Capgemini style tests no longer skip in CI.
- `tests/fixtures/golden/style_checks.py`: pytest-free style assertions, moved out of the test module so the runner (which cannot import pytest, because it is not in requirements.txt) and the tests share one implementation.
- `.github/workflows/ci.yml`: new `golden` job (apt `tesseract-ocr libreoffice-writer`, pip install, `--golden --formats aptino,capgemini,suresh`, env pins incl. `RESUME_LLM_PARSE_FALLBACK=false`). Fixtures only; no private corpus.
- `tests/test_golden_gate_regression.py` (8 tests): clean subset exits 0; injected dropped bullet exits nonzero while `passed_pct` is still 9/10 = 90% (the zero-tolerance gate names the fixture and `bullet:shipped`); a generator crash stays in the denominator and fails; fallback-on returns 2; unknown fixture/format returns 2; stubs are not scored and zero runs is never a pass; gate-math unit test; plus a parser regression test.

## Real defects the gate surfaced and fixed
1. `detailed_resume_parser._parse_job_header_line`: "Engineer II | Jan 2019 - Present" parsed as title "Engineer", company "II". A level suffix (I-IV / digit) now stays in the title and is never a company. Fixes `promotion_same_employer`.
2. `output_integrity`: a bullet-marked source line missing from the output now counts as a *hard* `source_lines` finding. Before, if the parser had never read the line, it was only a soft/info note and the run showed `passed` with the bullet gone (`ambiguous_role_headers` lost "Closed the monthly books ...").
3. `output_integrity`: suppressed-section comparison is now case/format normalized ("REFERENCES" in source vs "References" heading-cased). Before, intentionally omitted References raised a blocking `additional_sections_missing`. Fixes `references_section_present`.

## Local golden run (aptino, capgemini[synthetic], suresh) - exit 0
40 scored fixtures x 3 formats = 120 runs (10 unscored stub fixtures skipped).

| Gate | Rule | Num/Den | Result |
|---|---|---|---|
| passed_pct | >=85 | 117/120 = 97.5% | PASS (failing: `ambiguous_role_headers` x3) |
| zero_role_pct | <=3 | 0/33 | PASS |
| empty_title_pct | <=5 | 0/48 | PASS |
| bad_name_pct | <=5 | 0/39 | PASS |
| scanned_recovery_pct | >=90 | 0/0 | n/a, not enforced |
| doc_conversion_pct | >=90 | 0/0 | n/a, not enforced |
| style_assert_pct | =100 | 18/18 | PASS |
| failed_pct | <=2 | 0/120 | PASS |
| silent_omission_pct | =0 | 0/120 | PASS |

Before the fixes the same run was `passed_pct` 93/120 (77.5%) FAIL and `zero_role_pct` 2/37 FAIL.

## Interpretation decisions (please review)
- **Manifest correction:** `bullet_only_experience` and `bullet_only_with_date_lines` moved from `expected_status: passed` to `needs_review`. Plan Task 2/3 deliberately keeps unassigned bullets out of the document ("do not render unassigned as a fake job without review") and raises a blocking review, so `passed` was a stale Task-0 guess. Their bullets are checked against the parser's preserved `unassigned_experience_bullets` (`allow_unassigned_bullets`).
- **Outcome rule for `expected_status: needs_review` fixtures** (the 5 ambiguous ones): `needs_review` or `passed` is acceptable only if every expected fact is intact; `failed`/error never is. Strict equality would need those fixtures to be flagged even when content is perfect.
- **role-bearing** for `zero_role_pct` = `expects_work_history` AND has annotated `expected_roles` (33 fixtures). Bullet-only and header-less fixtures have no source roles to find. Without this, those two fixtures give 2/37 = 5.4% against the 3% bar.
- Thresholds were not lowered.

## Concerns
- **OCR >=90% and DOC >=90% are not enforced.** The scanned/legacy-DOC/table-DOCX fixtures still have `NotImplementedError` builders, so they remain `scored:false` as instructed. The exit check for those two gates is open. This machine also has no Tesseract/LibreOffice.
- **Known remaining loss:** `ambiguous_role_headers` ("Litware Analyst Dallas / 2021" header with no separators) still drops the first role's bullet. It is now flagged `needs_review` (blocking `source_lines`), not silently passed. It is the only passed_pct miss.
- **Integrity change affects the real corpus** (bullet-marked missing lines are now blocking). See the paired-run note below for the effect on the 60-file sample.
- The CI `golden` job is added but is not yet marked as a required check; do that after the first green CI run on GitHub. That has not been observed yet (no remote run from here).
- `--from-report` was not implemented (stretch). `test/format/Suresh Duvvada.docx` is already tracked in git, so Suresh in CI uses the real committed file. Capgemini uses the synthetic one.
- Untracked `backend/eval_reports/golden_latest.json` is written by each run; it is not committed.
- Full backend suite: 252 passed, 1 skipped.

## Paired 60-file release comparison
See the addendum below (appended if the run finished).

### Addendum: paired 60-file run (private corpus, local only; same `--limit 60` sampling as baseline `corpus_eval_20261111_135025`)
Same 60 files (identical selection procedure), formats aptino/capgemini/suresh. Report: `backend/eval_reports/corpus_eval_20261111_174552.json` (untracked).

| Metric | Baseline | Now |
|---|---|---|
| Extract errors | 1 no_text | 1 no_text |
| Zero roles / zero bullets | 18.6% | 15.3% |
| Avg roles / bullets per resume | 6.05 / 60.5 | 6.17 / 61.4 |
| Empty-title role rate | 11.2% | 11.0% |
| Name detected | 93.2% | 91.5% |
| Per format: passed / needs_review / failed | 8 / 51 / 0 (aptino) | 14 / 41 / 4 |

- Improvement: passed 8 -> 14 per format; needs_review 51 -> 41.
- **Regression to look at:** 4/60 (6.7%) are now `failed` (was 0), above the 2% bar on the real corpus. All four fail on `bullet_wrong_role` (Task 3's role-assignment check), not on content loss; one was `passed` before. Task 7 did not touch that check (my integrity edits only affect `source_lines` severity and suppressed-title matching). Not bisected; likely false positives on resumes with repeated bullets across roles (one 12-role DOCX reports 73 "misassigned" bullets). Worth a follow-up before making the golden job a required check on corpus behavior.
- Zero-role on the real corpus (15.3%) is still far from the <=3% target. The golden fixtures do not cover that failure mode.
- The 250-file parse sweep (`fidelity_report.py`) and `spotcheck_formats.py` were not run.

## Important finding 7 follow-up
- Fixed the golden path so fixtures with `allow_unassigned_bullets: true` require an actual `needs_review` status; `passed` is no longer accepted.
- Silent-omission matching now uses only text rendered in the generated DOCX. Parser-preserved unassigned bullets no longer mask missing output.
- Added regressions covering both missing DOCX bullets with an incorrect `passed` status and an incorrect `passed` status even when content is rendered.
- Regression suite: `10 passed`.
- Full golden run: exit `0`; 40 fixtures x 3 formats (120 runs), `passed_pct` 111/120 (92.5%), `silent_omission_pct` 0/120.
