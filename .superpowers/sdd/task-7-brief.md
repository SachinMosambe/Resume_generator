### Task 7: Golden CI gate (Wave F)

**Files:**
- Modify: `backend/scripts/corpus_quality_eval.py` — `--golden`, gate table with numerator/denominator/failing IDs
- Modify: `.github/workflows/ci.yml` — install deps, run golden, fail on gate miss
- Create: `backend/tests/test_golden_gate_regression.py` — inject known regression → nonzero exit

**Interfaces:**
- CLI: `python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh`
- Exit code 0 iff all gates pass; print failing fixture IDs per gate
- Scored fixtures declared in manifest before run

- [ ] **Step 1: Implement `--golden` runner**

Load `tests/fixtures/golden/manifest.json`. For each scored fixture × format, run the normal generation entry (same as eval: extract → parse → `ResumeGenerationService`). Aggregate:

| Gate | Formula |
|------|---------|
| passed_pct | passed / scored_valid_inputs |
| zero_role_pct | zero_role_among_expects_work_history / role_bearing_fixtures |
| empty_title_pct | untitled_source_titled_roles / annotated_source_titled_roles |
| bad_name_pct | wrong_or_missing_name / fixtures_with_expected_name |
| scanned_recovery_pct | recovered_scanned / scored_scanned |
| doc_conversion_pct | converted_ok / scored_doc |
| style_assert_pct | style_pass / clean_subset |
| failed_pct | failed / scored_valid_inputs |

Report unexpected intake/execution errors explicitly (remain in denominator where specified).

- [ ] **Step 2: CI workflow**

```yaml
  golden:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: backend/requirements.txt
      - run: sudo apt-get update && sudo apt-get install -y tesseract-ocr libreoffice-writer
      - run: pip install -r requirements.txt
      - run: python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
        env:
          RESUME_LLM_CONDENSE: "false"
          RESUME_AGENT_PIPELINE: "false"
          RESUME_LLM_PARSE_FALLBACK: "false"
          RESUME_OCR_ENABLED: "true"
```

Enable as required check only after local golden is green.

- [ ] **Step 3: Regression harness test**

Force a known material omission in a unit/harness test; assert runner exits nonzero and emits a review/failure reason regardless of aggregate rate.

- [ ] **Step 4: Run golden locally**

```bash
cd backend
.\.venv\Scripts\activate
python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
```

Expected: all gates green (or list failing IDs to fix before merging).

- [ ] **Step 5: Paired release comparison**

Rerun the same 60 inputs (original file list from dated JSON) and the 250-file parse sweep with the same sampling procedure. Compare: extraction success, zero roles on source-labeled resumes, rendered bullet recall, review reasons. Spot-check known real failures + seven clean controls.

```powershell
# Prefer original list via eval runner flag once implemented, e.g.:
# python scripts/corpus_quality_eval.py --from-report eval_reports/corpus_eval_20261111_135025.json --formats aptino,capgemini,suresh
python scripts/fidelity_report.py
python scripts/corpus_quality_eval.py --limit 60 --formats aptino,capgemini,suresh
python scripts/spotcheck_formats.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/corpus_quality_eval.py .github/workflows/ci.yml backend/tests/test_golden_gate_regression.py
git commit -m "ci: enforce corpus golden quality gates on pull requests"
```

**Exit check:** Full golden gate green in all three formats. Before/after reported for targeted fixtures, paired 60-file eval, and each gate’s numerator/denominator.

---

## Additive data contract (implementation checklist)

| Data | Fields |
|------|--------|
| Extraction metadata | `ocr_pages` (existing), `ocr_missing_pages`, `doc_converted`, optional `quarantine_reason` |
| Parse metadata | `confidence` 0–1, `reasons`, `llm_repaired`; keep source locations with facts/unassigned text |
| Review | `passed` \| `needs_review` \| `failed`; warnings `{severity, code, message}`; intake stops use HTTP 422 |

---

## Self-review (plan vs spec)

| Spec section | Task coverage |
|--------------|---------------|
| IntakeGate | Task 4 |
| DeterministicParse + evidence | Tasks 1–2 |
| IntegrityGate severity | Task 3 |
| LLM fallback | Task 5 |
| Format polish | Task 6 |
| Golden CI | Task 7 |
| Wave 0 baseline pin | Task 0 |
| ≥85% / ≤3% / OCR / DOC targets | Task 7 gates + Tasks 2–4 exit checks |
| No real resumes in git | Task 0 fixtures + Global Constraints |

No TBD placeholders. Types: `parse_meta`, `EmploymentEvidence`, structured warnings used consistently across tasks.
