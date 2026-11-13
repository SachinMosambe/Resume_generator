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

