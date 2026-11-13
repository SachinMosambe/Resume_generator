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

