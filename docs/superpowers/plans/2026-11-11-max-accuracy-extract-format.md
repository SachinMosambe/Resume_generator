# Max-Accuracy Extract → Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Maximize extract accuracy and faithful company-format mapping: enable eligible LLM repair by default, eliminate false `bullet_wrong_role` failures, recover more zero-role layouts, and remeasure the paired 60-file corpus.

**Architecture:** Keep the shared FastAPI spine. Production turns on source-checked LLM repair for weak parses. Integrity role-assignment becomes conservative (only fail on clear mis-assignment). Parser gains remaining high-impact header patterns from the latest worst-case list.

**Tech Stack:** Existing Python/FastAPI/Bedrock client, pytest, corpus_quality_eval.py

## Global Constraints

- Faithful mode default; never invent facts.
- LLM repair: at most once; reject if source checks fail; `llm_repaired` only on accept.
- Golden CI forces `RESUME_LLM_PARSE_FALLBACK=false`.
- Production default: `RESUME_LLM_PARSE_FALLBACK=true` (accuracy-first Option A).
- No real candidate docs in git; recruiter-safe warnings only.
- Same path for aptino/capgemini/suresh.

---

### Task 1: Stop false `bullet_wrong_role` failures

**Files:**
- Modify: `backend/app/services/output_integrity.py`
- Modify: `backend/tests/test_output_integrity.py`

**Interfaces:**
- Consumes: existing role-assignment window check
- Produces: fail only when a bullet unique to role A appears solely under role B’s window; skip/downgrade when bullet text repeats across roles or windows are ambiguous

- [ ] **Step 1: Write failing tests**

```python
def test_repeated_bullet_across_roles_does_not_fail():
    # same bullet text under two employers in store+docx → not bullet_wrong_role failed

def test_unique_bullet_under_wrong_employer_still_fails():
    # unique bullet for role A only under role B heading → failed
```

- [ ] **Step 2: Run tests — expect FAIL on repeated-bullet case if currently failed**

Run: `pytest backend/tests/test_output_integrity.py -k role -v`

- [ ] **Step 3: Implement conservative assignment check**

Only flag when:
- bullet is unique to one store role (not shared), AND
- that role’s company/title window is found in DOCX, AND
- bullet appears in another role’s window but not in its own.

If windows cannot be located → skip (do not fail). Shared/duplicate bullets → ignore.

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "fix: reduce false bullet_wrong_role failures on repeated bullets"
```

---

### Task 2: Enable accuracy-first LLM repair default

**Files:**
- Modify: `backend/app/core/config.py` (`RESUME_LLM_PARSE_FALLBACK: bool = True`)
- Modify: `backend/tests/test_llm_structure_repair.py` (assert new default)
- Keep: golden/CI forcing false

- [ ] **Step 1: Update default + test**

```python
assert Settings.model_fields["RESUME_LLM_PARSE_FALLBACK"].default is True
```

- [ ] **Step 2: Confirm golden script still forces false and exits 2 if on**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: enable LLM parse repair by default for max accuracy"
```

---

### Task 3: Recover remaining high-impact zero-role patterns

**Files:**
- Modify: `backend/app/services/detailed_resume_parser.py`
- Modify/Create: golden cases + `backend/tests/test_corpus_parse_recovery.py`
- Focus patterns from latest worst cases: Dice profile sheets, dense bullet PDFs, content-strategist/portfolio without classic headers, paren/split leftovers

- [ ] **Step 1: Add anonymized fixtures mirroring worst-case structures (no real PII)**

- [ ] **Step 2: Failing recovery tests → implement → pass**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: recover additional zero-role resume layouts"
```

---

### Task 4: Remeasure accuracy

**Files:**
- Run: `python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh`
- Run: paired 60-file eval (same inputs as `corpus_eval_20261111_135025` if `--from-report` exists; else `--limit 60`)
- Update: short note in `backend/eval_reports/` or task report (counts only)

- [ ] **Step 1: Golden must exit 0**

- [ ] **Step 2: Report before/after for passed%, zero-role%, failed%**

- [ ] **Step 3: Commit report note if tracked; else leave under eval_reports untracked**

---

## Exit check

- False `bullet_wrong_role` no longer dominates failed%
- Production default uses repair for weak parses
- Golden green with repair off
- Paired corpus shows higher passed% and/or lower zero-role% than 17:45 baseline (23.7% pass / 15.3% zero-role / 6.8% failed)
