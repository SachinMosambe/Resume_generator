### Task 4: Integrity recovery module (trigger, recover, merge, prefer)

**Files:**
- Create: `backend/app/services/integrity_recovery.py`
- Modify: `backend/tests/test_integrity_recovery.py`

**Interfaces:**
- Consumes:
  - `IntegrityReport` from `output_integrity`
  - `list_missing_hard_source_lines`
  - `extract_experience`, `source_lines`, `_default_client` (or public client hook) from `llm_line_extractor`
  - `detect_employment_evidence` from `source_evidence`
  - `settings` for caps
- Produces:
  - `recovery_enabled() -> bool`
  - `should_recover(report: IntegrityReport, store: dict, source_text: str) -> bool`
  - `hard_source_miss_count(report: IntegrityReport) -> int`
  - `has_wrong_role(report: IntegrityReport) -> bool`
  - `recover_store(source_text: str, store: dict, report: IntegrityReport, *, client=None) -> tuple[dict, dict]`
    - returns `(new_store, meta)` where meta includes `used`, `llm_calls`, `error`, `missing_in`, `missing_out_estimate`
  - `prefer_recovered(before: IntegrityReport, after: IntegrityReport) -> bool`

- [ ] **Step 1: Write failing tests**

```python
from app.services.output_integrity import IntegrityReport, BLOCKING
from app.services import integrity_recovery as ir

def test_should_recover_on_blocking_source_lines():
    report = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"ok": False, "hard": 3, "soft": 1, "changed_numbers": 0}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "3 line(s)..."}],
    )
    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "Acme\n• Built things carefully here.\n") is True

def test_should_not_recover_on_clean_pass():
    report = IntegrityReport(status="passed", checks={"source_lines": {"ok": True, "hard": 0}}, warnings=[])
    assert ir.should_recover(report, {"experience": [{"company": "Acme"}]}, "x") is False

def test_should_recover_zero_roles_with_work_evidence():
    report = IntegrityReport(status="needs_review", checks={}, warnings=[])
    source = "Experience\nAcme Corp Engineer 2020-2021\n• Shipped the billing platform for customers.\n"
    assert ir.should_recover(report, {"experience": []}, source) is True

def test_prefer_recovered_only_when_hard_drops_without_new_wrong_role():
    before = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"hard": 5}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "x"}],
    )
    after_better = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"hard": 1}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "x"}],
    )
    after_worse_role = IntegrityReport(
        status="failed",
        checks={"source_lines": {"hard": 0}},
        warnings=[{"severity": BLOCKING, "code": "bullet_wrong_role", "message": "x"}],
    )
    assert ir.prefer_recovered(before, after_better) is True
    assert ir.prefer_recovered(before, after_worse_role) is False

def test_recover_store_merges_only_grounded_roles():
    # Fake client returns roles citing real lines; invented company must not appear.
    source = "\n".join([
        "Casey Example",
        "Experience",
        "Acme Corp",
        "Engineer 2020-2022",
        "• Shipped the onboarding checklist for new analysts in 2021.",
    ])
    store = {"experience": [], "name": "Casey Example", "raw_text": source}
    report = IntegrityReport(
        status="needs_review",
        checks={"source_lines": {"hard": 2}},
        warnings=[{"severity": BLOCKING, "code": "source_lines", "message": "x"}],
    )
    roles_payload = {
        "roles": [{
            "title": {"line": 4, "text": "Engineer 2020-2022"},
            "company": {"line": 3, "text": "Acme Corp"},
            "dates": {"line": 4, "text": "2020-2022"},
            "header_lines": [3, 4],
            "content": [[5, 5]],
        }]
    }
    # Adapt to whatever fake_client shape extract_experience expects (mirror test_llm_line_extractor).
    new_store, meta = ir.recover_store(source, store, report, client=/* fake */)
    assert meta.get("used") is True
    assert any(r.get("company") == "Acme Corp" for r in new_store.get("experience") or [])
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

Run: `cd backend && python -m pytest tests/test_integrity_recovery.py -v`

- [ ] **Step 3: Implement `integrity_recovery.py`**

```python
def recovery_enabled() -> bool:
    return bool(getattr(settings, "RESUME_INTEGRITY_RECOVERY", False)) and bool(settings.AWS_BEARER_TOKEN_BEDROCK)

def hard_source_miss_count(report: IntegrityReport) -> int:
    return int(((report.checks or {}).get("source_lines") or {}).get("hard") or 0)

def has_wrong_role(report: IntegrityReport) -> bool:
    return any(
        (w.get("severity") == BLOCKING and w.get("code") in {"bullet_wrong_role", "role_assignment"})
        for w in (report.warnings or [])
        if isinstance(w, dict)
    )

def should_recover(report, store, source_text) -> bool:
    if not recovery_enabled():
        return False
    if hard_source_miss_count(report) > 0 or has_wrong_role(report):
        return True
    roles = store.get("experience") or []
    if not roles and detect_employment_evidence(source_text).has_work_history:
        return True
    return False

def prefer_recovered(before, after) -> bool:
    if has_wrong_role(after) and not has_wrong_role(before):
        return False
    if has_wrong_role(after) and has_wrong_role(before):
        # still allow if hard misses drop substantially
        pass
    return hard_source_miss_count(after) < hard_source_miss_count(before) or (
        has_wrong_role(before) and not has_wrong_role(after)
        and hard_source_miss_count(after) <= hard_source_miss_count(before)
    )

def recover_store(source_text, store, report, *, client=None) -> tuple[dict, dict]:
    # 1) missing = list_missing_hard_source_lines(source, source, store) using output from report context
    #    Caller should pass output_text OR recover_store accepts output_text param.
    # 2) Map missing strings → 1-based line numbers via source_lines(source_text)
    # 3) extract_experience(source_text, call, hints=line_numbers) with timeout/max calls from settings
    # 4) If lumped vs existing strong rule roles, abort used=False
    # 5) Merge: replace experience when recovered roles non-empty and improve coverage;
    #    append unassigned bullets for leftover grounded lines
    # 6) Return copy of store + meta for parse_meta["integrity_recovery"]
```

Add `output_text: str` parameter to `recover_store` so hard-line listing uses the generated DOCX text:

```python
def recover_store(
    source_text: str,
    store: dict,
    report: IntegrityReport,
    output_text: str,
    *,
    client=None,
) -> tuple[dict, dict]:
```

Respect `RESUME_INTEGRITY_RECOVERY_MAX_CALLS` and `RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS`. On any error: return `(store, {"used": False, "error": ...})`.

- [ ] **Step 4: Run `tests/test_integrity_recovery.py -v` — PASS**

- [ ] **Step 5: Commit** (when user asks)

```bash
git commit -m "feat: add grounded integrity recovery helpers"
```

---

