"""
Grounded LLM condensation for oversized resumes.

Rewrites summary/bullets for a 2–3 page professional resume using ONLY facts
from the structured store. Never invents employers, schools, skills, or metrics.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agents.tools.llm_client import llm_call_json_with_metrics
from app.core.config import settings
from app.core.logging import logger

_SYSTEM = """You are a senior resume editor. You compress resumes for a 2-3 page client format.
CRITICAL RULES:
1) Use ONLY facts present in the provided SOURCE JSON. Never invent employers, schools, skills, tools, dates, metrics, or achievements.
2) Do not mix content across roles or sections.
3) Keep every employer/role listed in SOURCE experience (same company + title + duration).
4) Rewrite bullets to be concise, professional, and impactful — but every bullet must be supported by SOURCE bullets for that same role.
5) Do not add new technologies that are not in that role's source bullets or technologies list.
6) Return ONLY valid JSON.
"""


def condense_store_with_llm(store: dict[str, Any], *, target_pages: float = 3.0) -> dict[str, Any] | None:
    """Compress a page-fitted store with one grounded LLM pass."""
    return _run_grounded_store_llm(
        store,
        mode="condense",
        target_pages=target_pages,
    )


def polish_store_with_llm(store: dict[str, Any]) -> dict[str, Any] | None:
    """
    Professional rewrite for normal-sized resumes (no aggressive compression).

    Fixes spacing/wording while keeping all roles and genuine facts.
    """
    return _run_grounded_store_llm(store, mode="polish", target_pages=3.0)


def _run_grounded_store_llm(
    store: dict[str, Any],
    *,
    mode: str,
    target_pages: float,
) -> dict[str, Any] | None:
    """Shared grounded LLM path for condense (large) and polish (normal)."""
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
                "Summary: 4-6 dense professional lines, facts only (summary may be paragraph).",
                "Skills: keep categories; atomic skill names from SOURCE only.",
                "Education: cleaned degree + full institution name + year (never stub labels like Institute/College/IIT alone).",
                "Split mashed certification/achievement lines into clean separate items when needed.",
            ]
        else:
            instructions = [
                f"Target length: about {target_pages} pages.",
                "Compress wording and keep the strongest genuine accomplishments.",
                "Keep ALL experience roles from SOURCE (do not drop employers).",
                "Aim for 5-7 bullets per recent role and 3-4 for older roles.",
                "CRITICAL FORMAT: each description item is ONE bullet (not a paragraph of many achievements).",
                "Do NOT invent technologies. Keep technologies ONLY from SOURCE technologies/Environment lists.",
                "Never put Environment text into title or location fields.",
                "Keep SOURCE skills_by_category names and trim within those categories only.",
                "Summary: 4-6 dense lines, facts only.",
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
                        "skills_by_category": {"Category": ["skill"]},
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
        # Polish stays smaller/faster; condense may need more output for multi-role resumes.
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
                "description": list(role.get("description") or [])[:14],
                "technologies": list(role.get("technologies") or [])[:16],
            }
        )
    return {
        "summary": str(store.get("summary") or "")[:2500],
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

    # Map LLM roles back onto source roles by company/title identity.
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
            # Keep source role unchanged if LLM dropped/mismatched it.
            merged_roles.append(src)
            continue
        used.add(match_idx)
        src_blob = " ".join(str(x) for x in (src.get("description") or [])).lower()
        src_blob += " " + " ".join(str(x) for x in (src.get("technologies") or [])).lower()
        from app.services.structured_resume_store import expand_to_bullets

        raw_bullets = []
        for b in match.get("description") or []:
            text = re.sub(r"\s+", " ", str(b).strip())
            if len(text) < 25:
                continue
            raw_bullets.append(text)
        # Ensure LLM paragraph streams become discrete bullets.
        bullets = []
        for text in expand_to_bullets(raw_bullets, max_bullets=8):
            if not _bullet_grounded(text, src_blob, src.get("description") or []):
                continue
            bullets.append(text)
        if len(bullets) < 2:
            bullets = expand_to_bullets(list(src.get("description") or []), max_bullets=6)
        techs = []
        src_techs = {str(t).strip().lower() for t in (src.get("technologies") or []) if str(t).strip()}
        for t in match.get("technologies") or []:
            name = str(t).strip()
            if name and name.lower() in src_techs:
                techs.append(name)
        if not techs:
            techs = list(src.get("technologies") or [])[:12]
        merged_roles.append(
            {
                "company": src.get("company") or "",
                "title": src.get("title") or "",
                "duration": src.get("duration") or "",
                "location": src.get("location") or match.get("location") or "",
                "description": bullets[:6],
                "technologies": techs[:12],
            }
        )

    # Hard dedupe by company+duration (LLM rewrite sometimes repeats roles).
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

    # Summary: accept only if not tiny and not wildly unrelated.
    summary = re.sub(r"\s+", " ", str(condensed.get("summary") or "").strip())
    src_summary = str(source.get("summary") or "")
    if summary and len(summary) >= 120:
        # Reject if LLM invented obvious employers not in source.
        if not _summary_has_unknown_employer(summary, src_roles):
            out["summary"] = summary
        else:
            out["summary"] = src_summary
    else:
        out["summary"] = src_summary

    # Skills: prefer source categories; only trim within them (never LLM remaps Soft Skills wrongly).
    src_grouped = source.get("skills_by_category") or {}
    if isinstance(src_grouped, dict) and src_grouped:
        llm_skills = condensed.get("skills_by_category") or {}
        cleaned_skills: dict[str, list[str]] = {}
        for cat, values in src_grouped.items():
            src_names = [str(s).strip() for s in (values or []) if str(s).strip()]
            src_set = {s.lower() for s in src_names}
            kept = []
            if isinstance(llm_skills, dict):
                # Match LLM category loosely to source category.
                llm_vals = []
                for lcat, lvals in llm_skills.items():
                    if str(lcat).strip().lower() == str(cat).strip().lower() or str(cat).lower() in str(lcat).lower():
                        llm_vals.extend(lvals or [])
                for skill in llm_vals:
                    name = str(skill).strip()
                    if name and name.lower() in src_set:
                        kept.append(name)
            if not kept:
                kept = src_names[:14]
            cleaned_skills[str(cat).strip()] = kept[:14]
        out["skills_by_category"] = cleaned_skills
        out["skills"] = [s for vals in cleaned_skills.values() for s in vals]
    else:
        # Fallback: only keep names that exist in source skill universe.
        src_skills = {str(s).strip().lower() for s in (source.get("skills") or [])}
        llm_skills = condensed.get("skills_by_category") or {}
        cleaned_skills = {}
        if isinstance(llm_skills, dict):
            for cat, values in llm_skills.items():
                kept = []
                for skill in values or []:
                    name = str(skill).strip()
                    if name and name.lower() in src_skills:
                        kept.append(name)
                if kept:
                    cleaned_skills[str(cat).strip()] = kept[:14]
        if cleaned_skills:
            out["skills_by_category"] = cleaned_skills
            out["skills"] = [s for vals in cleaned_skills.values() for s in vals]

    # Education: prefer cleaned LLM rows only when institution/degree match source.
    out["education"] = _merge_education(source.get("education") or [], condensed.get("education") or [])
    out["experience"] = merged_roles
    out["stats"] = {
        **(out.get("stats") or {}),
        "experience_count": len(merged_roles),
        "experience_bullets": sum(len(r.get("description") or []) for r in merged_roles),
        "llm_condensed": True,
    }
    return out


def _bullet_grounded(text: str, src_blob: str, src_bullets: list[Any]) -> bool:
    low = text.lower()
    # Exact-ish containment of a shortened source bullet is ideal.
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
    # Heuristic: quoted/Title Case company-like phrases are hard; skip aggressive check.
    # Flag only if summary mentions a clear "at X" company not in known set.
    for match in re.finditer(r"\bat\s+([A-Z][A-Za-z0-9&.\- ]{2,40})", summary):
        name = _norm(match.group(1))
        if name and name not in known and len(name) > 4:
            # Allow common non-employer words
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
    # Prefer cleaned entries that match source institutions/degrees.
    src_keys = {_norm(e.get("institution")) + _norm(e.get("degree")) for e in base}
    kept = []
    for row in cleaned:
        key = _norm(row.get("institution")) + _norm(row.get("degree"))
        if any(_norm(row.get("institution")) and _norm(row.get("institution")) in sk for sk in src_keys) or key in src_keys:
            kept.append(row)
        elif any(_norm(row.get("degree")) and _norm(row.get("degree"))[:12] in sk for sk in src_keys):
            kept.append(row)
    return kept or base
