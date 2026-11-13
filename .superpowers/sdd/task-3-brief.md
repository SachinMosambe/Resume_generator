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

