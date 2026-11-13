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

