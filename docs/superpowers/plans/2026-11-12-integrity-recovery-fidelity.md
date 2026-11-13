# Integrity-Driven Recovery Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reach ≥95% of a fixed 60–80 corpus sample with production settings finishing as `passed` or light `needs_review` with no blocking `source_lines` / wrong-role failures, by adding one grounded post-integrity recovery loop (content fidelity only; integrity thresholds unchanged).

**Architecture:** After the first DOCX + integrity report, if recovery triggers, list missing hard source lines, re-run grounded Bedrock experience extraction with those line numbers as hints, merge verbatim-only into the store, re-render once, and keep the draft whose integrity is better. Also accept non-lumped LLM roles when the rule parse has zero roles.

**Tech Stack:** Existing FastAPI / `ResumeGenerationService` / `llm_line_extractor` / `output_integrity` / Bedrock / pytest / `prod_hard_resume_retest.py` + corpus eval harness.

## Global Constraints

- Faithful mode; never invent employers, titles, dates, bullets, or metrics.
- Integrity rules/thresholds in `output_integrity.py` stay unchanged this wave.
- Recovery: at most one re-render; cap Bedrock recovery calls/time (`RESUME_INTEGRITY_RECOVERY_*`).
- Prefer recovered draft only if hard `source_lines` decrease and no new wrong-role / `bullet_wrong_role`.
- Golden CI keeps LLM + recovery off (deterministic).
- No real candidate PII committed; recruiter-safe warnings only.
- Spec: `docs/superpowers/specs/2026-11-12-integrity-recovery-fidelity-design.md`.

## File map

| File | Responsibility |
|------|----------------|
| `backend/app/core/config.py` | New recovery settings |
| `backend/app/services/output_integrity.py` | Export listing of missing hard source lines (counts already exist; need the lines) |
| `backend/app/services/llm_line_extractor.py` | 0-role + non-lumped LLM accept tweak |
| `backend/app/services/integrity_recovery.py` | **Create:** trigger, recover, merge, prefer |
| `backend/app/services/resume_generation_service.py` | Wire recovery after first integrity; second render |
| `backend/tests/test_output_integrity.py` | Tests for hard-line listing |
| `backend/tests/test_llm_line_extractor.py` | Tests for 0-role accept |
| `backend/tests/test_integrity_recovery.py` | **Create:** recovery unit tests |
| `backend/scripts/prod_hard_resume_retest.py` | Ensure recovery settings load for measurement |
| `backend/.env.example` | Document new flags |

---

### Task 1: List missing hard source lines (integrity helper)

**Files:**
- Modify: `backend/app/services/output_integrity.py`
- Modify: `backend/tests/test_output_integrity.py` (create if missing; else extend)

**Interfaces:**
- Consumes: existing `_classify_source_lines` logic / `_norm` / fact collection used in `check_output_integrity`
- Produces: `list_missing_hard_source_lines(source_text: str, output_text: str, store: dict[str, Any]) -> list[str]` — ordered unique raw source lines that would increment `hard` today

- [ ] **Step 1: Write the failing test**

```python
def test_list_missing_hard_source_lines_finds_absent_bullet():
    source = (
        "Casey Example\n"
        "Experience\n"
        "Acme Corp — Engineer — 2020-2022\n"
        "• Shipped the onboarding checklist for new analysts in 2021.\n"
        "• Closed the monthly books for a small team in 2022.\n"
    )
    # Output has name + employer but drops the onboarding bullet line content
    output = "Casey Example\nAcme Corp\nEngineer\nClosed the monthly books for a small team in 2022.\n"
    store = {
        "name": "Casey Example",
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "duration": "2020-2022",
                "description": [
                    "Shipped the onboarding checklist for new analysts in 2021.",
                    "Closed the monthly books for a small team in 2022.",
                ],
            }
        ],
    }
    from app.services.output_integrity import list_missing_hard_source_lines

    missing = list_missing_hard_source_lines(source, output, store)
    assert any("onboarding checklist" in m.lower() for m in missing)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_output_integrity.py::test_list_missing_hard_source_lines_finds_absent_bullet -v`  
Expected: FAIL (`list_missing_hard_source_lines` not defined or empty list)

- [ ] **Step 3: Implement helper**

Refactor `_classify_source_lines` so the hard-line decision is shared, then:

```python
def list_missing_hard_source_lines(source_text: str, output_text: str, store: dict[str, Any]) -> list[str]:
    """Return raw source lines that count as integrity hard misses (fact-bearing, absent)."""
    # Build facts the same way check_output_integrity does for source_lines.
    # Reuse the same skip/date/min_words/min_share rules as _classify_source_lines.
    # Append the original stripped line when it would increment hard; de-dupe preserving order.
```

Do **not** change when a line counts as hard vs soft (thresholds unchanged).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_output_integrity.py::test_list_missing_hard_source_lines_finds_absent_bullet -v`  
Expected: PASS

- [ ] **Step 5: Commit** (when user asks to commit)

```bash
git add backend/app/services/output_integrity.py backend/tests/test_output_integrity.py
git commit -m "feat: list integrity hard-missing source lines for recovery"
```

---

### Task 2: Config flags for integrity recovery

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example` (if present; else skip file create unless repo already has it)
- Test: `backend/tests/test_integrity_recovery.py` (defaults assertion; create file)

**Interfaces:**
- Produces settings fields:
  - `RESUME_INTEGRITY_RECOVERY: bool = True`
  - `RESUME_INTEGRITY_RECOVERY_MAX_CALLS: int = 4`
  - `RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS: float = 45.0`
- Runtime enable: recovery runs only when `RESUME_INTEGRITY_RECOVERY` and `AWS_BEARER_TOKEN_BEDROCK` are set (mirror line-extract `enabled()` pattern)

- [ ] **Step 1: Write failing test**

```python
from app.core.config import Settings

def test_integrity_recovery_settings_defaults():
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY"].default is True
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_MAX_CALLS"].default == 4
    assert Settings.model_fields["RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS"].default == 45.0
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/test_integrity_recovery.py::test_integrity_recovery_settings_defaults -v`

- [ ] **Step 3: Add fields to `Settings` in `config.py`**

```python
RESUME_INTEGRITY_RECOVERY: bool = True
RESUME_INTEGRITY_RECOVERY_MAX_CALLS: int = 4
RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS: float = 45.0
```

Document in `.env.example` with one-line comments matching the spec.

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit** (when user asks)

```bash
git commit -m "feat: add RESUME_INTEGRITY_RECOVERY settings"
```

---

### Task 3: First-pass line extract — accept non-lumped LLM roles when rule has 0 roles

**Files:**
- Modify: `backend/app/services/llm_line_extractor.py` (`apply_line_extraction` better/used logic near the `better = ...` block)
- Modify: `backend/tests/test_llm_line_extractor.py`

**Interfaces:**
- Consumes: existing `apply_line_extraction`, `_is_lumped`, `_attempt_score`
- Produces: when `rule_roles` is empty and `result.roles` non-empty and not lumped → `info["used"] is True` even if coverage gate failed

- [ ] **Step 1: Write failing test**

```python
def test_apply_uses_llm_roles_when_rule_has_zero_even_if_gate_weak(monkeypatch):
    # Rule parse: no experience. Fake client returns one grounded role.
    # Force a weak coverage path if needed by using sparse content lines,
    # but roles must still be applied when not lumped.
    parsed = {"experience": [], "parse_meta": {}}
    # Use RESUME fixture + GOOD_ROLES-style client from this file.
    monkeypatch.setenv("RESUME_LLM_LINE_EXTRACT", "true")
    # Call apply_line_extraction with fake client that returns GOOD_ROLES
    out = apply_line_extraction(RESUME, parsed, client=fake_client(GOOD_ROLES))
    assert out["parse_meta"]["line_extract"]["used"] is True
    assert len(out["experience"]) >= 1
```

If current code already passes this for GOOD_ROLES (because coverage beats empty rule), add a second case where `coverage` is mediocre but roles exist and lumped is False — monkeypatch `_experience_coverage` to return `0.5` for LLM and `0.0` for rule, and assert still used when rule_roles empty.

- [ ] **Step 2: Run — expect FAIL on the mediocre-coverage empty-rule case**

- [ ] **Step 3: Minimal change in `apply_line_extraction`**

```python
better = bool(result.roles) and not lumped and (
    not rule_roles  # NEW: empty rule → take non-lumped LLM roles
    or result.coverage > rule_cov + 0.02
    or (result.coverage >= rule_cov - 0.02 and _role_quality(result.roles) > _role_quality(rule_roles))
)
```

Keep lumped rejection. Do not remove coverage comparison for non-empty rule parses.

- [ ] **Step 4: Run `tests/test_llm_line_extractor.py -v` — all PASS**

- [ ] **Step 5: Commit** (when user asks)

```bash
git commit -m "fix: use non-lumped LLM roles when rule parse finds zero jobs"
```

---

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

### Task 5: Wire recovery into `ResumeGenerationService.generate`

**Files:**
- Modify: `backend/app/services/resume_generation_service.py` (after first `self.last_report = self._integrity_report(...)` around the generate method, before upload)
- Test: `backend/tests/test_integrity_recovery.py` (service-level test with stubs) **or** a focused new test that mocks render/integrity

**Interfaces:**
- Consumes: `integrity_recovery.should_recover`, `recover_store`, `prefer_recovered`
- Produces: optional second render; `parse_meta.integrity_recovery` on store; `self.last_report` = chosen draft’s report

- [ ] **Step 1: Write failing integration-style unit test**

```python
def test_generate_runs_recovery_when_first_integrity_has_hard_misses(monkeypatch):
    # Build a minimal service test:
    # - monkeypatch _get_detailed_resume_data to return fixed detailed_data with raw text
    # - monkeypatch _render_with_format_strategy to return simple docx bytes (python-docx Document saved to bytes)
    # - first integrity: hard>0; after recover_store mutates experience so second integrity hard==0
    # Assert recover_store called once and last_report reflects preferred draft.
```

If full `generate()` is too heavy to stub, test a new internal method instead:

```python
def _maybe_integrity_recover(self, candidate, client_format, store, document, format_metadata,
                             header_logos, footer_logos, docx_bytes, report) -> tuple[bytes, IntegrityReport, dict]:
    ...
```

And unit-test `_maybe_integrity_recover` directly.

- [ ] **Step 2: Run — expect FAIL**

- [ ] **Step 3: Implement wiring**

Pseudocode at end of successful first render:

```python
report = self._integrity_report(...)
recovery_meta = {"used": False}
source_text = (candidate.extracted_data or {}).get("raw_text") or ""
output_text = # extract text from docx_bytes (reuse existing docx paragraph join helper if present)

if integrity_recovery.should_recover(report, store, source_text):
    new_store, recovery_meta = integrity_recovery.recover_store(
        source_text, store, report, output_text
    )
    if recovery_meta.get("used"):
        # rebuild detailed_data/document from new_store (apply_store_to_candidate_data +
        # _generate_professional_document + attach_unassigned_experience)
        # re-render once via _render_with_format_strategy
        report2 = self._integrity_report(new_store, docx2, document2, ...)
        if integrity_recovery.prefer_recovered(report, report2):
            store, docx_bytes, report, document = new_store, docx2, report2, document2
            candidate.extracted_data["structured_resume"] = store
        recovery_meta["preferred"] = integrity_recovery.prefer_recovered(report, report2)

# always record meta
store.setdefault("parse_meta", {})["integrity_recovery"] = recovery_meta
self.last_report = report
# then existing upload_bytes_to_key(...)
```

Never raise solely because recovery failed. Cap must be enforced inside `recover_store`.

- [ ] **Step 4: Run recovery + line-extractor + integrity tests — PASS**

Run: `cd backend && python -m pytest tests/test_integrity_recovery.py tests/test_llm_line_extractor.py tests/test_output_integrity.py -v`

- [ ] **Step 5: Commit** (when user asks)

```bash
git commit -m "feat: run one grounded integrity recovery pass before upload"
```

---

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

### Task 7: Spec coverage self-check (planner / implementer)

- [ ] Confirm each spec requirement maps to a task:

| Spec requirement | Task |
|------------------|------|
| Post-integrity recovery loop, one re-render | 4, 5 |
| Trigger: hard source_lines / zero roles / wrong-role | 4 |
| Grounded cite/copy only | 4 |
| Prefer only if integrity improves | 4, 5 |
| First-pass 0-role LLM accept | 3 |
| Config flags + CI off | 2, 6 |
| ≥95% on 60–80 sample measurement | 6 |
| Integrity thresholds unchanged | 1 (list only), no edits to pass/fail math |
| Never invent text | 4 tests |

- [ ] If corpus sample is still &lt;95% after Task 6, **do not** loosen integrity. File failing IDs and stop for a follow-up wave (parser/OCR), per spec Risks.

---

## Self-review (plan vs spec)

1. **Spec coverage:** Recovery flow, triggers, merge/prefer, 0-role tweak, config, tests, measurement, golden-off — all tasked. OCR/LibreOffice out of scope — noted.
2. **Placeholders:** None intentional; implementers must fill fake_client wiring using the existing `test_llm_line_extractor.fake_client` pattern.
3. **Types:** `recover_store(..., output_text: str) -> tuple[dict, dict]` used consistently in Tasks 4–5; `prefer_recovered(before, after) -> bool` consistent.

## Execution handoff

Plan saved to `docs/superpowers/plans/2026-11-12-integrity-recovery-fidelity.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?
