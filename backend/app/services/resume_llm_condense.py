"""
Grounded LLM readable polish for client resumes.

Improves clarity and lightly tightens wording while keeping the essence of every
role. Skills are always taken verbatim from SOURCE (exact tokens — never rewritten).
Never invents employers, schools, skills, or metrics.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agents.tools.llm_client import llm_call_json_with_metrics
from app.core.config import settings
from app.core.logging import logger

_SYSTEM = """You are a senior resume editor creating a client-ready professional resume.
CRITICAL RULES:
1) Use ONLY facts present in the provided SOURCE JSON. Never invent employers, schools, skills, tools, dates, metrics, or achievements.
2) Do not mix content across roles or sections.
3) Keep every employer/role listed in SOURCE experience (same company + title + duration).
4) Improve readability: clear Action + Context + Result bullets. Light summarization is OK — tighten wording and drop near-duplicate/redundant bullets — but keep the essence of each role (tech, products, metrics, domain).
5) Keep at least ~75% of unique substance per role vs SOURCE. Drop obvious near-duplicates (e.g. repeated WCAG/accessibility lines). Never collapse a rich role into 2-3 vague lines.
6) SKILLS: copy SOURCE skills_by_category EXACTLY — same category names and exact skill spellings. Do not rename, regroup, or invent skills.
7) Do not add technologies that are not in that role's source bullets or technologies list.
8) Return ONLY valid JSON.
"""


def polish_store_for_readability(store: dict[str, Any], *, target_pages: float = 5.0) -> dict[str, Any] | None:
    """LLM polish for readability with light essence-preserving summarization."""
    return _run_grounded_store_llm(store, mode="readable", target_pages=target_pages)


def condense_store_with_llm(store: dict[str, Any], *, target_pages: float = 5.0) -> dict[str, Any] | None:
    """Alias — readable polish (not aggressive compression)."""
    return polish_store_for_readability(store, target_pages=target_pages)


def polish_store_with_llm(store: dict[str, Any]) -> dict[str, Any] | None:
    """Professional rewrite for normal-sized / mashed resumes."""
    return _run_grounded_store_llm(store, mode="polish", target_pages=5.0)


def _run_grounded_store_llm(
    store: dict[str, Any],
    *,
    mode: str,
    target_pages: float,
) -> dict[str, Any] | None:
    """Shared grounded LLM path for readable polish and mashed-text polish."""
    try:
        payload = _source_payload(store)
        if mode == "polish":
            instructions = [
                "Mode: PROFESSIONAL POLISH (keep length similar — do not aggressively compress).",
                "Fix missing spaces, jammed words, and awkward formatting.",
                "CRITICAL FORMAT: each experience description item MUST be one short bullet (1-2 sentences max).",
                "Never return a paragraph stream. Split multi-achievement text into separate bullet strings.",
                "Rewrite bullets to clear Action + Context + Result sentences.",
                "Keep ALL experience roles from SOURCE (do not drop employers).",
                "Keep roughly the same bullet count per role (trim only obvious duplicates/noise).",
                "Summary: keep original substance (4-8 lines ok); facts only (summary may be paragraph).",
                "SKILLS: return SOURCE skills_by_category EXACTLY unchanged (exact spellings).",
                "Education: cleaned degree + full institution name + year (never stub labels like Institute/College/IIT alone).",
                "Split mashed certification/achievement lines into clean separate items when needed.",
            ]
        else:
            instructions = [
                f"Target readable length: about {target_pages} pages (client-ready, not a thin stub).",
                "Mode: READABLE ESSENCE — polish for clarity; light summarization only.",
                "Keep ALL experience roles from SOURCE (do not drop employers).",
                "Per role: keep the most important achievements; drop near-duplicates and filler only.",
                "Keep at least ~75% of unique SOURCE bullets per role (never 2-3 lines for a rich role).",
                "Do not repeat the same accessibility/WCAG/MuleSoft theme in multiple near-identical bullets.",
                "Remove code snippets, CLI commands, and contact/phone/email text from summary or bullets.",
                "Preserve every important metric, product name, system, integration, and domain fact in the kept bullets.",
                "CRITICAL FORMAT: each description item is ONE clear bullet (1-2 sentences).",
                "Do NOT invent technologies. Keep technologies ONLY from SOURCE technologies lists.",
                "Never put Environment text into title or location fields.",
                "SKILLS: return SOURCE skills_by_category EXACTLY unchanged (exact spellings, same categories).",
                "Summary: 4-7 professional lines of substance only — no name/phone/email mash in the summary.",
                "Education: return cleaned degree + institution + year only (no profile/Dice noise).",
            ]
        user = "\n".join(
            [
                *instructions,
                "",
                "SOURCE JSON:",
                json.dumps(payload, ensure_ascii=True)[:55000],
                "",
                "Return JSON schema:",
                json.dumps(
                    {
                        "summary": "string",
                        "skills_by_category": {"Category": ["exact skill from source"]},
                        "experience": [
                            {
                                "company": "must match source",
                                "title": "must match source",
                                "duration": "must match source",
                                "location": "optional",
                                "description": ["one achievement per bullet string"],
                                "technologies": ["from source only"],
                            }
                        ],
                        "education": [
                            {"degree": "string", "institution": "string", "year": "string", "location": ""}
                        ],
                    },
                    ensure_ascii=True,
                ),
            ]
        )
        token_budget = 4096 if mode == "polish" else min(8192, max(settings.RESUME_GENERATION_MAX_TOKENS, 4096))
        result = llm_call_json_with_metrics(
            _SYSTEM,
            user,
            validate=_validate_condense_shape,
            repair_attempts=1,
            validation_attempts=1,
            max_tokens=token_budget,
        )
        merged = _merge_condensed(store, result.data)
        if not merged:
            logger.warning("resume_llm_condense_rejected", reason="grounding_or_merge_failed", mode=mode)
            return None
        logger.info(
            "resume_llm_condense_complete",
            mode=mode,
            roles=len(merged.get("experience") or []),
            bullets=sum(len(r.get("description") or []) for r in (merged.get("experience") or [])),
            output_tokens_est=result.metrics.get("output_tokens_est"),
        )
        return merged
    except Exception as exc:
        logger.warning("resume_llm_condense_failed", mode=mode, error=str(exc))
        return None


def _source_payload(store: dict[str, Any]) -> dict[str, Any]:
    experience = []
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        experience.append(
            {
                "company": role.get("company") or "",
                "title": role.get("title") or "",
                "duration": role.get("duration") or "",
                "location": role.get("location") or "",
                "description": list(role.get("description") or [])[:20],
                "technologies": list(role.get("technologies") or [])[:20],
            }
        )
    return {
        "summary": str(store.get("summary") or "")[:3500],
        "skills_by_category": store.get("skills_by_category") or {},
        "experience": experience,
        "education": [
            {
                "degree": e.get("degree") or "",
                "institution": e.get("institution") or "",
                "year": e.get("year") or "",
                "location": e.get("location") or "",
            }
            for e in (store.get("education") or [])
            if isinstance(e, dict)
        ],
    }


def _validate_condense_shape(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Response must be a JSON object."]
    if not str(data.get("summary") or "").strip():
        errors.append("summary is required.")
    if not isinstance(data.get("experience"), list) or not data.get("experience"):
        errors.append("experience list is required.")
    return errors


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _merge_condensed(source: dict[str, Any], condensed: dict[str, Any]) -> dict[str, Any] | None:
    import copy

    out = copy.deepcopy(source)
    src_roles = [r for r in (source.get("experience") or []) if isinstance(r, dict)]
    llm_roles = [r for r in (condensed.get("experience") or []) if isinstance(r, dict)]
    if len(llm_roles) < max(1, int(len(src_roles) * 0.75)):
        return None

    used: set[int] = set()
    merged_roles: list[dict[str, Any]] = []
    for src in src_roles:
        src_company = _norm(src.get("company"))
        src_title = _norm(src.get("title"))
        match = None
        match_idx = -1
        for idx, cand in enumerate(llm_roles):
            if idx in used:
                continue
            if src_company and _norm(cand.get("company")) == src_company:
                match = cand
                match_idx = idx
                break
            if src_title and src_company and src_title in _norm(cand.get("title")) and src_company in _norm(
                cand.get("company")
            ):
                match = cand
                match_idx = idx
                break
        if match is None:
            merged_roles.append(src)
            continue
        used.add(match_idx)
        src_blob = " ".join(str(x) for x in (src.get("description") or [])).lower()
        src_blob += " " + " ".join(str(x) for x in (src.get("technologies") or [])).lower()
        from app.services.structured_resume_store import expand_to_bullets

        src_bullets = expand_to_bullets(list(src.get("description") or []), max_bullets=20)
        raw_bullets = []
        for b in match.get("description") or []:
            text = re.sub(r"\s+", " ", str(b).strip())
            if len(text) < 25:
                continue
            raw_bullets.append(text)
        bullets = []
        for text in expand_to_bullets(raw_bullets, max_bullets=max(16, len(src_bullets))):
            if not _bullet_grounded(text, src_blob, src.get("description") or []):
                continue
            bullets.append(text)
        # Essence floor: keep most of the role's substance.
        min_keep = max(3, int(len(src_bullets) * 0.75)) if src_bullets else 2
        if len(bullets) < min_keep:
            bullets = _backfill_bullets(bullets, src_bullets, max_bullets=max(min_keep, len(src_bullets)))
        if len(bullets) < 2:
            bullets = src_bullets[:16] or expand_to_bullets(list(src.get("description") or []), max_bullets=12)
        techs = list(src.get("technologies") or [])[:16]
        if src_bullets and _role_lost_too_much_detail(src_bullets, bullets):
            bullets = src_bullets[:20]
        merged_roles.append(
            {
                "company": src.get("company") or "",
                "title": src.get("title") or "",
                "duration": src.get("duration") or "",
                "location": src.get("location") or match.get("location") or "",
                "description": bullets[:20],
                "technologies": techs,
            }
        )

    deduped_roles: list[dict[str, Any]] = []
    seen_role_keys: set[str] = set()
    for role in merged_roles:
        key = _norm(role.get("company")) + _norm(role.get("duration"))
        if key and key in seen_role_keys:
            continue
        if key:
            seen_role_keys.add(key)
        deduped_roles.append(role)
    merged_roles = deduped_roles

    summary = re.sub(r"\s+", " ", str(condensed.get("summary") or "").strip())
    src_summary = str(source.get("summary") or "")
    if summary and len(summary) >= 120:
        if not _summary_has_unknown_employer(summary, src_roles):
            if src_summary and len(summary) < max(120, int(len(src_summary) * 0.5)):
                out["summary"] = src_summary
            else:
                out["summary"] = summary
        else:
            out["summary"] = src_summary
    else:
        out["summary"] = src_summary

    # Skills: ALWAYS exact source tokens — never LLM-rewritten.
    src_grouped = source.get("skills_by_category") or {}
    if isinstance(src_grouped, dict) and src_grouped:
        exact: dict[str, list[str]] = {}
        for cat, values in src_grouped.items():
            kept = [str(s).strip() for s in (values or []) if str(s).strip()]
            if kept:
                exact[str(cat).strip()] = kept
        out["skills_by_category"] = exact
        out["skills"] = [s for vals in exact.values() for s in vals]
    else:
        out["skills"] = list(source.get("skills") or [])
        out["skills_by_category"] = source.get("skills_by_category") or {}

    out["education"] = _merge_education(source.get("education") or [], condensed.get("education") or [])
    out["experience"] = merged_roles
    out["stats"] = {
        **(out.get("stats") or {}),
        "experience_count": len(merged_roles),
        "experience_bullets": sum(len(r.get("description") or []) for r in merged_roles),
        "llm_condensed": True,
        "skills_locked_exact": True,
    }
    return out


def _backfill_bullets(llm_bullets: list[str], src_bullets: list[str], *, max_bullets: int) -> list[str]:
    """Keep grounded LLM bullets, then restore uncovered source bullets in order."""
    kept = list(llm_bullets)
    covered = " ".join(kept).lower()
    for src in src_bullets:
        if len(kept) >= max_bullets:
            break
        s = re.sub(r"\s+", " ", str(src).strip())
        if len(s) < 25:
            continue
        head = s.lower()[:50]
        if head and head in covered:
            continue
        tokens = [t for t in re.findall(r"[a-z0-9+]{5,}", s.lower())]
        if tokens and sum(1 for t in tokens if t in covered) >= max(2, int(len(tokens) * 0.6)):
            continue
        kept.append(s)
        covered += " " + s.lower()
    return kept[:max_bullets]


def _role_lost_too_much_detail(src_bullets: list[str], llm_bullets: list[str]) -> bool:
    """True when LLM output is substantially thinner than the selected source bullets."""
    if not src_bullets or not llm_bullets:
        return False
    src_chars = sum(len(b) for b in src_bullets)
    llm_chars = sum(len(b) for b in llm_bullets)
    if llm_chars < max(80, int(src_chars * 0.55)):
        return True
    src_tokens = set(re.findall(r"[a-z0-9+]{5,}", " ".join(src_bullets).lower()))
    llm_blob = " ".join(llm_bullets).lower()
    if not src_tokens:
        return False
    hits = sum(1 for t in src_tokens if t in llm_blob)
    return hits < max(3, int(len(src_tokens) * 0.45))


def _bullet_grounded(text: str, src_blob: str, src_bullets: list[Any]) -> bool:
    low = text.lower()
    for src in src_bullets:
        s = re.sub(r"\s+", " ", str(src).strip().lower())
        if len(s) >= 40 and (s[:60] in low or low[:60] in s):
            return True
    tokens = [t for t in re.findall(r"[a-z0-9+]{4,}", low) if t not in {"with", "from", "using", "that", "this", "have"}]
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in src_blob)
    return hits >= max(3, int(len(tokens) * 0.45))


def _summary_has_unknown_employer(summary: str, roles: list[dict[str, Any]]) -> bool:
    known = {_norm(r.get("company")) for r in roles if r.get("company")}
    for match in re.finditer(r"\bat\s+([A-Z][A-Za-z0-9&.\- ]{2,40})", summary):
        name = _norm(match.group(1))
        if name and name not in known and len(name) > 4:
            if name in {"banking", "healthcare", "telecom", "government", "financialservices"}:
                continue
            if not any(name in k or k in name for k in known if k):
                return True
    return False


def _merge_education(source: list[Any], condensed: list[Any]) -> list[dict[str, Any]]:
    from app.services.structured_resume_store import normalize_education_entries

    base = normalize_education_entries(source)
    if not condensed:
        return base
    cleaned = normalize_education_entries(condensed)
    if not cleaned:
        return base
    src_keys = {_norm(e.get("institution")) + _norm(e.get("degree")) for e in base}
    kept = []
    for row in cleaned:
        key = _norm(row.get("institution")) + _norm(row.get("degree"))
        if any(_norm(row.get("institution")) and _norm(row.get("institution")) in sk for sk in src_keys) or key in src_keys:
            kept.append(row)
        elif any(_norm(row.get("degree")) and _norm(row.get("degree"))[:12] in sk for sk in src_keys):
            kept.append(row)
    return kept or base
