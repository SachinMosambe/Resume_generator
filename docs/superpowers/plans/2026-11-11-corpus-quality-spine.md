# Corpus Quality Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Aptino, Capgemini, and Suresh outputs reliable on real corpus messiness by recovering work history in faithful mode, verifying facts in the rendered DOCX, hardening scanned/legacy intake, adding optional source-checked LLM structure repair, and enforcing release targets with a CI golden gate.

**Architecture:** Extend the shared FastAPI path (`extract` → `parse_resume_detailed` → `structured_resume_store` → DOCX render → `check_output_integrity`). Derive employment expectations from source evidence independently of the parsed role list; optionally repair structure once via LLM only when eligible; keep the same integrity/review semantics for every client format.

**Tech Stack:** Python 3.11, FastAPI, python-docx, PyMuPDF, existing `pdf_ocr` / `doc_converter`, pytest, GitHub Actions; optional AWS Bedrock via existing LLM client when `RESUME_LLM_PARSE_FALLBACK=true`.

**Spec:** `docs/superpowers/specs/2026-11-11-corpus-quality-spine-design.md`  
**Prior plan:** `docs/superpowers/plans/2026-10-27-resume-output-fidelity.md`  
**Baseline run:** `backend/eval_reports/corpus_eval_20261111_135025.{json,md}` (= `corpus_eval_latest.*`)

## Global Constraints

- Faithful mode is default: preserve source facts and original bullet text, including long work histories; condense/agent pipeline off for scored runs.
- No invented employers, titles, dates, or bullets; LLM repair is restructure-only and source-checked.
- Never log resume body, names, emails, or phones — aggregate counts, opaque case IDs, and reason codes only.
- Never commit real candidate documents; golden fixtures are synthetic or anonymized layout patterns only.
- All three formats share the same intake → parse → store → verify path; format code only styles a validated store.
- Keep `X-Review-Status` / `X-Review-Warnings` compatible with existing readers; severity/codes may be additive.
- Scored CI golden run uses the deterministic path; LLM fallback is tested with stubs independently.
- Release targets (each format where applicable): `passed` ≥85%; zero-role ≤3% on role-bearing fixtures; empty title ≤5%; wrong/missing name ≤5%; scanned recovery ≥90%; legacy DOC ≥90%; clean-subset style 100%; hard `failed` ≤2%.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/tests/fixtures/golden/manifest.json` | Versioned golden fixture list, expectations, scored flags |
| `backend/tests/fixtures/golden/build_golden_fixtures.py` | Builds synthetic PDFs/DOCX/DOC patterns into `tmp` or committed text fixtures |
| `backend/tests/fixtures/golden/cases/*.txt` (and generated binary under CI) | Anonymized layout patterns (Dice, paren-title, bullet-only, clean, scanned stubs) |
| `backend/eval_reports/baseline_case_map.md` | Wave 0 map: case ID → stage → expectation (no resume body) |
| `backend/app/services/source_evidence.py` | Detect readable employment evidence + required facts from source independently of parse |
| `backend/app/services/parse_confidence.py` | 0–1 confidence + reason codes from parse + source evidence |
| `backend/app/services/detailed_resume_parser.py` | Deterministic recoveries: Dice boundary, split headers, bullet-only preserve, name guards |
| `backend/app/services/structured_resume_store.py` | Carry parse_meta / unassigned experience / source locations into store |
| `backend/app/services/output_integrity.py` | Source-aware DOCX verify; blocking vs info severity; employment-evidence warning |
| `backend/app/services/llm_structure_repair.py` | Optional one-shot schema+source-checked repair |
| `backend/app/services/resume_generation_service.py` | Wire evidence → confidence → optional repair → integrity |
| `backend/app/services/docx_skeleton_service.py` | Capgemini hide empty Projects; style assertions helpers |
| `backend/app/services/pdf_parser.py` / `pdf_ocr.py` / `doc_converter.py` | Page-aware OCR merge; DOC convert; quarantine hook |
| `backend/app/api/routes/generate.py` | 422 intake errors; additive review warning shape |
| `backend/app/core/config.py` | `RESUME_LLM_PARSE_FALLBACK` default `False` |
| `backend/scripts/corpus_quality_eval.py` | `--golden`, gate numerators/denominators, failing IDs |
| `.github/workflows/ci.yml` | Golden gate job; fail PR on missed targets |
| `frontend/src/app/page.tsx` | Show blocking vs info warnings (additive parse) |
| `backend/tests/test_source_evidence.py` | Wave A/B evidence tests |
| `backend/tests/test_parse_confidence.py` | Confidence calibration |
| `backend/tests/test_corpus_parse_recovery.py` | Dice / paren-title / bullet-only / education-only |
| `backend/tests/test_output_integrity.py` | Extend severity + assignment checks |
| `backend/tests/test_intake_gate.py` | OCR / DOC / non-resume 422 paths |
| `backend/tests/test_llm_structure_repair.py` | Stubbed accept/reject/unavailable |
| `backend/tests/test_format_style_asserts.py` | Capgemini/Suresh/Aptino clean subset |

---

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

### Task 1: Source employment evidence (shared by Waves A–B)

**Files:**
- Create: `backend/app/services/source_evidence.py`
- Create: `backend/tests/test_source_evidence.py`
- Modify: (wire later in Task 2–3)

**Interfaces:**
- Produces:
  - `detect_employment_evidence(source_text: str) -> EmploymentEvidence`
  - `EmploymentEvidence(has_work_history: bool, reasons: list[str], snippet_refs: list[str])` — refs are opaque line indexes or section labels, never logged as content

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_source_evidence.py
from app.services.source_evidence import detect_employment_evidence

DICE = open(__file__.replace("test_source_evidence.py", "fixtures/golden/cases/dice_wrapper.txt"), encoding="utf-8").read()
EDU = open(__file__.replace("test_source_evidence.py", "fixtures/golden/cases/education_only.txt"), encoding="utf-8").read()
BULLET = open(__file__.replace("test_source_evidence.py", "fixtures/golden/cases/bullet_only.txt"), encoding="utf-8").read()

def test_dice_and_bullet_sources_flag_work_history():
    assert detect_employment_evidence(DICE).has_work_history is True
    assert detect_employment_evidence(BULLET).has_work_history is True

def test_education_only_has_no_work_history():
    assert detect_employment_evidence(EDU).has_work_history is False
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest backend/tests/test_source_evidence.py -v`  
Expected: FAIL (`ModuleNotFoundError` or missing symbol)

- [ ] **Step 3: Implement minimal detector**

```python
# backend/app/services/source_evidence.py
from __future__ import annotations
from dataclasses import dataclass, field
import re

_EXP_HEAD = re.compile(r"(?im)^(professional\s+)?(experience|work history|employment|job history)\b")
_JOBISH = re.compile(
    r"(?i)\b(20\d{2}|present)\b|\([^)]{3,60}\)\s*\d{1,2}/\d{2,4}|\b(inc|llc|corp|ltd)\b"
)

@dataclass
class EmploymentEvidence:
    has_work_history: bool
    reasons: list[str] = field(default_factory=list)
    snippet_refs: list[str] = field(default_factory=list)  # e.g. "line:42", "section:experience"

def detect_employment_evidence(source_text: str) -> EmploymentEvidence:
    lines = (source_text or "").splitlines()
    refs: list[str] = []
    reasons: list[str] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if _EXP_HEAD.match(line):
            refs.append(f"line:{i}")
            reasons.append("experience_heading")
        elif line.startswith(("•", "-", "*")) and _JOBISH.search(line):
            refs.append(f"line:{i}")
            reasons.append("dated_or_employerish_bullet")
        elif _JOBISH.search(line) and len(line) < 120:
            refs.append(f"line:{i}")
            reasons.append("jobish_line")
    # Prefer heading+content over sparse jobish noise
    has = ("experience_heading" in reasons and len(refs) >= 2) or reasons.count("dated_or_employerish_bullet") >= 3
    return EmploymentEvidence(has_work_history=has, reasons=sorted(set(reasons)), snippet_refs=refs[:20])
```

Calibrate against fixtures until education-only is false and Dice/bullet-only are true.

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest backend/tests/test_source_evidence.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/source_evidence.py backend/tests/test_source_evidence.py
git commit -m "feat: detect source employment evidence independent of parse"
```

---

### Task 2: Deterministic parse recovery (Wave A)

**Files:**
- Modify: `backend/app/services/detailed_resume_parser.py`
- Create: `backend/app/services/parse_confidence.py`
- Create: `backend/tests/test_corpus_parse_recovery.py`
- Create: `backend/tests/test_parse_confidence.py`
- Modify: `backend/app/services/structured_resume_store.py` (carry `parse_meta`, unassigned bullets)

**Interfaces:**
- Consumes: `detect_employment_evidence`
- Produces: `parse_resume_detailed` result includes:
  - `experience: list[dict]`
  - `unassigned_experience_bullets: list[str]` (optional)
  - `parse_meta: {confidence: float, reasons: list[str], llm_repaired: false}`
  - Keep existing top-level fields

- [ ] **Step 1: Write failing recovery tests from golden cases**

```python
# backend/tests/test_corpus_parse_recovery.py
from pathlib import Path
from app.services.detailed_resume_parser import parse_resume_detailed

CASES = Path(__file__).parent / "fixtures" / "golden" / "cases"

def _load(name: str) -> str:
    return (CASES / name).read_text(encoding="utf-8")

def test_dice_wrapper_recovers_roles_and_bullets():
    data = parse_resume_detailed(None, _load("dice_wrapper.txt"))
    assert len(data["experience"]) >= 1
    companies = " ".join(r.get("company") or "" for r in data["experience"])
    assert "Amazon" in companies or "amazon" in companies.lower()
    bullets = " ".join(b for r in data["experience"] for b in (r.get("description") or []))
    assert "onboarding" in bullets.lower()
    assert data.get("parse_meta", {}).get("confidence", 0) >= 0.55

def test_paren_title_split_header():
    data = parse_resume_detailed(None, _load("paren_title.txt"))
    assert len(data["experience"]) >= 1
    titles = [r.get("title") or "" for r in data["experience"]]
    assert any(t and "React Native" not in t for t in titles)  # title is real job title
    assert any("(" not in (t or "") for t in titles) or any("Engineer" in t for t in titles)

def test_bullet_only_preserves_text():
    data = parse_resume_detailed(None, _load("bullet_only.txt"))
    assigned = [b for r in data["experience"] for b in (r.get("description") or [])]
    unassigned = data.get("unassigned_experience_bullets") or []
    assert assigned or unassigned
    blob = " ".join(assigned + unassigned).lower()
    assert "delivered" in blob or "built" in blob  # substring from fixture
    if not data["experience"]:
        assert "expected_experience_missing" in (data.get("parse_meta") or {}).get("reasons", [])

def test_education_only_ok_without_roles():
    data = parse_resume_detailed(None, _load("education_only.txt"))
    assert data["experience"] == [] or len(data["experience"]) == 0
    assert data.get("education")
    reasons = (data.get("parse_meta") or {}).get("reasons") or []
    assert "expected_experience_missing" not in reasons
```

- [ ] **Step 2: Run — expect FAIL on new assertions**

Run: `pytest backend/tests/test_corpus_parse_recovery.py -v`

- [ ] **Step 3: Strengthen Dice boundary in `_strip_profile_cover` / `_prepare_resume_text`**

Reuse existing `_DICE_NOISE_RE` and `_strip_profile_cover`. Ensure wrapper labels are ignored **only inside the identified preamble**, and parsing resumes at the first real `SUMMARY`/`EXPERIENCE`/`Skills` block after chrome. Add a regression if current `DICE_LIKE` passes but golden `dice_wrapper.txt` fails — fix boundary detection, do not broaden noise stripping into real skills.

- [ ] **Step 4: Add paren-title / split header recognition in `_extract_experience`**

Support at minimum:

1. Company line, then `(Title) MM/YY - Present` (or en-dash)
2. `Company — Title — Dates` on one line
3. Explicit title under Experience followed by bullets

Attach following bullets to that role using section boundaries. Prefer source order.

Sketch (integrate into existing loop; do not replace the whole extractor):

```python
_PAREN_TITLE = re.compile(
    r"^\(([^)]{2,80})\)\s*(\d{1,2}/\d{2,4}|\w+\s+\d{4})\s*[-–—]\s*(Present|\d{1,2}/\d{2,4}|\w+\s+\d{4})$",
    re.I,
)
```

When current company is set and line matches `_PAREN_TITLE`, set `title` and `duration` on the open role.

- [ ] **Step 5: Bullet-only fallback**

After normal extraction, if `not experience` and `detect_employment_evidence(text).has_work_history`:

- Collect bullets under experience-ish region into `unassigned_experience_bullets`
- If a single employer/date line exists, create one structured role and attach bullets
- Else leave unassigned and add parse reason `ambiguous_role_assignment`

- [ ] **Step 6: Name / title guards**

In `_extract_name` / title validation: reject tech-token names (`React Native.`, framework lists). Prefer person-like header evidence. Technology labels used as skills stay in skills.

- [ ] **Step 7: Implement `parse_confidence.py` and attach `parse_meta`**

```python
# backend/app/services/parse_confidence.py
from __future__ import annotations
from app.services.source_evidence import EmploymentEvidence, detect_employment_evidence

def score_parse(data: dict, source_text: str) -> dict:
    evidence = detect_employment_evidence(source_text)
    roles = [r for r in (data.get("experience") or []) if isinstance(r, dict)]
    reasons: list[str] = []
    empty_titles = sum(1 for r in roles if not (r.get("title") or "").strip())
    name = (data.get("name") or "").strip()
    confidence = 1.0
    if evidence.has_work_history and not roles and not (data.get("unassigned_experience_bullets") or []):
        reasons.append("expected_experience_missing")
        confidence -= 0.5
    elif evidence.has_work_history and not roles:
        reasons.append("ambiguous_role_assignment")
        confidence -= 0.35
    if roles and empty_titles / max(1, len(roles)) >= 0.5:
        reasons.append("source_backed_titles_unresolved")
        confidence -= 0.25
    if not name or name.lower() in {"react native", "react native."}:
        reasons.append("identity_ambiguous")
        confidence -= 0.2
    confidence = max(0.0, min(1.0, confidence))
    return {
        "confidence": confidence,
        "reasons": reasons,
        "llm_repaired": False,
        "employment_evidence": {
            "has_work_history": evidence.has_work_history,
            "reasons": evidence.reasons,
        },
    }
```

At end of `parse_resume_detailed`, set `result["parse_meta"] = score_parse(result, resume_text)`.

- [ ] **Step 8: Carry meta through structured store**

Ensure `structured_resume_store` / store builder preserves `parse_meta` and `unassigned_experience_bullets` on the store dict used by integrity (do not render unassigned as a fake job without review).

- [ ] **Step 9: Run recovery + confidence tests**

```bash
pytest backend/tests/test_corpus_parse_recovery.py backend/tests/test_parse_confidence.py backend/tests/test_resume_reading.py -v
```

Expected: PASS (existing Dice/numeric tests still green)

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/detailed_resume_parser.py backend/app/services/parse_confidence.py backend/app/services/structured_resume_store.py backend/tests/test_corpus_parse_recovery.py backend/tests/test_parse_confidence.py
git commit -m "feat: recover Dice, split-header, and bullet-only experience in faithful parse"
```

**Exit check:** Readable Dice and split-header fixtures recover expected jobs/bullets. Bullet-only evidence survives; unresolved assignments → review reasons. Education-only and clean controls pass. Deterministic path ≤3% zero-role on labeled role-bearing Wave A fixtures.

---

### Task 3: Source-aware DOCX verification (Wave B)

**Files:**
- Modify: `backend/app/services/output_integrity.py`
- Modify: `backend/app/services/resume_generation_service.py` (`_integrity_report` pass parse_meta / evidence)
- Modify: `backend/app/api/routes/generate.py` (additive warning objects if present)
- Modify: `frontend/src/app/page.tsx` (accept string or `{severity,code,message}`)
- Modify: `backend/tests/test_output_integrity.py`
- Modify: `backend/scripts/corpus_quality_eval.py` (label raw `line_cov` vs `checks.source_lines`)

**Interfaces:**
- Extends `IntegrityReport`:
  - `warnings` may be `list[str] | list[dict]` — prefer structured dicts with fallback stringification for header JSON
  - Structured: `{severity: "blocking"|"info", code: str, message: str}`
- Status rules per design: informational-only → `passed`; unresolved source gaps → `needs_review`; material render/assignment errors → `failed`

- [ ] **Step 1: Write failing integrity tests**

```python
def test_source_lines_alone_do_not_force_needs_review(store_with_full_fields, docx_full, source_with_extra_wrap_lines):
    report = check_output_integrity(store_with_full_fields, docx_full, source_text=source_with_extra_wrap_lines)
    assert report.status == "passed"
    assert any(getattr(w, "get", lambda k, d=None: None)("severity") == "info" or "line" in str(w).lower() for w in report.warnings) or report.checks.get("source_lines")

def test_zero_roles_with_employment_evidence_needs_review(empty_exp_store, docx_bytes, source_with_experience_section):
    report = check_output_integrity(
        empty_exp_store,
        docx_bytes,
        source_text=source_with_experience_section,
        parse_meta={"employment_evidence": {"has_work_history": True}, "reasons": ["expected_experience_missing"]},
    )
    assert report.status == "needs_review"
    assert any("experience" in str(w).lower() for w in report.warnings)

def test_bullet_assigned_to_wrong_employer_fails_or_reviews(store, docx_bytes):
    # Fixture: bullet text unique to Role A appears only under Role B heading in DOCX
    report = check_output_integrity(store, docx_bytes, source_text=..., verify_role_assignment=True)
    assert report.status in {"needs_review", "failed"}
```

Adapt to existing `_docx` helpers in `test_output_integrity.py`.

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest backend/tests/test_output_integrity.py -v`

- [ ] **Step 3: Implement severity split and employment-evidence check**

In `check_output_integrity`:

1. Add kwargs: `parse_meta: dict | None = None`, `verify_role_assignment: bool = True`
2. Build structured warnings; keep messages recruiter-safe (counts/codes, no resume body)
3. Treat `source_lines` misses as **info** unless the missing line is classified as carrying a required fact (employer/title/date/bullet substring from store or evidence)
4. If `parse_meta.employment_evidence.has_work_history` and store has zero roles and no preserved unassigned bullets in output → blocking `expected_experience_missing`
5. OCR used / references omitted / approved label remaps → info; do not alone force `needs_review`
6. Recompute status: all blocking OK → `passed`; soft gaps → `needs_review`; core field ratio fail or wrong assignment → `failed`

Update `IntegrityReport` serialization used by generate headers:

```python
def warning_payload(report: IntegrityReport) -> list:
    out = []
    for w in report.warnings[:10]:
        if isinstance(w, dict):
            out.append(w)
        else:
            out.append({"severity": "blocking" if report.status != "passed" else "info", "code": "legacy", "message": str(w)})
    return out
```

Frontend: if element is string, show as today; if object, show `message` and style by `severity`.

- [ ] **Step 4: Role-scoped bullet verification**

For each role in store, check that its bullets appear in the DOCX near that role’s company/title (windowed search in normalized DOCX text). Flag cross-assignment.

- [ ] **Step 5: Label dual coverage metrics in eval script**

In `corpus_quality_eval.py` report JSON/MD:

- `raw_line_cov` = existing `source_line_coverage` ratio
- `integrity_source_lines` = `checks.source_lines`

Do not conflate them. Baseline medians (~84.8% raw) stay diagnostic.

- [ ] **Step 6: Run tests + spot UI paths**

```bash
pytest backend/tests/test_output_integrity.py -v
```

Manually exercise frontend with info-only, needs_review, failed (or component test if present).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/output_integrity.py backend/app/services/resume_generation_service.py backend/app/api/routes/generate.py frontend/src/app/page.tsx backend/tests/test_output_integrity.py backend/scripts/corpus_quality_eval.py
git commit -m "feat: make integrity review actionable with source-aware severity"
```

**Exit check:** Dropped bullet / wrong job / changed factual number flagged. Harmless heading/wrap passes. Visible work evidence + zero jobs → specific experience warning.

---

### Task 4: Intake — OCR, legacy DOC, quarantine (Wave C)

**Files:**
- Modify: `backend/app/services/pdf_parser.py`, `pdf_ocr.py`, `doc_converter.py`
- Modify: `backend/app/api/routes/generate.py` (422 messages)
- Create: `backend/tests/test_intake_gate.py`
- Extend golden fixtures: scanned stub, mixed PDF, `.doc`, non-resume, sparse valid resume

**Interfaces:**
- `extraction_meta`: keep `ocr_pages`; ensure `ocr_missing_pages`, `doc_converted`, optional `quarantine_reason`
- Human-readable page refs in warnings (1-based)

- [ ] **Step 1: Failing intake tests**

```python
def test_ocr_unavailable_whole_scan_returns_clear_error(monkeypatch):
    # simulate image-only PDF + ocr_available False → 422 path / OcrUnavailableError
    ...

def test_mixed_pdf_partial_draft_marks_missing_pages():
    meta = {"ocr_pages": [1], "ocr_missing_pages": [2]}
    # integrity info/blocking per Wave B rules
    ...

def test_doc_missing_libreoffice_422(monkeypatch):
    ...

def test_non_resume_quarantine_422():
    ...

def test_sparse_valid_resume_not_quarantined():
    ...
```

- [ ] **Step 2: Implement / verify OCR merge in page order**

Reuse `pdf_ocr.py`. Merge readable + OCR text in source order. Track recovered vs still-unreadable pages separately. Confirm Tesseract present in runtime docs / CI image for golden OCR fixtures.

- [ ] **Step 3: Legacy `.doc`**

`doc_converter.py`: convert via LibreOffice; on failure → HTTP 422 suggesting `.docx` upload.

- [ ] **Step 4: Non-resume quarantine**

Heuristic gate (certificates, I-94, travel history) → 422 with actionable reason. Must not reject education-only or sparse but valid resumes.

- [ ] **Step 5: Run tests**

```bash
pytest backend/tests/test_intake_gate.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pdf_parser.py backend/app/services/pdf_ocr.py backend/app/services/doc_converter.py backend/app/api/routes/generate.py backend/tests/test_intake_gate.py
git commit -m "feat: harden intake for OCR, legacy DOC, and non-resume rejection"
```

**Exit check:** Image-only and mixed PDF exercise success + partial/unavailable paths. `.doc` exercises convert + missing-converter. Scored OCR/DOC fixtures ≥90% with dependencies enabled.

---

### Task 5: Optional LLM structure repair (Wave D)

**Files:**
- Create: `backend/app/services/llm_structure_repair.py`
- Modify: `backend/app/core/config.py` — `RESUME_LLM_PARSE_FALLBACK: bool = False`
- Modify: `backend/app/services/resume_generation_service.py` — call once when eligible
- Create: `backend/tests/test_llm_structure_repair.py`

**Interfaces:**
- `maybe_repair_parse(source_text: str, parsed: dict, *, client=...) -> dict`  
  Returns parse dict; sets `parse_meta.llm_repaired=True` only on accepted repair
- Eligibility: `(roles==0 and evidence.has_work_history) or confidence < 0.55 or empty_title_ratio >= 0.5` with source-backed titles unresolved
- At most once per generation; flag default **off**

- [ ] **Step 1: Stubbed failing tests**

```python
def test_accepts_schema_valid_source_backed_repair(monkeypatch): ...
def test_rejects_fabricated_employer(monkeypatch): ...
def test_rejects_bullet_wrong_employer(monkeypatch): ...
def test_unavailable_client_keeps_deterministic(monkeypatch): ...
def test_education_only_not_eligible(): ...
```

- [ ] **Step 2: Implement repair with source presence checks**

Validate JSON against store schema. Every name/company/title/date/bullet must normalize-match source text. Existing verified facts must survive. On reject/timeout → deterministic draft unchanged.

- [ ] **Step 3: Wire in generation after parse, before store finalize**

Only if `settings.RESUME_LLM_PARSE_FALLBACK` is True.

- [ ] **Step 4: Run stub tests; ensure golden CI path leaves flag off**

```bash
pytest backend/tests/test_llm_structure_repair.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/llm_structure_repair.py backend/app/core/config.py backend/app/services/resume_generation_service.py backend/tests/test_llm_structure_repair.py
git commit -m "feat: add optional source-checked LLM parse repair fallback"
```

**Exit check:** Stubbed accept/reject/wrong-association/unavailable/education-only covered. Scored CI remains deterministic.

---

### Task 6: Client format behavior (Wave E)

**Files:**
- Modify: `backend/app/services/docx_skeleton_service.py`
- Create: `backend/tests/test_format_style_asserts.py`
- Use: `backend/scripts/spotcheck_formats.py` (manual)

**Interfaces:**
- Capgemini: hide “Summary of Projects” when no source-backed projects
- Style asserts: name_align, font_family, section_order, labels

- [ ] **Step 1: Failing style tests on clean subset fixtures**

```python
def test_capgemini_hides_empty_projects(clean_store_no_projects): ...
def test_capgemini_name_right_avenir(clean_docx_bytes): ...
def test_suresh_name_center_arial(clean_docx_bytes): ...
def test_content_same_expectations_all_formats(golden_clean_id): ...
```

- [ ] **Step 2: Implement empty Projects hide + assert helpers**

- [ ] **Step 3: Run tests + optional spotcheck**

```bash
pytest backend/tests/test_format_style_asserts.py -v
python scripts/spotcheck_formats.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/docx_skeleton_service.py backend/tests/test_format_style_asserts.py
git commit -m "feat: assert Capgemini/Suresh style and hide empty projects"
```

**Exit check:** Clean-subset style 100%; source content under intended sections for all three formats.

---

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
