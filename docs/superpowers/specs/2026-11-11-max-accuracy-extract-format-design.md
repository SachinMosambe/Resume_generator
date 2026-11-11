# Max-Accuracy Extract → Company Format Design

**Date:** 2026-11-11  
**Status:** Approved (accuracy-first / Option A)  
**Parent:** `docs/superpowers/specs/2026-11-11-corpus-quality-spine-design.md`

## Goal

Extract **all** resume facts with maximum accuracy, then map those same facts into Aptino / Capgemini / Suresh with maximum fidelity. Prefer slower generate when repair helps. Never invent employers, titles, dates, or bullets.

## Defaults

- Faithful mode remains default.
- `RESUME_LLM_PARSE_FALLBACK` defaults **True** for production accuracy (eligible weak parses only).
- Golden CI keeps fallback **forced off** for deterministic gates.
- Company format only restyles a validated store.

## Accuracy spine

1. Intake (OCR / `.doc` / quarantine)
2. Deterministic parse + employment evidence + confidence
3. If eligible → one LLM structure repair → source fact-check
4. Store all verified facts (roles, bullets, education, certs, extras)
5. Render into company template sections (no content invention)
6. Strict DOCX verify (blocking vs info); role assignment must not false-fail on repeated bullets

## Success targets (paired 60-file + golden)

| Metric | Target |
|--------|--------|
| Zero-role on role-bearing sources | ≤5% interim / ≤3% goal |
| Hard `failed` from false role-assignment | ≤2% |
| Integrity `passed` | ≥40% interim / ≥85% goal |
| Golden CI | remains green with fallback off |

## Non-goals

- Condensed/LLM polish as default
- Inventing Capgemini projects
- Committing real candidate resumes
