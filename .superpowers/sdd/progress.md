# SDD Progress Ledger
Plan: docs/superpowers/plans/2026-11-11-corpus-quality-spine.md
Branch: main (user consented)
Started: 2026-11-11

Task 0: complete (commits 9b6b1a7..9ea9cfe, review clean)

Task 1: complete (commits 9ea9cfe..aeb8bd9, review clean)

Task 1: complete (commits 9ea9cfe..aeb8bd9, review clean)

Task 2: complete (commits aeb8bd9..4855712, review clean)
Minors deferred: ambiguous_headers invent risk; second title-only folds into prior role; duplicate tech-label lists in parse_confidence vs parser; unassigned bullets when roles exist may still drop silently; integrity wiring of parse_meta is Task 3
Task 3: complete (commits 4855712..31ac2e8, review clean)
Minors deferred: soft wording overstates; %/$ number detection weak; table layouts untested for role assignment; dead _source_lines_missing; eval script personal paths
Task 4: complete (commits 31ac2e8..324ed95, review clean)
Minors deferred: unread-page warning wording when OCR partially used; quarantine_reason not in 422 body; OCR/DOC ≥90% deferred to Task 7 binaries
Task 5: complete (commits 324ed95..d7d82fa, review clean)

Task 6: complete (commits d7d82fa..ed2e9a0, review clean)
⚠️ Capgemini style in clean CI needs synthetic template (PII blocked committing real Capgemini-Format.docx)
Task 7: complete (commits ed2e9a0..ba76b0f, Important gate hole fixed; review accepted with disclosed follow-ups)
Follow-ups: implement scanned/DOC binary builders then enforce ≥90% gates; synthetic Capgemini already in CI; private 60-file bullet_wrong_role false positives; 250-file sweep + spotcheck before release; make golden a required GitHub check after first green run
Final review: yes-with-follow-ups → Important 1–4 fixed in 5ccaf8f + 56fa34a
Remaining follow-ups: OCR/DOC builders; private 60-file bullet_wrong_role; 250-file sweep; make golden required on GitHub; overlapping_role_dates may be noisy; commit plan/spec docs
