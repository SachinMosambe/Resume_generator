# Integrity-Driven Recovery for Corpus Fidelity

**Date:** 2026-11-12  
**Status:** Approved (user: fix it) — ready for implementation plan  
**Related:** `2026-11-11-hybrid-llm-accuracy-design.md` (first-pass LLM repair); this spec adds a **post-integrity** grounded recovery loop.

## Goal

On a fixed **60–80** private-corpus sample under **production** settings (`RESUME_LLM_LINE_EXTRACT=true`, Bedrock configured):

≥ **95%** of resumes finish as:

- `passed`, **or**
- `needs_review` with **no** blocking `source_lines` and **no** wrong-role / `bullet_wrong_role`

Achieve this by **improving content fidelity only**. Integrity classification rules and thresholds stay unchanged.

## Non-goals (this wave)

- Loosening or rewriting `output_integrity` pass/fail thresholds
- Enabling the multi-agent pipeline as the primary path
- Inventing or paraphrasing resume text
- Fixing OCR install / LibreOffice availability on the host
- Changing golden CI to require Bedrock

## Constraints

- Production may use more Bedrock when recovery runs: about **8–12 calls** and **60–90s** wall time on hard resumes.
- Easy resumes must keep today’s fast path (no recovery when first integrity has no blocking `source_lines` / wrong-role and roles are present).
- Every recovered string must be **verbatim on a cited source line** (same grounding contract as line extract).
- Golden / unit tests keep recovery and line extract **off** unless a test explicitly enables fakes.

## Architecture

Keep the existing generate path. Add **one** optional recovery cycle after the first integrity report.

```
extract → rule parse → Bedrock line extract
  → build store → render DOCX → integrity #1
       │
       ├─ no recovery trigger → return draft #1
       │
       └─ recovery trigger
            → collect missing hard source lines (+ role hints)
            → grounded Bedrock recovery (cite/copy only)
            → merge into experience store
            → re-render DOCX once
            → integrity #2
            → return better of draft #1 vs #2
```

No third render in this wave.

### Placement

- Orchestration lives in `ResumeGenerationService.generate` (or a small helper module it calls) so the API path and the production hard-resume harness both get the behavior.
- Reuse line-extractor grounding helpers where possible; do not duplicate unchecked free-form LLM JSON into the store.

## Recovery contract

### Triggers (after integrity #1)

Any of:

1. Blocking `source_lines` (hard missing fact-bearing source lines)
2. Zero experience roles while source shows work-history evidence
3. Blocking wrong-role / `bullet_wrong_role`

### Recovery input

- Exact missing hard source lines (from integrity / source-line classifier)
- Current role headers (company, title, dates) from the store
- Numbered source text (same style as line extract)

### Model rules

- Answer with line citations only
- Copy text only from the cited line; reject fields that fail verbatim check
- Do not invent employers, titles, dates, or metrics

### Merge rules

- Attach recovered bullets under the matching employer/title when headers match
- If no employer match → existing unassigned / “Role details need review” bucket
- Prefer draft #2 only if integrity improves (fewer hard `source_lines` misses and no new wrong-role). Otherwise keep draft #1.

### First-pass line-extract tweak (small, in-scope)

If the rule parse has **0 roles** and the LLM returned ≥1 **non-lumped** role, use the LLM experience even when the strict coverage gate failed. This covers empty-rule + partial-LLM cases (e.g. some hard DOCX/PDF misses) without waiting for recovery.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `RESUME_INTEGRITY_RECOVERY` | `true` when Bedrock token present, else `false` | Master switch |
| `RESUME_INTEGRITY_RECOVERY_MAX_CALLS` | fit remaining budget (suggest `4`) | Cap recovery Bedrock calls |
| `RESUME_INTEGRITY_RECOVERY_TIMEOUT_SECONDS` | fit under ~90s wall (suggest `45`) | Cap recovery wall time |

Existing flags remain: `RESUME_LLM_LINE_EXTRACT`, `RESUME_LLM_PARSE_FALLBACK`. Golden CI continues to force LLM paths off.

## Measurement

1. **Hard set:** re-run the 12 known hard resumes with production settings; report status, hard `source_lines`, wrong-role, roles, recovery used.
2. **Corpus sample:** fixed 60–80 file sample (stratified like `pick_resumes`); report % meeting the success bar.
3. **Regression:** golden `--golden` still exit 0 with recovery disabled.

Ship criterion for this wave: corpus sample meets ≥95% under the success bar above, golden still green.

## Testing

- Unit: trigger detection from integrity warnings / checks
- Unit: merge accepts only cited verbatim lines; rejects invented text
- Unit: prefer recovered draft only when hard misses decrease
- Unit: 0-role rule + non-lumped LLM roles → `line_extract.used=true`
- Golden / CI: recovery off; existing fixtures unchanged

## Error handling

- Bedrock errors, timeouts, or failed grounding → keep draft #1, record reason in `parse_meta.integrity_recovery`
- Never raise out of generate solely because recovery failed
- Integrity still never blocks download; status headers remain the recruiter signal

## Risks

- Recovery may not reach 95% on the first wave (scanned unread pages, true unreadable `.doc`); report the gap with failing IDs rather than loosening integrity.
- Extra latency/cost on hard files — acceptable per budget B; must not apply to clean passes.
- Over-merge could worsen wrong-role — mitigated by “prefer only if integrity improves.”
