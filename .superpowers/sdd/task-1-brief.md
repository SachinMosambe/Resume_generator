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

