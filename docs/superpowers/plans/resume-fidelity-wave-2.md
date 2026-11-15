# Resume Fidelity Wave 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert complex resumes into supported client DOCX templates while preserving required source content, keeping role ownership correct, preventing invented facts, producing consistent repeated results, and explicitly routing unresolved documents to human review — without claiming 100% accuracy on arbitrary resumes.

**Architecture:** Extend the existing faithful FastAPI path with a versioned source ledger and render manifest (Phase 1), extraction adapters that keep successful paths (Phase 2), Gemma constrained to grounded source-ID grouping (Phase 3), immutable canonical resume + versioned template contracts (Phase 4), separated validation/review outcomes (Phase 5), tenant-scoped idempotency (Phase 6), and annotated evaluation gates (Phase 7). Keep agent pipeline off; keep integrity thresholds unchanged; keep `google.gemma-3-27b-it` as baseline.

**Tech Stack:** Next.js UI, FastAPI, python-docx, PyMuPDF/pdfplumber, Tesseract OCR (existing), AWS Bedrock Gemma 27B, pytest, existing corpus/golden harnesses.

## Global Constraints

- Keep Gemma baseline model ID exactly `google.gemma-3-27b-it` (from `backend/app/core/config.py` / `.env`); do not replace without comparative evaluation.
- Keep `RESUME_AGENT_PIPELINE=false`.
- Do not weaken integrity checks in `output_integrity.py` to improve pass rates.
- Do not invent dates, titles, employers, qualifications, or metrics.
- Do not use the LLM to rewrite the entire resume; Gemma returns source refs / relationships only.
- Do not silently truncate documents, extracted text, or model output into a “success” path.
- Do not introduce vector DBs, agent frameworks, or new queue platforms unless repo evidence requires it.
- Protect candidate data: no raw resume bodies in routine logs; no new external vendors without an explicit decision.
- Preserve unrelated work and existing supported API behavior (`POST /api/generate`, `X-Review-*` headers).
- Spec sources: user Wave 2 brief; `test/resume/Resume_Generator_Reliable_Architecture.md`; prior `docs/superpowers/specs/2026-11-12-integrity-recovery-fidelity-design.md`.

---

## Phase 0 findings (inspected 2026-11-13)

### Actual architecture (verified)

```
Next.js (frontend/src/app/page.tsx)
  → FastAPI POST /api/generate (backend/app/api/routes/generate.py)
  → extract_document (pdf_parser.py) + optional OCR (pdf_ocr.py)
  → assess_resume_intake (intake_gate.py)
  → Candidate.extracted_data{raw_text, extraction_meta}
  → ResumeGenerationService.generate (resume_generation_service.py)
       [RESUME_AGENT_PIPELINE=false → classic path]
  → parse_resume_detailed (detailed_resume_parser.py)
  → llm_line_extractor.apply_line_extraction (Bedrock, if enabled)
  → optional llm_structure_repair.maybe_repair_parse
  → build_structured_resume (structured_resume_store.py)
  → compose document sections → _render_with_format_strategy
       (docx_skeleton_service and/or schema _render_docx / docx_layout)
  → check_output_integrity (output_integrity.py)
  → optional integrity_recovery (one pass)
  → DOCX bytes + service.last_report → X-Review-Status / Warnings / Warning-Details
```

### Relevant modules

| Area | Files |
|------|-------|
| API | `backend/app/api/routes/generate.py`, `backend/app/main.py` |
| Config | `backend/app/core/config.py`, `backend/.env.example` |
| Extraction | `pdf_parser.py`, `docx_reader.py`, `source_blocks.py`, `doc_converter.py`, `pdf_ocr.py` |
| Intake | `intake_gate.py` |
| Rule parse | `detailed_resume_parser.py`, `parse_confidence.py` |
| Bedrock line extract | `llm_line_extractor.py`, `agents/tools/llm_client.py`, `interview_llm/bedrock_client.py` |
| Parse fallback | `llm_structure_repair.py` |
| Store | `structured_resume_store.py` |
| Templates | `aptino_template.py`, `format_extraction_service.py`, `format_profile_store.py`, `docx_skeleton_service.py`, `docx_layout.py` |
| Integrity / recovery | `output_integrity.py`, `integrity_recovery.py` |
| Evidence helpers | `source_evidence.py` (employment detection only; not a ledger) |

### Intended settings (verified in code / `.env`)

| Setting | Value |
|---------|-------|
| `RESUME_OUTPUT_MODE` | `faithful` |
| `RESUME_AGENT_PIPELINE` | `false` |
| `RESUME_LLM_LINE_EXTRACT` | default `true` (`.env.example`; not overridden off in `.env`) |
| `RESUME_LLM_PARSE_FALLBACK` | default `true` |
| `RESUME_INTEGRITY_RECOVERY` | default `true` |
| `BEDROCK_MODEL` | `google.gemma-3-27b-it` |
| Line-extract invoke | `llm_call_json_with_metrics` → Bedrock `temperature=0.0`, `max_tokens=4096`, `repair_attempts=1` |

Note: temperature 0.0 reduces variance but does **not** guarantee deterministic model output across calls/hosts.

### Supported inputs and templates

- **Inputs:** `.pdf`, `.docx`, `.doc` (via conversion), `.html`/`.htm` (extract path); upload size `MAX_FILE_SIZE_MB=10`; DOCX archive limits in `docx_reader.py`.
- **Templates:** `aptino_default`, uploaded `client_format`, `saved_format`. Golden formats: Aptino, Capgemini, Suresh (`test/format/*.docx`).

### Provenance / disappearance points

1. **DOCX blocks discarded:** `read_docx_blocks` builds `SourceBlock` IDs, then `_extract_docx` keeps only `blocks_to_text(...)` — IDs/origin/bbox never reach the store.
2. **PDF has no block ledger:** PyMuPDF/pdfplumber return plain text; page/block geometry is not retained as stable IDs for Gemma or integrity.
3. **Parser → store:** `structured_resume_store` stores strings only (no `source_ids`).
4. **Renderer:** section composition can drop empty headings; experience items without identity+bullets are skipped; contact is intentionally omitted by client policy; `unassigned_experience_bullets` are review-only and not rendered as jobs.
5. **Integrity vs ownership:** `source_lines` is global substring/4-gram presence — not per-role ownership. Citations alone ≠ correct role attachment.
6. **Recovery:** one grounded pass; historical meta dominated by `no_improvement`.
7. **Silent truncate risk:** `lightweight=True` truncates by `max_chars` / PDF pages; full generate path uses full extraction, but any future misuse of lightweight for generate would violate the non-negotiable rule.

### `source_lines` verifier alignment (preserve metric; document separately)

Current hard-miss logic (`_source_line_classifications`): skip short/dated/contact-ish lines; require ≥30% of 4-grams in normalized output haystack; bullet-marked or fact-bearing lines missing → hard.

**Possible false hard misses (hypothesis, not yet quantified on this machine):**
- Faithful reordering / wrapping that breaks 4-grams while content is present.
- Soft punctuation/normalization differences between source extract and DOCX re-extract.
- Multi-column PDF reading order producing source lines that never appear contiguous in output.

**Rule for Wave 2:** keep the existing `source_lines` metric and thresholds unchanged for reported pass rates. Any improved alignment check must be a **separate** diagnostic metric (e.g. `source_lines_span_v2`) until evaluation justifies a controlled migration.

### Existing partial work to reuse

- `SourceBlock` + `docx_reader.read_docx_blocks` + tests (`test_docx_reader.py`).
- Intake gate + block-extract / block-intake eval reports (2026-11-13) — extraction recall on accepted files looked strong where process completed; many `crash`/`unknown` rows in those reports need investigation separately.
- Integrity recovery module already wired.

### Historical baseline (treat as historical until reproduced here)

From `backend/eval_reports/fidelity_recovery_wave.md` (2026-11-12):

| Suite | Meeting bar |
|-------|-------------|
| Hard 12 (prod settings) | **2/12 = 16.7%** |
| Corpus 60 (prod settings) | **22/60 = 36.7%** |
| Golden (LLM off) | **PASS** (168 runs) |
| Recovery preferred | 0/12 hard; 1/60 corpus |

Dominant failure: blocking `source_lines`. Recovery rarely improves selected draft.

### Baseline commands

```bash
cd backend
# Unit / CI-equivalent (LLM paths forced off by CI env)
pytest -q
# Golden gate
python scripts/corpus_quality_eval.py --golden --formats aptino,capgemini,suresh
# Prod hard set (needs Bedrock token + private corpus path)
python scripts/prod_hard_resume_retest.py
# Prod 60 sample
python scripts/prod_corpus_fidelity_sample.py
```

### Failure categories (from historical report + code inspection)

| Category | Evidence | Likely stage |
|----------|----------|--------------|
| Blocking `source_lines` | 36/60, 10/12 | extract / parse / render / verifier alignment |
| `bullets_missing` | 11/60 | ownership or render |
| `overlapping_role_dates` | 10/60 | grouping |
| Wrong-role / `bullet_wrong_role` | 3/60, 1/12 | grouping |
| Zero roles | 1/60, 1/12 | extract/parse |
| Certifications missing | 3/60 | parse/render |
| Legacy `.doc` failed | hard set Kaminski | conversion |
| OCR unavailable / no text | intake/block reports | OCR host deps |
| Recovery `no_improvement` | majority of recovery attempts | line extract coverage ceiling |

### Missing access / data that blocks verification

- **Private corpus path mismatch:** scripts expect `Resume_generator-main/Resume_generator-main/Sachin resume AI/Sachin resume AI`, but corpus lives at `Downloads/Resume_generator-main/Sachin resume AI/Sachin resume AI` (sibling of nested repo). Hard/corpus prod scripts fail until a junction/symlink or path fix.
- **Local deps:** first pytest attempt failed with `ModuleNotFoundError: pymupdf` before `pip install -r requirements.txt` completed.
- **OCR / LibreOffice:** may be missing on Windows host (affects scanned PDF + `.doc`).
- **Paid Bedrock cost/latency:** full 60 + hard 12 reproduction consumes Bedrock quota; run after path fix; do not claim numbers if not run.
- **Human annotations** for role ownership ground truth: not yet present for Wave 2 metrics (Phase 7).

### Feature flag / rollback approach

| Flag | Purpose | Rollback |
|------|---------|----------|
| `RESUME_SOURCE_LEDGER` (new, default off until Phase 1 green) | Build/persist ledger + manifest checks | Set false → classic text-only path |
| `RESUME_RENDER_MANIFEST` (new) | Pre/post render coverage vs DOCX reopen | Off → existing integrity only |
| `RESUME_GROUNDED_GROUPING` (Phase 3) | Gemma returns source IDs | Off → current line-extract |
| Existing `RESUME_LLM_LINE_EXTRACT` / `RESUME_INTEGRITY_RECOVERY` / `RESUME_AGENT_PIPELINE` | unchanged semantics | existing toggles |

Rollback = flip flags + redeploy; no integrity threshold edits required.

---

## File map (Wave 2)

| File | Responsibility |
|------|----------------|
| `backend/app/services/source_ledger.py` | **Create:** versioned ledger, spans, dispositions, serialization |
| `backend/app/services/source_blocks.py` | Extend block model / helpers to feed ledger |
| `backend/app/services/docx_reader.py` | Emit richer locations; inventory unsupported elements |
| `backend/app/services/pdf_parser.py` | Persist blocks/meta into ledger; avoid silent truncate on generate path |
| `backend/app/services/render_manifest.py` | **Create:** pre-render destinations + post-render DOCX verification |
| `backend/app/services/structured_resume_store.py` | Carry `source_ids` / unresolved / exclusions |
| `backend/app/services/resume_generation_service.py` | Wire ledger → store → manifest → render → verify |
| `backend/app/services/output_integrity.py` | Keep existing checks; add parallel provenance diagnostics only |
| `backend/app/core/config.py` | New feature flags |
| `backend/tests/test_source_ledger.py` | **Create** |
| `backend/tests/test_render_manifest.py` | **Create** |
| Later phases | extraction adapters, grounded grouping schema, canonical resume, idempotency, eval annotations |

---

### Task 1: Versioned source ledger types + tests

**Files:**
- Create: `backend/app/services/source_ledger.py`
- Modify: `backend/app/services/source_blocks.py`
- Test: `backend/tests/test_source_ledger.py`

**Interfaces:**
- Consumes: `SourceBlock` from `source_blocks.py`
- Produces:
  - `SourceLedger` with `source_revision: str`, `items: list[SourceItem]`
  - `SourceItem(id, raw_text, normalized_text, location, extraction_method, uncertainty, disposition, reason, provenance)`
  - `disposition ∈ {"required", "excluded_with_reason", "unresolved"}`
  - `build_ledger_from_blocks(blocks, *, file_hash, extractor_version) -> SourceLedger`
  - `normalize_for_match(text) -> str` (whitespace/line-wrap only)

- [ ] **Step 1: Write failing tests** for stable IDs, narrow normalization, unknown→unresolved, exclusion audit fields, span support.

- [ ] **Step 2: Implement ledger module + narrow normalizer.**

- [ ] **Step 3: Run** `pytest backend/tests/test_source_ledger.py -q` → PASS.

- [ ] **Step 4: Commit** only when user asks.

---

### Task 2: Attach ledger to DOCX/PDF extraction without breaking text path

**Files:**
- Modify: `backend/app/services/pdf_parser.py`, `docx_reader.py`, `generate.py` (store ledger snapshot in `extraction_meta`)
- Test: extend `test_docx_reader.py`; add ledger-in-meta assertion

**Interfaces:**
- `extract_document` continues returning `(text, meta)`
- `meta["source_ledger"]` present when `RESUME_SOURCE_LEDGER=true`
- Text used by parser remains `blocks_to_text` / existing PDF text (no behavior change when flag off)

- [ ] **Step 1: Flag in config** `RESUME_SOURCE_LEDGER: bool = False` (enable in local tests that need it).

- [ ] **Step 2: DOCX path serializes blocks into ledger items with paragraph/table/header/footer/textbox locations.**

- [ ] **Step 3: PDF path creates page/line items with page numbers (bbox when available); mark OCR items with uncertainty.**

- [ ] **Step 4: Tests with flag on/off; generate path still works with flag off.**

---

### Task 3: Render manifest + DOCX reopen verification

**Files:**
- Create: `backend/app/services/render_manifest.py`
- Modify: `resume_generation_service.py` (build manifest before render; verify after)
- Test: `backend/tests/test_render_manifest.py`

**Interfaces:**
- `RenderManifestEntry(source_span_ids, owner, target_section, output_element, expected_text, repeat_reason)`
- `build_render_manifest(store, ledger) -> RenderManifest`
- `verify_render_manifest(docx_bytes, manifest) -> list[ManifestIssue]`
- Unresolved required content → contributes to `needs_review` via existing report channel (do not weaken hard integrity)

- [ ] **Step 1: Failing test** — required span missing from reopened DOCX text under correct owner region.

- [ ] **Step 2: Implement build + independent reopen check (not renderer “written” flags alone).**

- [ ] **Step 3: Wire behind `RESUME_RENDER_MANIFEST`.**

---

### Task 4: Fix demonstrated rendering omissions

**Files:**
- Modify: `docx_skeleton_service.py` / `_render_docx` / section composition as proven by failing fixture tests
- Test: golden-style synthetic fixtures that currently omit certifications / additional_sections / duplicate bullets under two roles

- [ ] **Step 1: Add regression tests** from known omission patterns (`certifications_missing`, unassigned review labeling, dual-role duplicate bullet occurrences).

- [ ] **Step 2: Fix renderer/manifest destinations only — never append missing bullets under arbitrary roles.**

- [ ] **Step 3: Re-run affected unit + golden subset.**

---

### Task 5: Phase 2 — Extraction adapter interface

**Files:** `backend/app/services/extraction/` (or single `extraction_adapters.py` if small), wrap existing PDF/DOCX/DOC/OCR.

Requirements from brief: inventory unsupported elements; DOC conversion in temp workspace with timeout/cleanup; selective OCR; limits → clear failure/review status; expensive work uses existing infra only (no new queue unless needed). Evaluate Docling vs current PDF extractor on fixtures — report only; do not switch without numbers.

---

### Task 6: Phase 3 — Grounded Gemma grouping

Keep `google.gemma-3-27b-it`. Change response shape to source IDs + relationships; validate schema + ID existence + conflicts; application copies original text; at most one malformed-response retry; pin prompt version; low-variance settings already `temperature=0.0`.

---

### Task 7: Phase 4 — Canonical resume + template contracts

Immutable accepted revision with source refs; re-template without re-invoking Gemma; version Aptino/Capgemini/Suresh contracts; unknown uploaded templates validated before auto-accept.

---

### Task 8: Phase 5 — Separated validation + review outcomes

Separate checks for extraction completeness, required coverage, role ownership, unsupported additions, duplicate occurrences, layout. Map to `passed` / `needs_review` / `failed` compatibly. Actionable issue records. Do not claim visual automation proves flawless layout.

---

### Task 9: Phase 6 — Idempotency / ops

Tenant-scoped cache key: file hash + canonical revision + extraction/schema/parser/model/prompt/template/renderer versions + options. Atomic publish; no cross-tenant sharing; timings without raw PII.

---

### Task 10: Phase 7 — Evaluation gates

Keep current corpus/integrity definitions. Add human-checkable annotations. Report numerators/denominators. Targets: zero known blocking content/ownership defects in **accepted** eval outputs; identical artifact bytes on repeat accepted requests; no golden regression; ≥95% automatic completion is a measured target, not a promise.

---

## Acceptance checks (Wave 2 overall)

1. Golden `--golden` still exit 0 with LLM/recovery off.
2. With ledger flag off, API behavior matches pre-Wave-2 for existing clients.
3. With ledger+manifest on, unresolved required content cannot be auto-`passed`.
4. Integrity thresholds unchanged; new diagnostics are additive.
5. Before/after hard-12 and corpus-60 reported with definitions when credentials+corpus path available.
6. Plan updated with actual commands run and blockers.

## Implementation order

Phase 1 Tasks 1–4 first (this session). Phases 2–7 only after Phase 1 tests pass and plan results section is updated.

## Results log (update as work proceeds)

| Date | Check | Result | Notes |
|------|-------|--------|-------|
| 2026-11-13 | Architecture inspect | Done | Matches intended pipeline; Gemma `google.gemma-3-27b-it` |
| 2026-11-13 | Historical fidelity report | Read | 36.7% / 16.7% / golden pass / recovery rare |
| 2026-11-13 | `pip install -r requirements.txt` | Done | Unblocked pytest |
| 2026-11-13 | Phase 1 unit tests | **75+ passed** | `test_source_ledger*`, `test_render_manifest`, integrity, docx_reader |
| 2026-11-13 | Renderer omission synthetics | **3 passed** | additional/certs, dual-role duplicate bullet, unassigned — no skeleton bug found on these |
| 2026-11-13 | Corpus path | **Fixed in scripts** | Resolve parent `Sachin resume AI` when nested copy missing |
| 2026-11-13 | Prod hard/corpus retest | Not re-run yet | Path fix ready; Bedrock cost/time remains |
| 2026-11-13 | Golden aptino | **PASS** | 56/56 |
| 2026-11-13 | Golden aptino,capgemini,suresh | **PASS** | exit 0 (168 runs) |
| 2026-11-13 | Full pytest | **395 passed**, 1 skipped | Fixed intake tests for extract_with_adapter |
| 2026-11-13 | Prod hard-12 live | **2/12 = 16.7%** bar | 5 files missing from disk; 7 ran; recovery preferred 0 |
| 2026-11-13 | Prod corpus-60 live (flags OFF) | **21/60 = 35.0%** | baseline |
| 2026-11-13 | Wave 2 flags enabled in `.env` + config defaults | ON | ledger/manifest/grouping/canonical/cache |
| 2026-11-13 | Prod hard-12 Wave2 ON | **2/12 = 16.7%** | unchanged; 5 files still missing |
| 2026-11-13 | Prod corpus-60 Wave2 ON | **32/60 = 53.3%** | up from 35.0%; blocking source_lines 35→18 |

### Phase 1 implemented (this session)

- `source_ledger.py` — versioned ledger, dispositions, spans, narrow normalize
- `render_manifest.py` — build + DOCX reopen verify (per-owner duplicate bullets)
- Flags `RESUME_SOURCE_LEDGER`, `RESUME_RENDER_MANIFEST` (default **false**)
- DOCX/PDF extraction attaches ledger when flag on; truncate marked in meta for lightweight
- Generate path applies manifest when flag on; unresolved/missing → cannot stay `passed`
- Store carries `source_refs.source_revision`

### Phases 2–7 implemented (2026-11-13 continuation)

| Phase | Delivered | Flag (default) |
|-------|-----------|----------------|
| 2 | Adapter limits (size/pages/time), DOC failure diagnostics, Docling probe boundary (report-only) | n/a |
| 3 | `grounded_grouping.py` — schema validate, ID conflicts, ledger text copy, line→ledger map | `RESUME_GROUNDED_GROUPING=false` |
| 4 | `canonical_resume.py` — immutable revisions, template contracts, unknown-template gate | `RESUME_CANONICAL_STORE=false` |
| 5 | `review_validation.py` — separated checks + review_draft labeling | via render manifest path |
| 6 | `artifact_cache.py` — tenant-scoped idempotency key, atomic publish | `RESUME_ARTIFACT_CACHE=false` |
| 7 | Annotation schema + `eval_annotation_metrics.py` | fixtures under `tests/fixtures/eval_annotations/` |

### Verified this session

- Wave 2 unit tests: **22 passed** (`test_wave2_phases` + ledger/manifest/adapters)
- Golden 3 formats: **PASS** (168/168)

### Still blocked / not claimed production-ready

- Docling **comparative** eval on private fixtures (probe only; not switched)
- hard-12 / corpus-60 Bedrock remeasure (not re-run after Wave 2)
- Full human annotation corpus (schema example only — not “unseen” eval)
- Enabling Wave 2 flags in production without shadow eval
