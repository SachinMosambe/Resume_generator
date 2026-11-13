# Safe Zero-Role Edge Wave

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or execute inline with TDD. Golden must stay green.

**Goal:** Recover remaining high-impact zero-role layouts (portfolio/stylized work blocks, letter-spaced dates, Role labels without dates) without inventing facts and without regressing current accuracy.

**Architecture:** Extend `detailed_resume_parser.py` only with source-backed patterns. Add synthetic fixtures + recovery tests first. After each pattern, run `pytest` recovery/full suite and `corpus_quality_eval.py --golden`. Abort any change that breaks golden or creates invented employers.

**Tech Stack:** Existing parser, pytest, golden harness.

## Global Constraints

- Never invent employers/titles/dates/bullets.
- No real candidate PII in fixtures.
- Golden CI must remain exit 0; zero-role on scored fixtures must stay 0%.
- Offline corpus: prefer fixed>0 and broke==0 on any comparison sweep.
- Faithful mode; LLM repair unchanged (default on in prod, forced off in golden).

---

### Task 1: Letter-spaced dates

**Files:** `detailed_resume_parser.py`, `test_corpus_parse_recovery.py`, golden case `letter_spaced_dates.txt`

- [ ] Failing test: `A U G U S T 2 0 2 3 - P R E S E N T` (or similar) yields a role with recoverable duration tokens
- [ ] Implement normalizer collapsing letter-spaced month/year/present in date contexts only
- [ ] pytest + golden green
- [ ] Commit: `feat: parse letter-spaced employment dates`

### Task 2: Role/Company labels without dates

**Files:** parser + `role_label_no_dates.txt`

- [ ] Failing test: `Role: Senior Analyst` / `Company: Acme` with bullets, no dates → ≥1 role, empty duration OK, no invented dates
- [ ] Implement only when Role/Company/Client labels are explicit
- [ ] pytest + golden green
- [ ] Commit: `feat: recover Role/Company blocks without dates`

### Task 3: Portfolio / stylized engagement blocks

**Files:** parser + `portfolio_engagements.txt`

- [ ] Failing test: client name + `Role:` + dated or undated bullets under Engagements/Clients/Content Experience style heading
- [ ] Map only when employer-like lines + Role/title evidence exist; do not invent
- [ ] pytest + golden green
- [ ] Commit: `feat: recover portfolio engagement work history`

### Task 4: Verify no regression

- [ ] Full `pytest tests -q`
- [ ] `python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh` exit 0
- [ ] Optional offline zero-role compare if corpus available: broke must be 0
