"""
Fit a full structured resume into a 2–3 page professional layout.

Rules:
- Never invent employers, dates, skills, or bullets.
- Never move content across sections.
- Small/medium resumes: keep everything as-is.
- Oversized resumes: select genuine excerpts section-wise to fit the page budget.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from app.core.logging import logger
from app.services.structured_resume_store import normalize_education_entries

# Approximate DOCX density for Calibri ~10–11pt client templates.
_CHARS_PER_PAGE = 3200
_SUMMARY_OVERHEAD = 450
_SKILLS_OVERHEAD = 500
_EDU_PER_ITEM = 90
_ROLE_HEADER = 120
_CHARS_PER_BULLET = 140
_TECH_LINE = 80


def estimate_pages(store: dict[str, Any]) -> float:
    """Rough page estimate from structured content volume."""
    chars = 0
    summary = str(store.get("summary") or "")
    chars += min(len(summary), 1200) + (_SUMMARY_OVERHEAD if summary else 0)

    skills = store.get("skills_by_category") or {}
    if isinstance(skills, dict) and skills:
        skill_text = sum(len(k) + sum(len(s) for s in (v or [])) for k, v in skills.items())
        chars += skill_text + _SKILLS_OVERHEAD
    else:
        chars += sum(len(s) for s in (store.get("skills") or [])) + 200

    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        chars += _ROLE_HEADER
        chars += len(role.get("description") or []) * _CHARS_PER_BULLET
        if role.get("technologies"):
            chars += _TECH_LINE

    chars += len(store.get("education") or []) * _EDU_PER_ITEM
    for proj in store.get("projects") or []:
        if isinstance(proj, dict):
            chars += _ROLE_HEADER + len(proj.get("description") or []) * _CHARS_PER_BULLET
    chars += len(store.get("certifications") or []) * 60
    chars += len(store.get("achievements") or []) * 60

    return max(0.5, chars / _CHARS_PER_PAGE)


def needs_page_fit(store: dict[str, Any], target_pages: float = 3.0) -> bool:
    return estimate_pages(store) > (target_pages + 0.15)


def fit_store_to_pages(
    store: dict[str, Any],
    *,
    target_pages: float = 3.0,
) -> dict[str, Any]:
    """
    Return a store sized for ~target_pages.

    If already within budget, returns a deep copy unchanged.
    Oversized content is reduced by selecting real bullets/skills only.
    """
    original = copy.deepcopy(store)
    before = estimate_pages(original)
    if before <= target_pages + 0.15:
        original["fit"] = {
            "applied": False,
            "pages_before": round(before, 2),
            "pages_after": round(before, 2),
            "target_pages": target_pages,
        }
        return original

    fitted = copy.deepcopy(original)
    fitted["summary"] = _fit_summary(str(fitted.get("summary") or ""), max_chars=950)
    fitted["skills_by_category"] = _fit_skills(fitted.get("skills_by_category") or {}, max_per_category=14)
    fitted["skills"] = _flatten_skills(fitted["skills_by_category"]) or list(fitted.get("skills") or [])[:80]
    fitted["experience"] = _fit_experience(
        fitted.get("experience") or [],
        target_pages=target_pages,
    )
    fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=2, bullets=3)
    fitted["education"] = _fit_education(fitted.get("education") or [])
    # Keep certs/achievements short; drop noisy "languages" skill dumps.
    fitted["certifications"] = list(fitted.get("certifications") or [])[:8]
    fitted["achievements"] = list(fitted.get("achievements") or [])[:6]
    fitted["languages"] = _fit_spoken_languages(fitted.get("languages") or [])

    # Recompute stats for the fitted view (full store remains in raw if needed).
    fitted["stats"] = {
        **(original.get("stats") or {}),
        "experience_count": len(fitted.get("experience") or []),
        "experience_bullets": sum(len(e.get("description") or []) for e in (fitted.get("experience") or [])),
        "education_count": len(fitted.get("education") or []),
        "skills_count": sum(len(v) for v in (fitted.get("skills_by_category") or {}).values())
        or len(fitted.get("skills") or []),
        "projects_count": len(fitted.get("projects") or []),
        "fitted": True,
    }
    after = estimate_pages(fitted)

    # If still over budget, tighten bullets once more (still genuine selection).
    if after > target_pages + 0.25:
        fitted["experience"] = _fit_experience(
            fitted.get("experience") or [],
            target_pages=target_pages,
            tight=True,
        )
        fitted["skills_by_category"] = _fit_skills(fitted.get("skills_by_category") or {}, max_per_category=10)
        fitted["skills"] = _flatten_skills(fitted["skills_by_category"])
        fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=1, bullets=2)
        fitted["stats"]["experience_bullets"] = sum(
            len(e.get("description") or []) for e in (fitted.get("experience") or [])
        )
        after = estimate_pages(fitted)

    fitted["fit"] = {
        "applied": True,
        "pages_before": round(before, 2),
        "pages_after": round(after, 2),
        "target_pages": target_pages,
        "roles_kept": len(fitted.get("experience") or []),
        "bullets_kept": fitted["stats"]["experience_bullets"],
    }
    logger.info("resume_page_fit_applied", **fitted["fit"])
    return fitted


def _fit_summary(text: str, max_chars: int = 950) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_chars:
        return text
    # Prefer sentence boundaries — never invent wording.
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept: list[str] = []
    total = 0
    for part in parts:
        if not part:
            continue
        if total + len(part) + 1 > max_chars and kept:
            break
        kept.append(part)
        total += len(part) + 1
        if len(kept) >= 5:
            break
    out = " ".join(kept).strip()
    return out or text[:max_chars].rsplit(" ", 1)[0].strip()


def _fit_skills(grouped: dict[str, Any], max_per_category: int = 14) -> dict[str, list[str]]:
    if not isinstance(grouped, dict):
        return {}
    out: dict[str, list[str]] = {}
    for category, values in grouped.items():
        name = str(category).strip()
        if not name:
            continue
        # Never put experience-like sentences into skills.
        clean = [
            str(v).strip()
            for v in (values or [])
            if str(v).strip()
            and len(str(v).split()) <= 12
            and not re.search(r"(?i)\b(responsible for|led a team|developed a|architected)\b", str(v))
        ]
        if clean:
            out[name] = clean[:max_per_category]
    return out


def _flatten_skills(grouped: dict[str, list[str]]) -> list[str]:
    flat: list[str] = []
    seen: set[str] = set()
    for values in (grouped or {}).values():
        for skill in values:
            key = skill.casefold()
            if key in seen:
                continue
            seen.add(key)
            flat.append(skill)
    return flat


def _fit_experience(
    roles: list[Any],
    *,
    target_pages: float = 3.0,
    tight: bool = False,
) -> list[dict[str, Any]]:
    """Keep every role identity; select strongest genuine bullets by recency weight."""
    normalized = [r for r in roles if isinstance(r, dict)]
    if not normalized:
        return []

    n = len(normalized)
    # Budget bullets for ~target pages after summary/skills/education overhead (~1 page).
    body_pages = max(1.2, target_pages - 1.0)
    total_budget = int(body_pages * 10)  # ~10 bullets/page body density
    if tight:
        total_budget = max(18, int(total_budget * 0.75))
    total_budget = max(n * 2, min(total_budget, 55))  # at least 2 bullets/role when possible

    # Recency weights: first roles assumed reverse-chronological.
    weights = [max(1.0, float(n - i)) for i in range(n)]
    weight_sum = sum(weights) or 1.0
    quotas = [max(2 if not tight else 1, int(round(total_budget * (w / weight_sum)))) for w in weights]
    # Cap per-role so one job doesn't dominate.
    max_each = 6 if not tight else 4
    quotas = [min(max_each, q) for q in quotas]
    # Adjust to budget.
    while sum(quotas) > total_budget:
        # Trim from oldest roles first.
        for i in range(n - 1, -1, -1):
            if quotas[i] > (1 if tight else 2):
                quotas[i] -= 1
                break
        else:
            break
    while sum(quotas) < min(total_budget, sum(len(r.get("description") or []) for r in normalized)):
        grew = False
        for i in range(n):
            available = len(normalized[i].get("description") or [])
            if quotas[i] < min(max_each, available):
                quotas[i] += 1
                grew = True
                if sum(quotas) >= total_budget:
                    break
        if not grew:
            break

    fitted: list[dict[str, Any]] = []
    for role, quota in zip(normalized, quotas):
        clone = {
            "title": role.get("title") or "",
            "company": role.get("company") or "",
            "location": role.get("location") or "",
            "duration": role.get("duration") or "",
            "description": _select_bullets(list(role.get("description") or []), quota),
            "technologies": list(role.get("technologies") or [])[:12],
        }
        fitted.append(clone)
    return fitted


def _select_bullets(bullets: list[str], quota: int) -> list[str]:
    """Pick up to quota bullets from source only — ranked, never rewritten."""
    cleaned = [re.sub(r"\s+", " ", str(b).strip()) for b in bullets if str(b).strip()]
    cleaned = [b for b in cleaned if len(b) >= 25]
    if len(cleaned) <= quota:
        return cleaned
    ranked = sorted(cleaned, key=_bullet_score, reverse=True)
    chosen = ranked[:quota]
    # Preserve original order for readability.
    chosen_set = set(chosen)
    return [b for b in cleaned if b in chosen_set][:quota]


def _bullet_score(text: str) -> float:
    score = 0.0
    low = text.lower()
    # Prefer quantified / impactful genuine bullets.
    if re.search(r"\d", text):
        score += 3.0
    if re.search(r"(?i)\b(led|architected|designed|implemented|developed|optimized|delivered|built|engineered)\b", text):
        score += 2.0
    if re.search(r"(?i)\b(aws|azure|kafka|kubernetes|spring|microservices|react|angular|python|java)\b", text):
        score += 1.0
    # Prefer mid-length substance over tiny fragments or mega-paragraphs.
    length = len(text)
    if 80 <= length <= 280:
        score += 2.0
    elif length > 280:
        score += 0.5
    if "responsible for" in low or "worked on" in low:
        score -= 1.0
    return score


def _fit_projects(projects: list[Any], keep: int = 2, bullets: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        if not (item.get("name") or item.get("title")):
            continue
        out.append(
            {
                "name": item.get("name") or item.get("title") or "",
                "description": _select_bullets(list(item.get("description") or []), bullets),
                "technologies": list(item.get("technologies") or [])[:10],
                "link": item.get("link") or "",
                "duration": item.get("duration") or "",
            }
        )
        if len(out) >= keep:
            break
    return out


def _fit_education(education: list[Any]) -> list[dict[str, Any]]:
    """Keep real degrees only; drop Dice/profile noise details."""
    return normalize_education_entries(education)


def _fit_spoken_languages(values: list[Any]) -> list[str]:
    """Keep only short spoken-language style entries — not Tools/Platforms dumps."""
    out: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text or len(text) > 40 or len(text.split()) > 5:
            continue
        if re.search(r"(?i)\b(git|aws|java|spring|docker|jenkins|tools|platforms)\b", text):
            continue
        out.append(text)
    return out[:8]
