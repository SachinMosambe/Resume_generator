# Wave 3: Fidelity engineering (layout → grounded copy → render gate)

## Goal
Recover corpus bar after Wave-2 extract overreach; keep Matt/Shanley-class wins; push toward accurate source_lines without weakening integrity.

## Approach (approved)
1. **Narrow extract** — flag + conservative filters for projects/certs/narrative headers
2. **Render-manifest gate** — required expected_text must appear in DOCX or blocking finding
3. **Layout fallback** — Docling (or existing OCR path) only when layout/OCR hard
4. **Wrong-role** — narrative headers must not false-trigger misassignment
5. Remeasure hard-12 + corpus-60

## Non-goals
- Full vision on every resume
- Weakening integrity bar definitions

## Implemented
- Conservative project/other bullet scoop (no phantom employers) + cert scoop
- Narrative headers → expand title (reduce wrong-role)
- Keep prior joined unassigned texts (don’t fragment via ledger fuzzy match)
- Render manifest includes certs/unassigned; missing_required_text → blocking
- Docling layout fallback when column/OCR/short-text hard (if installed)
- Flags in config + `.env.example`

## Spot checks
- Matt: source_lines hard=0
- Shanley: missing hard cleared after unassigned-keep fix
