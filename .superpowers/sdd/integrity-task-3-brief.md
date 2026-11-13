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

