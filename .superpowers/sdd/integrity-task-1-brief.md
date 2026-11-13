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

