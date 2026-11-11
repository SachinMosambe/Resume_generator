# Baseline case map

Pinned run: `corpus_eval_20261111_135025` (11 Nov 2026). Queries were run from `backend/` against that JSON.

Confirmed counts:

- 11 `done` rows with `parse.roles == 0`
- 6 `done` rows with Aptino `checks.bullets.ok == false`, all of them role-bearing
- 7 rows with `passed` on aptino, capgemini, and suresh together
- 1 `extract` row, error `no_text`

Aptino alone has 8 `passed` rows. The extra row (`source_key` `pdf-9e74c120`, 7 roles) is not in the control set because capgemini and suresh are `needs_review`.

`source_key` is `{ext}-{sha1(filename)[:8]}`, the opaque prefix of the eval row id. The filename stem is omitted. A local corpus file matches when `sha1(filename)[:8]` equals that suffix. This file stores no resume text, employer names, or contact details from the corpus.

`stage` is the stage to investigate, not the eval row's terminal stage (those rows are `done` except `ex-01`). `expects_work_history` is `yes` only when the eval row already shows role counts or bullet-like lines. `unconfirmed` means the JSON does not show that evidence and the original file was not opened. `scored` is `false` for every row: these are corpus pointers, not golden fixtures.

Employer, title, and bullet strings from the corpus are not recorded. Bullet-check notes use only the integrity counts (`found`/`expected`).

## Zero-role (`done`, roles = 0)

| case_id | opaque_label | source_key | ext | stage | expects_work_history | scored | notes_code | signal |
|---------|--------------|------------|-----|-------|----------------------|--------|------------|--------|
| zr-01 | zero_role_docx_pipe | docx-259f84ac | docx | parse | yes | false | investigate_parse | roles=0; bulletish=21; lines=37; edu=1; skills=31; line_cov=32.3; pipes=1 |
| zr-02 | zero_role_docx_dense | docx-4904fb1a | docx | parse | yes | false | investigate_parse | roles=0; bulletish=80; lines=109; edu=1; skills=3; line_cov=41.9 |
| zr-03 | zero_role_docx_lowcov | docx-6deb0330 | docx | parse | yes | false | investigate_parse | roles=0; bulletish=42; lines=71; edu=1; skills=0; line_cov=17.2 |
| zr-04 | zero_role_docx_short | docx-edaf5ed0 | docx | parse | yes | false | investigate_parse | roles=0; bulletish=22; lines=29; edu=0; skills=0; line_cov=25.0 |
| zr-05 | zero_role_pdf_dense | pdf-0a6bd3f5 | pdf | parse | yes | false | investigate_parse | roles=0; bulletish=91; lines=243; edu=3; skills=40; line_cov=7.2 |
| zr-06 | zero_role_pdf_prose | pdf-192ce60d | pdf | parse | unconfirmed | false | investigate_parse_prose | roles=0; bulletish=0; lines=290; edu=3; skills=0; line_cov=53.2 |
| zr-07 | zero_role_pdf_refs | pdf-45b67062 | pdf | parse | yes | false | investigate_parse | roles=0; bulletish=26; lines=87; edu=4; skills=0; line_cov=10.0 |
| zr-08 | zero_role_pdf_lowcov | pdf-5b33f97e | pdf | parse | yes | false | investigate_parse | roles=0; bulletish=12; lines=52; edu=0; skills=0; line_cov=2.4 |
| zr-09 | zero_role_pdf_bullets | pdf-6e22211a | pdf | parse | yes | false | investigate_parse | roles=0; bulletish=79; lines=190; edu=0; skills=0; line_cov=29.2 |
| zr-10 | zero_role_pdf_skills | pdf-92bbeae4 | pdf | parse | yes | false | investigate_parse | roles=0; bulletish=72; lines=87; edu=3; skills=54; line_cov=51.9 |
| zr-11 | zero_role_pdf_scanned | pdf-fe9a4339 | pdf | ocr | unconfirmed | false | investigate_ocr | roles=0; bulletish=0; lines=127; caps=32; edu=1; line_cov=16.0; scanned_pages=9 |

## Bullet-check failures (role-bearing, Aptino `bullets.ok` false)

| case_id | opaque_label | source_key | ext | stage | expects_work_history | scored | notes_code | signal |
|---------|--------------|------------|-----|-------|----------------------|--------|------------|--------|
| bf-01 | bullet_mismatch_doc | doc-9554c3eb | doc | integrity | yes | false | investigate_bullet_mismatch | roles=5; bullets_found=139; bullets_expected=140; line_cov=71.7 |
| bf-02 | bullet_mismatch_docx | docx-e779b25a | docx | integrity | yes | false | investigate_bullet_mismatch | roles=9; bullets_found=79; bullets_expected=80; line_cov=85.1 |
| bf-03 | bullet_mismatch_pdf_plain | pdf-073155f7 | pdf | integrity | yes | false | investigate_bullet_mismatch | roles=13; bullets_found=100; bullets_expected=103; bulletish=0; line_cov=93.4 |
| bf-04 | bullet_mismatch_pdf_one_empty_title | pdf-3490726c | pdf | integrity | yes | false | investigate_bullet_mismatch | roles=6; empty_title_roles=1; bullets_found=70; bullets_expected=71; line_cov=80.6 |
| bf-05 | bullet_mismatch_pdf_long | pdf-411cbb0c | pdf | integrity | yes | false | investigate_bullet_mismatch | roles=4; bullets_found=112; bullets_expected=113; line_cov=86.1 |
| bf-06 | bullet_mismatch_pdf_empty_titles | pdf-922bc016 | pdf | integrity | yes | false | investigate_bullet_mismatch_empty_titles | roles=3; empty_title_roles=3; bullets_found=19; bullets_expected=20; line_cov=93.5 |

## Unanimous pass controls

| case_id | opaque_label | source_key | ext | stage | expects_work_history | scored | notes_code | signal |
|---------|--------------|------------|-----|-------|----------------------|--------|------------|--------|
| pc-01 | unanimous_docx_single_role | docx-158b565b | docx | control | yes | false | baseline_unanimous_pass | roles=1; empty_title_roles=0; bullets=77; line_cov=96.3 |
| pc-02 | unanimous_docx_four_roles | docx-1b876239 | docx | control | yes | false | baseline_unanimous_pass | roles=4; empty_title_roles=0; bullets=63; line_cov=96.6 |
| pc-03 | unanimous_docx_some_empty_titles | docx-3fa5b0d7 | docx | control | yes | false | baseline_unanimous_pass | roles=6; empty_title_roles=4; bullets=36; line_cov=94.5 |
| pc-04 | unanimous_docx_eleven_roles | docx-803410fc | docx | control | yes | false | baseline_unanimous_pass | roles=11; empty_title_roles=2; bullets=38; pipes=1; line_cov=96.1 |
| pc-05 | unanimous_docx_education_heavy | docx-e79aadee | docx | control | yes | false | baseline_unanimous_pass | roles=3; edu=9; bullets=59; line_cov=98.9 |
| pc-06 | unanimous_pdf_pipe | pdf-1118975c | pdf | control | yes | false | baseline_unanimous_pass | roles=5; bullets=18; pipes=1; line_cov=93.5 |
| pc-07 | unanimous_pdf_eleven_roles | pdf-80601c20 | pdf | control | yes | false | baseline_unanimous_pass | roles=11; empty_title_roles=1; bullets=68; line_cov=99.0 |

## Extract failure

| case_id | opaque_label | source_key | ext | stage | expects_work_history | scored | notes_code | signal |
|---------|--------------|------------|-----|-------|----------------------|--------|------------|--------|
| ex-01 | extract_no_text_pdf | pdf-acef50d9 | pdf | extract | unconfirmed | false | investigate_extract_no_text | error=no_text; extract_chars=0 |
