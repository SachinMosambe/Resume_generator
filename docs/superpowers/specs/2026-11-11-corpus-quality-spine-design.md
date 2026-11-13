# Corpus Quality Spine Design

**Date:** 2026-11-11  
**Status:** Approved — implementation plan at `docs/superpowers/plans/2026-11-11-corpus-quality-spine.md`  
**Based on:** `backend/eval_reports/CORPUS_QUALITY_REPORT.md`, `corpus_eval_latest.md`  
**Supersedes (scope):** Incremental follow-on to `docs/superpowers/plans/2026-10-27-resume-output-fidelity.md` for real-corpus failures that remain after synthetic fidelity work.

---

## 1. Problem statement

Company format styling (Aptino / Capgemini / Suresh) is largely working. Recruiters still see bad output because:

1. **~12–19% of resumes parse with 0 roles / 0 bullets** — experience section empty before any template renders.
2. **~86–88% of generate runs are `needs_review`** — mostly driven by mechanical `source_lines` mismatches, not catastrophic field loss.
3. Scores are **nearly identical across formats** — the failure is shared parse → store → integrity, not Capgemini vs Aptino CSS.
4. Prior fidelity work fixed clean/synthetic fixtures; **real-world messiness** (Dice chrome, paren titles, bullet-only layouts, scanned PDFs, `.doc`) still breaks the product.

**Why this keeps recurring:** Format tweaks and one-off parser patches do not change the shared pipeline failure modes, and there is no CI golden gate that fails a PR when zero-role rate or pass rate regresses.

---

## 2. Goals and non-goals

### Goals (single release plan)

| Goal | Target |
|------|--------|
| Integrity hard `passed` on golden set | ≥85% (all three formats) |
| Zero-role parse rate | ≤3% |
| Empty job-title rate among roles | ≤5% |
| Name missing/wrong | ≤5% |
| Scanned PDF success with OCR | ≥90% of scanned golden fixtures |
| Capgemini/Suresh style asserts on clean subset | 100% |
| Hard integrity `failed` | ≤2% |
| Regression prevention | CI **hard-fail** if golden thresholds miss |

### Non-goals

- LLM condense / agent polish as default (faithful mode stays default).
- Full parser IR rewrite or Docling layout models.
- Committing real candidate documents.
- Inventing Capgemini “Summary of Projects” content when the source has no projects.

---

## 3. Decisions locked

| Decision | Choice |
|----------|--------|
| Scope | Near-perfect fidelity: ≥85% pass + OCR/`.doc` + format polish in one plan |
| LLM | Optional fallback only when deterministic parse confidence is low or roles = 0 |
| Quality gate | CI hard-fail on fixed ~50-resume golden set × 3 formats |
| Architecture | Layered Quality Spine (Approach 1) — extend existing FastAPI pipeline |

---

## 4. Architecture

One shared path for every harness. Format only styles a validated store.

```
Upload
  → IntakeGate          (OCR, .doc convert, non-resume quarantine)
  → Extract             (existing pdf/docx readers → text + extraction_meta)
  → DeterministicParse  (Dice strip, header patterns, fallbacks, name guards)
  → Confidence score
       ├─ high → ValidatedStore
       └─ low / 0 roles → LlmStructureRepair (schema-locked, fact-checked)
            → ValidatedStore (or keep deterministic + blocking review)
  → IntegrityGate       (blocking vs informational checks)
  → FormatRender        (aptino | capgemini | suresh)
  → Download + review headers
```

Golden harness runs the same path offline/CI and fails the PR below thresholds.

### Non-negotiables

- Faithful output remains default: no summarization, no silent bullet/role caps.
- LLM repair is **restructure-only**: every employer, title, date, and bullet string must be present in source text (normalized). No invention.
- Never log resume body, names, emails, phones — counts and IDs only.
- Golden fixtures are synthetic or anonymized patterns only; never commit real candidate DOCX/PDF from `eval_reports/samples/`.
- Integrity status semantics are identical for all formats.

---

## 5. Components

### 5.1 IntakeGate

**Location:** Thin orchestration in generate path; reuse `pdf_ocr.py`, `doc_converter.py`, `pdf_parser.py`.

**Responsibilities:**

- Detect scanned / image-only PDF pages; run OCR when enabled and available.
- Convert `.doc` via LibreOffice when present.
- Quarantine obvious non-resumes (certificates, I-94, travel history) with HTTP 422.
- Attach `extraction_meta`: `{ocr_pages, ocr_missing_pages, doc_converted, quarantine_reason?}`.

**Errors:**

| Situation | Behavior |
|-----------|----------|
| OCR needed, available | Continue; informational warning |
| OCR needed, missing | HTTP 422 with clear “OCR required / Tesseract missing” message |
| `.doc`, LibreOffice missing | HTTP 422 with convert/install hint |
| Non-resume | HTTP 422 “not a resume” |

### 5.2 DeterministicParse upgrades

**Location:** `detailed_resume_parser.py` (+ small helpers if a file grows too large).

**Must fix (from corpus evidence):**

1. **Dice / job-board profile detector** — strip or ignore: Preferred Location, Willing to Relocate, Work Auth, Profile Source, Profile Downloaded, Desired Work Settings; re-parse from first real Summary/Experience.
2. **Alternate job-header patterns** — at minimum:
   - Company line then `(Title) MM/YY - Present`
   - `Company — Title — Dates` on one line
   - Title-only lines under Experience followed by bullets
3. **Bullet-only / unsectioned fallback** — if 0 roles but substantial bullet-like content near experience-ish text, create synthetic role(s) or split by date lines rather than emit empty experience.
4. **Name guardrails** — reject tech-token “names” (e.g. `React Native.`); prefer person-like top/centered lines.
5. **Parse confidence** — emit `{confidence: float 0–1, reasons: string[]}` based on roles found, empty-title ratio, name validity, section coverage.

### 5.3 LlmStructureRepair (fallback)

**Location:** New thin service using existing Bedrock/LLM client.

**Trigger (any one):**

- `roles == 0`, or
- `confidence < 0.55`, or
- `≥50%` of roles have empty titles

**Rules:**

- Called at most once per generate.
- Input: source text + weak parse + schema description.
- Output: JSON matching structured store schema.
- Reject and discard if any role field/bullet fails source presence check.
- If LLM unavailable or rejected: keep deterministic store; if still 0 roles → blocking “experience incomplete”.

**Config:** Feature-flagged (e.g. `RESUME_LLM_PARSE_FALLBACK`); default may be on in environments with Bedrock credentials, off otherwise. Deterministic path must still meet as much of the golden set as possible without LLM.

### 5.4 ValidatedStore

**Location:** `structured_resume_store.py` (existing).

- Single canonical object all formats render from.
- Faithful mode: no silent truncation of bullets/roles/education details.
- Carry parse meta (`confidence`, `llm_repaired`, `reasons`) for integrity and headers.

### 5.5 IntegrityGate

**Location:** `output_integrity.py`

**Blocking checks** (drive `failed` / keep `needs_review` when incomplete):

- Candidate name present and person-like when source has a detectable name
- ≥1 role when source experience content exists
- Field presence for titles/companies/dates/bullets when those exist in the store/source
- Education / certifications when present in source and expected in store

**Informational checks** (do **not** alone force `needs_review`):

- Soft `source_lines` coverage / punctuation drift
- References omitted by client policy
- Section label remaps (e.g. Skills → Skills Profile)
- OCR used

**Status rules:**

| Condition | Status |
|-----------|--------|
| All blocking pass; informational only | `passed` |
| Blocking soft incomplete (e.g. experience thin after fallback) | `needs_review` |
| Core fields missing / unreadable output | `failed` |
| OCR/refs/line drift only | `passed` + informational warnings |

Headers: `X-Review-Status`, `X-Review-Warnings` (include severity). Frontend may filter blocking vs info.

### 5.6 FormatRender polish

**Location:** `docx_skeleton_service.py`, format profiles.

- Capgemini: **hide** “Summary of Projects” heading when empty (do not invent projects).
- Preserve Capgemini right-aligned name + Avenir 45; Suresh centered + Arial; section order/labels per template.
- CI style asserts on clean golden subset: `name_align`, `font_family`, `section_order`, required labels.
- Invest in DOCX client templates; PDF client templates remain secondary.

### 5.7 GoldenHarness + CI

**Location:** `backend/scripts/corpus_quality_eval.py` (+ new golden fixture builder), GitHub Actions (or existing CI) workflow.

- Fixed set of ~50 synthetic/anonymized fixtures covering: clean conventional, Dice chrome, paren-title, bullet-only dense, two-column, table DOCX, scanned OCR, `.doc` convert, long multi-role, missing optional sections.
- Run × formats: `aptino`, `capgemini`, `suresh`.
- **PR fails** if any threshold in §2 Goals is missed.
- Never commit real corpus files; builder script generates synthetics into CI workspace / `tests/fixtures`.

---

## 6. Data contracts

```text
extraction_meta:
  ocr_pages: list[int]
  ocr_missing_pages: list[int]
  doc_converted: bool
  quarantine_reason: str | null

parse_meta:
  confidence: float   # 0.0–1.0
  reasons: list[str]
  llm_repaired: bool

review:
  status: "passed" | "needs_review" | "failed"
  warnings: list[{severity: "blocking"|"info", code: str, message: str}]
```

---

## 7. Error handling summary

| Situation | Behavior |
|-----------|----------|
| Scanned + OCR OK | Continue; info warning |
| Scanned + OCR missing | 422 |
| `.doc` without LibreOffice | 422 |
| Non-resume quarantine | 422 |
| LLM repair success | Continue; `llm_repaired=true` |
| LLM unavailable/rejected + still 0 roles | DOCX may still generate; `needs_review` + blocking experience warning |
| Informational warnings only | `passed` |
| Blocking integrity failure | `failed`; UI must not treat as auto-sendable |

---

## 8. Testing strategy

1. **Unit tests** — Dice strip, paren-title headers, name guard, confidence scoring, integrity severity split, LLM reject-on-invention.
2. **Fixture integration** — pattern clones (Marco-dense, Dice sheet, gerald paren-title, bullet-only, scanned) × 3 formats.
3. **Golden CI** — thresholds hard-fail.
4. **Manual spotcheck** — keep `spotcheck_formats.py` for visual DOCX sampling (artifacts not committed).

Reproduction (dev):

```bash
cd backend
.\.venv\Scripts\activate
python scripts/fidelity_report.py
python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
python scripts/spotcheck_formats.py
```

---

## 9. Implementation waves (for the upcoming plan)

Ordered so each wave is shippable and measurable:

| Wave | Focus | Exit criteria |
|------|-------|---------------|
| A | Deterministic parse fixes + fixtures | Zero-role ≤3% on golden without requiring LLM |
| B | Integrity severity split + UI headers | `passed` ≥85% when fields OK; soft lines no longer dominate |
| C | IntakeGate OCR + `.doc` + quarantine | Scanned/`.doc` golden ≥90% / clear 422s |
| D | LLM structure repair fallback | Remaining hard layouts recover without invention |
| E | Format polish asserts + Capgemini empty projects hide | Style 100% on clean subset |
| F | Golden CI hard-fail workflow | Regressions cannot merge |

---

## 10. Success definition (“never again”)

The product is considered fixed for this problem class when:

1. Golden CI is green at the §2 targets for all three formats.
2. Empty experience on Dice / paren-title / bullet-only patterns has regression tests.
3. `needs_review` means **actionable blocking issues**, not punctuation/label noise.
4. Adding a new client harness only adds a renderer/profile — it cannot bypass IntakeGate, parse confidence, or IntegrityGate.

---

## 11. Open product notes (resolved in this design)

| Topic | Resolution |
|-------|------------|
| Capgemini empty Projects | Hide heading; do not invent |
| LLM role | Fallback only; schema + source fact check |
| Real corpus in git | Forbidden; synthetic golden only |
| Format-specific parse | Forbidden; one spine for all harnesses |
