# Hybrid LLM accuracy upgrades: report

Spec: `docs/superpowers/specs/2026-11-11-hybrid-llm-accuracy-design.md`

## Changes
- `llm_structure_repair.py`
  - `ELIGIBILITY_CONFIDENCE` 0.55 -> 0.70.
  - Also eligible on `parse_meta.reasons` containing `ambiguous_role_assignment` (needs work evidence), `role_identity_garbled` (needs roles), or `expected_experience_missing` (needs work evidence and no roles). Education-only stays ineligible; already-repaired (`llm_repaired`) stays ineligible.
  - Company/title must be a contiguous word run in the source when they have 2+ words. Single-token company/title needs 3+ chars (and the alnum substring). Location, duration, employer-block association and survival rules are unchanged.
  - Bullet check moved into `_bullet_grounded` (full `_norm(bullet)` in source, no partial credit).
  - System prompt now demands verbatim spans only: no paraphrase, shortening, splitting, merging, or invented employers/dates/bullets.
- `resume_generation_service.py`: fixed the stale "off by default" comment. `config.py` had the same stale comment, so I fixed it too.
- Golden CI is untouched: `RESUME_LLM_PARSE_FALLBACK` is still forced false.

## Tests
- `tests/test_llm_structure_repair.py`: 33 passed (11 new). New tests cover:
  - eligibility at 0.65;
  - ineligible at 0.70 with no reasons;
  - each new reason (including the evidence requirement for `expected_experience_missing`);
  - reason-based eligibility skipping already-repaired parses;
  - paraphrased bullets rejected;
  - letter-collapsed company rejected;
  - non-contiguous title rejected;
  - 2-char company rejected;
  - prompt wording.
- Full backend suite (`backend/.venv`): 325 passed, 1 skipped.

## Concerns
1. The bullet rule is implemented as "full `_norm(bullet)` in source" only. The existing code already required that for every bullet, so partial matches were already rejected. I did not add the spec's "OR a contiguous word-run covering >= 85%" alternative. A word-run is a substring of the collapsed text, so it can only matter when the full bullet does not match. Accepting it would let up to 15% unverified words through, and the employer-block position check needs a full-bullet position. If you want trimmed bullets accepted, that needs a separate design.
2. The 3-char minimum on single-token company/title rejects legitimate 2-char names such as "3M" or "EY". This follows the spec. In those cases the repair is dropped and the deterministic parse is kept, so nothing is invented.
3. Raising the threshold to 0.70 and adding reasons means more generations call Bedrock, so latency goes up when repair runs. This matches the accuracy-first spec.
4. Hyphenated or split-word PDF artifacts (for example "deploy-\nment") can fail the contiguous-word check on company/title. The repair is then rejected and the deterministic parse is kept.
