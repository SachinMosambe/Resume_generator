# Task 0 report — Pin baseline and golden manifest

**Status:** DONE_WITH_CONCERNS

**Commit:** `f924a4b` on `main` — `test: pin corpus baseline case map and golden manifest skeleton` (54 files). Not pushed. Corpus JSON, `eval_reports/samples/`, and real resumes were not staged.

## What shipped

- `backend/eval_reports/baseline_case_map.md` — opaque case IDs for the 11 Nov 2026 run `corpus_eval_20261111_135025`.
- `backend/tests/fixtures/golden/manifest.json` — version 1, 50 synthetic fixtures (48 scored), release gates from the plan.
- `backend/tests/fixtures/golden/cases/*.txt` — anonymized text only. Every `expected_roles` / name / bullet substring was checked against its case file (0 gaps).
- `backend/tests/fixtures/golden/build_golden_fixtures.py` — `--list` and `--check-sources`. `scanned_pdf`, `mixed_pdf`, `table_docx`, and `legacy_doc` raise `NotImplementedError` for a later wave.
- `backend/tests/test_golden_manifest.py` — the specified load test, plus a check that the 50-fixture set, required pattern families, gate keys, and case files are present.

## Step 1 — baseline queries

Run from `backend/` with the venv Python and the PowerShell filters in the brief (tables written outside the repo; counts only):

| Query | Result |
|---|---|
| `stage == done` and `parse.roles == 0` | **11** |
| `stage == done` and Aptino `checks.bullets.ok == false` | **6**, all with `roles > 0` |
| `stage == extract` | **1**, error `no_text` |
| aptino + capgemini + suresh all `passed` | **7** |

Aptino has 8 `passed` rows. `source_key` `pdf-9e74c120` (7 roles) is aptino-only and is not a unanimous control.

`source_key` is `{ext}-{sha1(filename)[:8]}`. The filename stem is not in the map. Match a local file by hashing its name.

## Step 2 — case map

| Group | IDs | stage to investigate | expects_work_history |
|---|---|---|---|
| Zero-role done | zr-01 … zr-11 | `parse`, except zr-11 `ocr` | `yes` when `layout.bulletish > 0` (9 rows). zr-06 prose (`bulletish=0`, 290 lines) and zr-11 scanned (`scanned_pages=9`, `bulletish=0`) are `unconfirmed` |
| Bullet mismatch | bf-01 … bf-06 | `integrity` | `yes` (roles already parsed). bf-06 also has 3/3 empty titles. Counts are `found`/`expected` only |
| Unanimous pass | pc-01 … pc-07 | `control` | `yes`. pc-03 still has 4 empty titles and pc-04 has 2; they passed anyway |
| Extract | ex-01 | `extract` | `unconfirmed` (`no_text`, 0 chars) |

`scored` is false on every corpus row. No employer, title, or bullet text from the corpus is stored. Originals were not opened.

## Step 3–4 — golden manifest

50 fixtures. Required skeleton IDs are present with the plan's companies and bullets: `clean_guillermo_pattern` (Alex Example / ExampleCorp / Senior Engineer / 2020 / `shipped`), `dice_wrapper_full_resume` (Morgan Hale; Amazon / Software Engineer / `onboarding tool`), `paren_title_split_header`, `bullet_only_experience` (`allow_unassigned_bullets`), `education_only_complete` (`expects_work_history` false).

Pattern families include two-column, table DOCX, 12-role history, missing optional sections, scanned, `.doc`, sparse profile vs full resume, and ambiguous cases with `expected_status` `needs_review`. Two non-resumes are `scored: false` and `expected_status: quarantine`. Style subset is limited to conventional clean controls.

Dice text follows the shape of `DICE_LIKE` in `test_resume_reading.py` with a different person and school. It is not a copy of a corpus file.

## Step 5 — entry points (unchanged)

- `parse_resume_detailed(resume_path, resume_text=None)` in `backend/app/services/detailed_resume_parser.py` (around line 2554).
- `IntegrityReport` is a dataclass with `status: str`, `checks: dict`, `warnings: list[str]`. `check_output_integrity(...)` returns it from `backend/app/services/output_integrity.py`.
- `backend/app/api/routes/generate.py` sets `X-Review-Status` to `report.status` and `X-Review-Warnings` to `quote(json.dumps(report.warnings[:10]))` — a URL-quoted JSON list of strings, capped at 10.
- `frontend/src/app/page.tsx` `parseReview` reads those headers, `decodeURIComponent` + `JSON.parse`, and keeps a `string[]`. Malformed headers are ignored. No severity objects yet.

## Step 6 — tests

TDD: `test_golden_manifest_loads_and_has_scored_fixtures` failed first with `FileNotFoundError` for `manifest.json`.

After the fixtures:

`backend\.venv\Scripts\python.exe -m pytest tests\test_golden_manifest.py -v` from `backend/`

**2 passed** in 0.03s (`test_golden_manifest_loads_and_has_scored_fixtures`, `test_golden_manifest_covers_pattern_families_and_sources`).

`build_golden_fixtures.py --check-sources` printed `ok 50 sources`.

## Step 7 — commit

Staged only `baseline_case_map.md`, `backend/tests/fixtures/golden/`, and `backend/tests/test_golden_manifest.py`. Left untracked: the eval JSON/markdown, corpus scripts, real resumes, and this report.

## Concerns

1. zr-06, zr-11, and ex-01 do not have a source-backed yes/no for work history. The JSON shows no bullet-like lines (or no text), and the original files were not opened, so the map says `unconfirmed` instead of inventing `yes`.
2. Scanned, mixed, table-DOCX, and legacy-DOC fixtures are text plus a stub builder. Later waves must implement the binaries before OCR / `.doc` gates can run.
3. pc-03 and pc-04 are unanimous passes with empty titles, so they are integrity controls, not empty-title failures.

## Exit check

Each confirmed failure and the seven pass controls has a case ID, an investigate stage, and an expectation taken from eval counts. Exact inputs can be re-selected with `source_key` without putting filenames in git.

## Important review fix

- Set `scored: false` on all eight fixtures backed by unimplemented binary builders, while preserving their expectations.
- Added a manifest regression test requiring every stub-builder fixture to remain unscored and documented the gate requirement beside the builder stubs.
- Test command (from `backend/`): `backend\.venv\Scripts\python.exe -m pytest tests\test_golden_manifest.py -v`
- Output: `3 passed in 0.05s`.
