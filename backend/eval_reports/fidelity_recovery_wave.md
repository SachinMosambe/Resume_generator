# Fidelity recovery wave — measurement (Task 6)

Date: 2026-11-12. Production settings (`backend/.env`): Bedrock `google.gemma-3-27b-it`, `RESUME_LLM_LINE_EXTRACT=true`,
`RESUME_LLM_PARSE_FALLBACK=true`, `RESUME_INTEGRITY_RECOVERY=true` (default), faithful mode, Aptino format.
Scripts: `scripts/prod_hard_resume_retest.py`, `scripts/prod_corpus_fidelity_sample.py` (neither imports `corpus_quality_eval`, so Bedrock is not stripped).

**Meeting bar** = status `passed` OR (`needs_review` with no blocking `source_lines` AND no wrong-role / `bullet_wrong_role`).
Error / no-text rows count as NOT meeting the bar.

## Scoreboard 1 — hard set (12 files, Aptino, production)

| Metric | Value |
|---|---|
| Status counts | needs_review 11, failed 1, passed 0 |
| Zero-role resumes | 1 / 12 |
| Blocking `source_lines` remaining | 10 / 12 |
| Wrong-role remaining | 1 / 12 |
| Recovery swapped in (`used`/`preferred`) | 0 / 12 |
| Recovery outcome (meta error) | `no_improvement` 8, `no_roles` 1, `lumped` 1, none 2 |
| **Meeting bar** | **2 / 12 = 16.7%** |

Meeting bar: Rosalind Murphy Portfolio (.pdf), Srinivasarao_P_AEM-JAVA-Profile (.pdf).
Failing: Shanley_IT_Consultin_Content_Experience, US Marco Perez Tech Lead..., 4535fb64-...docx (0 roles, `no_roles`),
Dice_Resume_CV_Mukesh_Kumar, Dice_Resume_CV_Matt_Sullivan, 327129D7-...pdf, Kaminski Michael (.doc, status failed,
`bullet_wrong_role`, `lumped`), Resume 2024 Vivian L, Dice_Profile_Sudeesh_Sasidharan_Highlighted, AEF8371C-...pdf.
Recovery meta distribution: `no_improvement` 8, `no_roles` 1, `lumped` 1, none 2.
(Note: `used` in `parse_meta.integrity_recovery` means a recovered store was produced; `preferred` means it was kept.
Neither happened on the hard set.)

## Scoreboard 2 — production corpus sample (60 files, Aptino, full run)

Stratified via copied `pick_resumes(60)` (pdf 27 / docx 27 / doc 6).

| Metric | Value |
|---|---|
| Status counts | passed 10, needs_review 46, failed 3, error/no_text 1 |
| Zero-role resumes | 1 |
| Blocking `source_lines` remaining | 36 / 60 |
| Wrong-role remaining (`bullet_wrong_role`) | 3 / 60 |
| Recovery swapped in and preferred | 1 / 60 |
| Recovery attempted (non-empty meta error or used) | ~30; `no_improvement` 26, `dropped_company` 7, `lumped` 2, `no_roles` 1 |
| **Meeting bar** | **22 / 60 = 36.7%** |

Bar by extension: pdf 9/27, docx 12/27, doc 1/6.
Other blocking codes across the sample: bullets_missing 11, overlapping_role_dates 10, identity_ambiguous 5,
experience_bullets_unassigned 3, source_backed_titles_unresolved 3, certifications_missing 3.
Failing ids (stable hash-based, see `prod_corpus_fidelity_sample.json`): 38 files; list is in the JSON `failing` array.
Failed status: pdf-f1978328, docx-e752d823, doc-63efdeeb. No-text: pdf-acef50d9.

## Golden (LLM off)

`corpus_quality_eval.py --golden --formats aptino,capgemini,suresh` → **exit 0**, GOLDEN PASS
(56 fixtures x 3 formats = 168 runs; passed 100%, failed 0%, silent_omission 0%, zero_role 0%).

## Takeaways

- The single grounded recovery pass rarely helps: swapped in on 1/60 corpus and 0/12 hard files. Dominant outcome is `no_improvement`
  (extractor returns the same coverage), plus 7 `dropped_company` rejections on the corpus.
- Blocking `source_lines` is the dominant remaining failure (36/60, 10/12), far ahead of wrong-role (3/60).
- The bar is far from met; the integrity gate remains strict, so most outputs stay `needs_review` rather than `passed`.
