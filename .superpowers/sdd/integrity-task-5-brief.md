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

