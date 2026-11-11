# Task 6 report: Client format behavior (Wave E)

## Status
DONE. Committed on `main`: "feat: assert Capgemini/Suresh style and hide empty projects".

## Changes
- `services/docx_layout.py`: new `has_renderable_content(content)` (recursively non-blank check).
- `services/docx_skeleton_service.py`: a section whose content has nothing renderable is skipped, including its heading. Capgemini "Summary of Projects" no longer appears without source projects. No projects are ever invented.
- `services/resume_generation_service.py` (`_add_docx_section`, schema renderer): same rule, so empty headings are not emitted on the PDF/schema path either. Previously the heading was written before the empty-content return.
- `tests/test_format_style_asserts.py` (new, 59 cases): run `ResumeGenerationService.generate` on all 6 `style_subset` golden fixtures against Capgemini (`test/format/Capgemini-Format.docx`), Suresh (`Suresh Duvvada.docx`) and Aptino (built-in). Offline (no LLM/agent/S3).
  - `name_align` (Capgemini right, Suresh center, Aptino left) and `font_family` (Avenir 45 / Arial / Arial; all explicit run fonts).
  - `section_order` and `labels` per format (Capgemini: Professional Summary, Skills Profile, Professional Experience, Summary of Projects, Education; Suresh/Aptino: Skill Set Overview, Educational Details, Work Experience, Projects). Required sections come from the source's own headings.
  - Content parity: expected company, title, dates and bullets sit under each format's experience heading; education under the education heading; project content under the projects heading and not under experience.
  - `test_capgemini_hides_empty_projects` (end to end) and a skeleton-level test with an empty projects section.
  - Capgemini and Suresh template tests skip if the template file is absent.

## Verification
- TDD: the skeleton empty-projects test failed before the fix and passes after.
- `pytest tests/test_format_style_asserts.py`: 59 passed.
- Full backend suite (`backend/.venv`): 244 passed, 1 skipped.
- `scripts/spotcheck_formats.py`: name alignment and font match the format on every output. Same status results with and without this change (Manav Kapoor and Anil Java resumes show `failed` both before and after; not caused by this task).

## Concerns
- Pre-existing, not changed: when the source has no summary the generator adds the generic line "Professional with a background aligned to the target role." under a Summary heading (seen on `month_year_roles`). This is filler, not source content. The style tests tolerate an extra Summary heading only, and nothing else. Recommend a follow-up to drop it.
- Aptino and Suresh render Projects (after Experience) with the generic label "Projects", because their templates define no projects label. This is pinned in the tests.
- The style tests rely on heading text matching; they would not catch a heading with the right text but wrong paragraph style beyond the name/font checks.
- `test/format/Capgemini-Format.docx` and `Suresh Duvvada.docx` are not tracked in git (Capgemini is untracked in this checkout). Capgemini/Suresh tests skip when the file is missing, so a clean clone silently skips them. Consider committing the templates under `backend/tests/fixtures`.
- Commit: d210608.
- Spotcheck `failed` statuses on two real resumes remain (parse/integrity issues, out of scope here).

## Important finding follow-up: clean-clone style gate
- Fixed the module-scoped `client_formats` fixture so a missing Capgemini or Suresh template no longer skips the entire style suite. Missing templates are now skipped only when a test requests that specific format; Aptino and any other available format continue to run.
- `test/format/Capgemini-Format.docx` was inspected and not committed: it is a real candidate resume containing personal and employment information, not a sanitized client-only template.
- Generated `Capgemini-Format_*.docx` copies and Office `~$` temporary files remain untracked and were not committed.
- Verification: local checkout with the Capgemini template present: `59 passed`; clean detached worktree without the untracked template: `38 passed, 21 skipped`. The clean-clone run executes Aptino and Suresh while skipping only Capgemini-dependent cases.
