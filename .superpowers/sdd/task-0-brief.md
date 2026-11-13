### Task 0: Pin baseline and golden manifest (Wave 0)

**Files:**
- Create: `backend/eval_reports/baseline_case_map.md`
- Create: `backend/tests/fixtures/golden/manifest.json`
- Create: `backend/tests/fixtures/golden/cases/` (anonymized `.txt` patterns first)
- Create: `backend/tests/fixtures/golden/build_golden_fixtures.py`
- Modify: none required yet beyond verifying entry points
- Test: manual PowerShell baseline queries + `pytest` smoke that manifest loads

**Interfaces:**
- Consumes: `backend/eval_reports/corpus_eval_20261111_135025.json`
- Produces: opaque case IDs with `stage_to_investigate`, `expects_work_history`, role/employer/title/date/bullet expectations, `scored: true|false`

- [ ] **Step 1: Reproduce baseline case lists locally (no resume body in artifacts)**

From `backend/` with venv active:

```powershell
$run = Get-Content -Raw 'eval_reports/corpus_eval_20261111_135025.json' | ConvertFrom-Json
$run.rows | Where-Object { $_.stage -eq 'done' -and $_.parse.roles -eq 0 } |
    Select-Object id, file, ext | Format-Table
$run.rows | Where-Object { $_.stage -eq 'done' -and $_.formats.aptino.checks.bullets.ok -eq $false } |
    Select-Object id, file, ext | Format-Table
$run.rows | Where-Object { $_.stage -eq 'extract' } |
    Select-Object id, file, ext, error | Format-Table
```

Expected: 11 zero-role `done` rows; ~6 bullet-check failures among role-bearing; 1 extract/`no_text` (confirm against JSON).

- [ ] **Step 2: Write `baseline_case_map.md` with case IDs only**

For each of the 11 zero-role + 6 bullet-fail + 7 unanimous pass controls, record:

```markdown
| case_id | opaque_label | ext | stage | expects_work_history | notes_code |
|---------|--------------|-----|-------|----------------------|------------|
| zr-01 | zero_role_pdf_a | pdf | parse | yes | investigate_parse |
```

Do **not** paste resume text. Locally compare originals → parse → DOCX only on the machine that has the corpus.

- [ ] **Step 3: Create golden manifest skeleton (~50 entries)**

`backend/tests/fixtures/golden/manifest.json`:

```json
{
  "version": 1,
  "baseline_run": "corpus_eval_20261111_135025",
  "fixtures": [
    {
      "id": "clean_guillermo_pattern",
      "pattern": "conventional_clean",
      "source": "cases/clean_conventional.txt",
      "scored": true,
      "expects_work_history": true,
      "expected_roles": [
        {"company": "ExampleCorp", "title": "Senior Engineer", "dates_contains": ["2020"], "bullet_substrings": ["shipped"]}
      ],
      "expected_name": "Alex Example",
      "formats": ["aptino", "capgemini", "suresh"],
      "style_subset": true
    },
    {
      "id": "dice_wrapper_full_resume",
      "pattern": "dice_wrapper",
      "source": "cases/dice_wrapper.txt",
      "scored": true,
      "expects_work_history": true,
      "expected_roles": [
        {"company": "Amazon", "title": "Software Engineer", "bullet_substrings": ["onboarding tool"]}
      ]
    },
    {
      "id": "paren_title_split_header",
      "pattern": "paren_title",
      "source": "cases/paren_title.txt",
      "scored": true,
      "expects_work_history": true
    },
    {
      "id": "bullet_only_experience",
      "pattern": "bullet_only",
      "source": "cases/bullet_only.txt",
      "scored": true,
      "expects_work_history": true,
      "allow_unassigned_bullets": true
    },
    {
      "id": "education_only_complete",
      "pattern": "education_only",
      "source": "cases/education_only.txt",
      "scored": true,
      "expects_work_history": false
    }
  ],
  "gates": {
    "passed_pct_min": 85,
    "zero_role_pct_max": 3,
    "empty_title_pct_max": 5,
    "bad_name_pct_max": 5,
    "scanned_recovery_pct_min": 90,
    "doc_conversion_pct_min": 90,
    "style_assert_pct_min": 100,
    "failed_pct_max": 2
  }
}
```

Expand to ~50 with two-column, table DOCX, long history, missing optional sections, scanned, `.doc`, sparse-profile-needing-full-resume, and ambiguous cases with `expected_status`.

- [ ] **Step 4: Add anonymized text fixtures for Wave A patterns**

Create at least:

- `cases/dice_wrapper.txt` — Dice preamble labels then real EXPERIENCE (mirror `DICE_LIKE` in `test_resume_reading.py` with new names)
- `cases/paren_title.txt` — `Company` / `(Title) MM/YY - Present` / bullets
- `cases/bullet_only.txt` — EXPERIENCE then bullets without job headers
- `cases/education_only.txt` — name, education, skills; no employment section
- `cases/clean_conventional.txt` — control that already passes

- [ ] **Step 5: Verify implementation entry points in checkout**

Confirm these exist and note current warning shape:

- `parse_resume_detailed` in `backend/app/services/detailed_resume_parser.py`
- `check_output_integrity` → `IntegrityReport(status, checks, warnings: list[str])` in `output_integrity.py`
- Headers in `generate.py`: `X-Review-Status`, `X-Review-Warnings` (JSON list of strings, URL-quoted)
- Frontend parse in `frontend/src/app/page.tsx`

- [ ] **Step 6: Manifest load smoke test**

```python
# backend/tests/test_golden_manifest.py
import json
from pathlib import Path

def test_golden_manifest_loads_and_has_scored_fixtures():
    path = Path(__file__).parent / "fixtures" / "golden" / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    scored = [f for f in data["fixtures"] if f.get("scored")]
    assert len(scored) >= 5
    for f in scored:
        assert "id" in f and "expects_work_history" in f
```

Run: `pytest backend/tests/test_golden_manifest.py -v`  
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/eval_reports/baseline_case_map.md backend/tests/fixtures/golden backend/tests/test_golden_manifest.py
git commit -m "test: pin corpus baseline case map and golden manifest skeleton"
```

**Exit check:** Each known failure has case ID, source-backed expectation, and stage. Exact baseline inputs can be rerun.

---

