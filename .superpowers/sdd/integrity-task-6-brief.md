### Task 6: Measurement — hard set + corpus sample

**Files:**
- Modify: `backend/scripts/prod_hard_resume_retest.py` (print `integrity_recovery` meta; ensure recovery flags on)
- Optional: add `backend/scripts/prod_corpus_fidelity_sample.py` that samples 60 via `pick_resumes` **without** importing `corpus_quality_eval`’s Bedrock-stripping side effects — either refactor pick_resumes into a tiny shared module or duplicate the picker lightly in the prod script.

**Important:** Do **not** use `corpus_quality_eval.py` as-is for this measurement; it clears `AWS_BEARER_TOKEN_BEDROCK` at import.

- [ ] **Step 1: Update prod hard retest to report recovery**

For each row include `integrity_recovery` from store/parse_meta and whether blocking `source_lines` / wrong-role remain.

- [ ] **Step 2: Run hard set (12 files)**

Run: `cd backend && .venv/Scripts/python.exe scripts/prod_hard_resume_retest.py`  
Record: status counts, zero-role count, blocking source_lines count, recovery used count.

- [ ] **Step 3: Run 60-file production fidelity sample**

Script output must include:
- `% meeting bar` = passed OR (needs_review without blocking source_lines and without wrong-role)
- failing file ids/names

- [ ] **Step 4: Run golden (LLM off)**

Run: `cd backend && .venv/Scripts/python.exe scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh`  
Expected: exit 0

- [ ] **Step 5: Write short results note under `backend/eval_reports/` (e.g. `fidelity_recovery_wave.md`) with the two scoreboards. Commit only if user asks.**

---

