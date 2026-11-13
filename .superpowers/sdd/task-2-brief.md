### Task 2: Deterministic parse recovery (Wave A)

**Files:**
- Modify: `backend/app/services/detailed_resume_parser.py`
- Create: `backend/app/services/parse_confidence.py`
- Create: `backend/tests/test_corpus_parse_recovery.py`
- Create: `backend/tests/test_parse_confidence.py`
- Modify: `backend/app/services/structured_resume_store.py` (carry `parse_meta`, unassigned bullets)

**Interfaces:**
- Consumes: `detect_employment_evidence`
- Produces: `parse_resume_detailed` result includes:
  - `experience: list[dict]`
  - `unassigned_experience_bullets: list[str]` (optional)
  - `parse_meta: {confidence: float, reasons: list[str], llm_repaired: false}`
  - Keep existing top-level fields

- [ ] **Step 1: Write failing recovery tests from golden cases**

```python
# backend/tests/test_corpus_parse_recovery.py
from pathlib import Path
from app.services.detailed_resume_parser import parse_resume_detailed

CASES = Path(__file__).parent / "fixtures" / "golden" / "cases"

def _load(name: str) -> str:
    return (CASES / name).read_text(encoding="utf-8")

def test_dice_wrapper_recovers_roles_and_bullets():
    data = parse_resume_detailed(None, _load("dice_wrapper.txt"))
    assert len(data["experience"]) >= 1
    companies = " ".join(r.get("company") or "" for r in data["experience"])
    assert "Amazon" in companies or "amazon" in companies.lower()
    bullets = " ".join(b for r in data["experience"] for b in (r.get("description") or []))
    assert "onboarding" in bullets.lower()
    assert data.get("parse_meta", {}).get("confidence", 0) >= 0.55

def test_paren_title_split_header():
    data = parse_resume_detailed(None, _load("paren_title.txt"))
    assert len(data["experience"]) >= 1
    titles = [r.get("title") or "" for r in data["experience"]]
    assert any(t and "React Native" not in t for t in titles)  # title is real job title
    assert any("(" not in (t or "") for t in titles) or any("Engineer" in t for t in titles)

def test_bullet_only_preserves_text():
    data = parse_resume_detailed(None, _load("bullet_only.txt"))
    assigned = [b for r in data["experience"] for b in (r.get("description") or [])]
    unassigned = data.get("unassigned_experience_bullets") or []
    assert assigned or unassigned
    blob = " ".join(assigned + unassigned).lower()
    assert "delivered" in blob or "built" in blob  # substring from fixture
    if not data["experience"]:
        assert "expected_experience_missing" in (data.get("parse_meta") or {}).get("reasons", [])

def test_education_only_ok_without_roles():
    data = parse_resume_detailed(None, _load("education_only.txt"))
    assert data["experience"] == [] or len(data["experience"]) == 0
    assert data.get("education")
    reasons = (data.get("parse_meta") or {}).get("reasons") or []
    assert "expected_experience_missing" not in reasons
```

- [ ] **Step 2: Run — expect FAIL on new assertions**

Run: `pytest backend/tests/test_corpus_parse_recovery.py -v`

- [ ] **Step 3: Strengthen Dice boundary in `_strip_profile_cover` / `_prepare_resume_text`**

Reuse existing `_DICE_NOISE_RE` and `_strip_profile_cover`. Ensure wrapper labels are ignored **only inside the identified preamble**, and parsing resumes at the first real `SUMMARY`/`EXPERIENCE`/`Skills` block after chrome. Add a regression if current `DICE_LIKE` passes but golden `dice_wrapper.txt` fails — fix boundary detection, do not broaden noise stripping into real skills.

- [ ] **Step 4: Add paren-title / split header recognition in `_extract_experience`**

Support at minimum:

1. Company line, then `(Title) MM/YY - Present` (or en-dash)
2. `Company — Title — Dates` on one line
3. Explicit title under Experience followed by bullets

Attach following bullets to that role using section boundaries. Prefer source order.

Sketch (integrate into existing loop; do not replace the whole extractor):

```python
_PAREN_TITLE = re.compile(
    r"^\(([^)]{2,80})\)\s*(\d{1,2}/\d{2,4}|\w+\s+\d{4})\s*[-–—]\s*(Present|\d{1,2}/\d{2,4}|\w+\s+\d{4})$",
    re.I,
)
```

When current company is set and line matches `_PAREN_TITLE`, set `title` and `duration` on the open role.

- [ ] **Step 5: Bullet-only fallback**

After normal extraction, if `not experience` and `detect_employment_evidence(text).has_work_history`:

- Collect bullets under experience-ish region into `unassigned_experience_bullets`
- If a single employer/date line exists, create one structured role and attach bullets
- Else leave unassigned and add parse reason `ambiguous_role_assignment`

- [ ] **Step 6: Name / title guards**

In `_extract_name` / title validation: reject tech-token names (`React Native.`, framework lists). Prefer person-like header evidence. Technology labels used as skills stay in skills.

- [ ] **Step 7: Implement `parse_confidence.py` and attach `parse_meta`**

```python
# backend/app/services/parse_confidence.py
from __future__ import annotations
from app.services.source_evidence import EmploymentEvidence, detect_employment_evidence

def score_parse(data: dict, source_text: str) -> dict:
    evidence = detect_employment_evidence(source_text)
    roles = [r for r in (data.get("experience") or []) if isinstance(r, dict)]
    reasons: list[str] = []
    empty_titles = sum(1 for r in roles if not (r.get("title") or "").strip())
    name = (data.get("name") or "").strip()
    confidence = 1.0
    if evidence.has_work_history and not roles and not (data.get("unassigned_experience_bullets") or []):
        reasons.append("expected_experience_missing")
        confidence -= 0.5
    elif evidence.has_work_history and not roles:
        reasons.append("ambiguous_role_assignment")
        confidence -= 0.35
    if roles and empty_titles / max(1, len(roles)) >= 0.5:
        reasons.append("source_backed_titles_unresolved")
        confidence -= 0.25
    if not name or name.lower() in {"react native", "react native."}:
        reasons.append("identity_ambiguous")
        confidence -= 0.2
    confidence = max(0.0, min(1.0, confidence))
    return {
        "confidence": confidence,
        "reasons": reasons,
        "llm_repaired": False,
        "employment_evidence": {
            "has_work_history": evidence.has_work_history,
            "reasons": evidence.reasons,
        },
    }
```

At end of `parse_resume_detailed`, set `result["parse_meta"] = score_parse(result, resume_text)`.

- [ ] **Step 8: Carry meta through structured store**

Ensure `structured_resume_store` / store builder preserves `parse_meta` and `unassigned_experience_bullets` on the store dict used by integrity (do not render unassigned as a fake job without review).

- [ ] **Step 9: Run recovery + confidence tests**

```bash
pytest backend/tests/test_corpus_parse_recovery.py backend/tests/test_parse_confidence.py backend/tests/test_resume_reading.py -v
```

Expected: PASS (existing Dice/numeric tests still green)

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/detailed_resume_parser.py backend/app/services/parse_confidence.py backend/app/services/structured_resume_store.py backend/tests/test_corpus_parse_recovery.py backend/tests/test_parse_confidence.py
git commit -m "feat: recover Dice, split-header, and bullet-only experience in faithful parse"
```

**Exit check:** Readable Dice and split-header fixtures recover expected jobs/bullets. Bullet-only evidence survives; unresolved assignments → review reasons. Education-only and clean controls pass. Deterministic path ≤3% zero-role on labeled role-bearing Wave A fixtures.

---

