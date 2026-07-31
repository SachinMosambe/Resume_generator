"""
Fit a full structured resume into a client-ready page budget.

Rules:
- Never invent employers, dates, skills, or bullets.
- Never move content across sections.
- Small/medium resumes: keep everything as-is.
- Oversized resumes: select the most important genuine bullets/projects.
- Summarize by importance — never collapse a long career into a thin 2-page stub.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from app.core.logging import logger
from app.services.structured_resume_store import normalize_education_entries

# Approximate DOCX density for Calibri/Arial ~10–11pt client templates.
# Lower chars/page ≈ more conservative page estimates → richer fitted output.
_CHARS_PER_PAGE = 3000
_SUMMARY_OVERHEAD = 450
_SKILLS_OVERHEAD = 500
_EDU_PER_ITEM = 90
_ROLE_HEADER = 120
_CHARS_PER_BULLET = 150
_TECH_LINE = 80
_UNIQUE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+.#-]{3,}", re.I)
_HIGH_SIGNAL_RE = re.compile(
    r"(?i)\b(mulesoft|camp|forge|bedrock|oauth|graphql|terraform|eks|fargate|"
    r"databricks|anypoint|raml|dataweave|wcag|openai|langgraph|langchain|"
    r"aws|azure|kafka|kubernetes|spring|microservices|react|angular|python|java|"
    r"docker|jenkins|salesforce|snowflake|redshift|dynamodb|postgres|mongodb|"
    r"spark|flink|airflow|redis|elasticsearch|rabbitmq|grpc|webpack|nextjs)\b"
)
_GENERIC_VERB_RE = re.compile(
    r"(?i)^(implemented|developed|designed|improved|delivered|collaborated|supported|"
    r"participated|documented|mentored|worked|built|created|managed|led|helped)$"
)


def resolve_target_pages(pages_full: float, configured: float = 4.0) -> float:
    """
    Scale the fit target with source length.

    A ~9 page career resume should land around 4–5 pages (important facts kept),
    not collapse to ~2 pages.
    """
    configured = max(3.0, float(configured or 4.0))
    pages_full = max(0.5, float(pages_full or 0.5))
    if pages_full <= configured + 0.2:
        return configured
    # Keep about half the source length for very long resumes, capped for client formats.
    scaled = pages_full * 0.5
    return round(min(5.0, max(configured, scaled)), 2)


def estimate_pages(store: dict[str, Any]) -> float:
    """Rough page estimate from structured content volume."""
    chars = 0
    summary = str(store.get("summary") or "")
    chars += min(len(summary), 1800) + (_SUMMARY_OVERHEAD if summary else 0)

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
        for bullet in role.get("description") or []:
            chars += min(max(len(str(bullet)), 60), 320)
        if role.get("technologies"):
            chars += _TECH_LINE

    chars += len(store.get("education") or []) * _EDU_PER_ITEM
    for proj in store.get("projects") or []:
        if isinstance(proj, dict):
            chars += _ROLE_HEADER
            for bullet in proj.get("description") or []:
                chars += min(max(len(str(bullet)), 60), 280)
    chars += len(store.get("certifications") or []) * 60
    chars += len(store.get("achievements") or []) * 60

    return max(0.5, chars / _CHARS_PER_PAGE)


def needs_page_fit(store: dict[str, Any], target_pages: float = 4.0) -> bool:
    return estimate_pages(store) > (target_pages + 0.2)


def fit_store_to_pages(
    store: dict[str, Any],
    *,
    target_pages: float = 4.0,
) -> dict[str, Any]:
    """
    Return a store sized for ~target_pages by keeping the most important genuine content.
    """
    original = copy.deepcopy(store)
    before = estimate_pages(original)
    effective_target = resolve_target_pages(before, target_pages)
    if before <= effective_target + 0.2:
        original["fit"] = {
            "applied": False,
            "pages_before": round(before, 2),
            "pages_after": round(before, 2),
            "target_pages": effective_target,
        }
        return original

    fitted = copy.deepcopy(original)
    fitted["summary"] = _fit_summary(str(fitted.get("summary") or ""), max_chars=1600)
    fitted["skills_by_category"] = _fit_skills(fitted.get("skills_by_category") or {}, max_per_category=20)
    fitted["skills"] = _flatten_skills(fitted["skills_by_category"]) or list(fitted.get("skills") or [])[:120]
    fitted["experience"] = _fit_experience(
        fitted.get("experience") or [],
        target_pages=effective_target,
    )
    # Retention floor: never throw away most of a long career's substance.
    source_bullets = sum(len(r.get("description") or []) for r in (original.get("experience") or []) if isinstance(r, dict))
    kept_bullets = sum(len(r.get("description") or []) for r in (fitted.get("experience") or []) if isinstance(r, dict))
    min_keep = max(source_bullets * 65 // 100, len(original.get("experience") or []) * 5)
    if source_bullets and kept_bullets < min_keep:
        fitted["experience"] = _fit_experience(
            original.get("experience") or [],
            target_pages=effective_target,
            min_total_bullets=min_keep,
        )
    fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=5, bullets=5)
    fitted["education"] = _fit_education(fitted.get("education") or [])
    fitted["certifications"] = list(fitted.get("certifications") or [])[:14]
    fitted["achievements"] = list(fitted.get("achievements") or [])[:12]
    fitted["languages"] = _fit_spoken_languages(fitted.get("languages") or [])

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

    # Only tighten if still well over budget — prefer information over extreme brevity.
    if after > effective_target + 0.6:
        fitted["experience"] = _fit_experience(
            fitted.get("experience") or [],
            target_pages=effective_target,
            tight=True,
        )
        fitted["skills_by_category"] = _fit_skills(fitted.get("skills_by_category") or {}, max_per_category=14)
        fitted["skills"] = _flatten_skills(fitted["skills_by_category"])
        fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=4, bullets=4)
        fitted["stats"]["experience_bullets"] = sum(
            len(e.get("description") or []) for e in (fitted.get("experience") or [])
        )
        after = estimate_pages(fitted)

    fitted["fit"] = {
        "applied": True,
        "pages_before": round(before, 2),
        "pages_after": round(after, 2),
        "target_pages": effective_target,
        "roles_kept": len(fitted.get("experience") or []),
        "bullets_kept": fitted["stats"]["experience_bullets"],
        "projects_kept": len(fitted.get("projects") or []),
    }
    logger.info("resume_page_fit_applied", **fitted["fit"])
    return fitted


def _fit_summary(text: str, max_chars: int = 1600) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_chars:
        return text
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
        if len(kept) >= 10:
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
    target_pages: float = 4.0,
    tight: bool = False,
    min_total_bullets: int | None = None,
) -> list[dict[str, Any]]:
    """Keep every role identity; keep the strongest genuine bullets by recency weight."""
    normalized = [r for r in roles if isinstance(r, dict)]
    if not normalized:
        return []

    n = len(normalized)
    # Body after summary/skills/education overhead (~1.0 page).
    body_pages = max(2.0, target_pages - 1.0)
    total_budget = int(body_pages * 26)
    if tight:
        total_budget = max(56, int(total_budget * 0.9))
    # Floor scales with role count so multi-employer careers stay informative.
    total_budget = max(n * 6, min(total_budget, 180))
    if min_total_bullets:
        total_budget = max(total_budget, int(min_total_bullets))

    weights = [max(1.0, float(n - i)) for i in range(n)]
    weight_sum = sum(weights) or 1.0
    min_each = 5 if not tight else 4
    quotas = [max(min_each, int(round(total_budget * (w / weight_sum)))) for w in weights]
    max_each = 20 if not tight else 14
    quotas = [min(max_each, q) for q in quotas]

    while sum(quotas) > total_budget:
        for i in range(n - 1, -1, -1):
            if quotas[i] > min_each:
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
        techs = [
            str(t).strip()
            for t in (role.get("technologies") or [])
            if str(t).strip() and len(str(t).strip()) <= 60 and len(str(t).split()) <= 6
        ][:16]
        bullets = _select_bullets(list(role.get("description") or []), quota)
        bullets = [_shorten_bullet_keep_core(b) for b in bullets]
        clone = {
            "title": role.get("title") or "",
            "company": role.get("company") or "",
            "location": role.get("location") or "",
            "duration": role.get("duration") or "",
            "description": bullets,
            "technologies": techs,
        }
        fitted.append(clone)
    return fitted


def _shorten_bullet_keep_core(text: str, max_chars: int = 280) -> str:
    """Trim only very long bullets at sentence boundaries — keep lead facts/metrics."""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if len(text) <= max_chars:
        return text
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
        if len(kept) >= 2:
            break
    out = " ".join(kept).strip()
    if out and len(out) >= 60:
        return out
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def _select_bullets(bullets: list[str], quota: int) -> list[str]:
    """Pick up to quota bullets from source only — ranked by importance, never rewritten."""
    cleaned = [re.sub(r"\s+", " ", str(b).strip()) for b in bullets if str(b).strip()]
    cleaned = [b for b in cleaned if len(b) >= 25]
    if len(cleaned) <= quota:
        return cleaned

    token_owners: dict[str, list[int]] = {}
    for idx, bullet in enumerate(cleaned):
        for token in _unique_info_tokens(bullet):
            token_owners.setdefault(token, []).append(idx)
    must_keep: set[int] = set()
    for _token, owners in token_owners.items():
        if len(owners) == 1:
            must_keep.add(owners[0])
    for idx, bullet in enumerate(cleaned):
        if re.search(r"\d", bullet) or _HIGH_SIGNAL_RE.search(bullet):
            must_keep.add(idx)

    ranked_idxs = sorted(range(len(cleaned)), key=lambda i: _bullet_score(cleaned[i]), reverse=True)
    chosen_idxs: list[int] = []
    for idx in ranked_idxs:
        if idx in must_keep and len(chosen_idxs) < quota:
            chosen_idxs.append(idx)
    for idx in ranked_idxs:
        if len(chosen_idxs) >= quota:
            break
        if idx not in chosen_idxs:
            chosen_idxs.append(idx)
    chosen_set = set(chosen_idxs[:quota])
    return [cleaned[i] for i in range(len(cleaned)) if i in chosen_set][:quota]


def _unique_info_tokens(text: str) -> set[str]:
    """Tokens that look like tech/product/domain entities — not generic English."""
    stop = {
        "with", "from", "using", "that", "this", "have", "been", "were", "their",
        "team", "project", "system", "application", "applications", "services",
        "based", "across", "including", "through", "while", "into", "over",
        "feature", "features", "platform", "reliability", "delivery", "practices",
        "engineers", "managers", "planning", "release", "weekly", "sprint",
    }
    out: set[str] = set()
    for raw in _UNIQUE_TOKEN_RE.findall(text or ""):
        token = raw.lower().strip(".-+")
        if len(token) < 4 or token in stop:
            continue
        if token.isdigit() or _GENERIC_VERB_RE.match(token):
            continue
        if (
            any(ch.isdigit() for ch in token)
            or "+" in raw
            or "#" in raw
            or "." in raw
            or _HIGH_SIGNAL_RE.search(token)
            or len(token) >= 8
        ):
            out.add(token)
    return out


def _bullet_score(text: str) -> float:
    score = 0.0
    low = text.lower()
    if re.search(r"\d", text):
        score += 3.0
    if re.search(r"(?i)\b(led|architected|designed|implemented|developed|optimized|delivered|built|engineered)\b", text):
        score += 2.0
    if re.search(r"(?i)\b(aws|azure|kafka|kubernetes|spring|microservices|react|angular|python|java)\b", text):
        score += 1.0
    if _HIGH_SIGNAL_RE.search(text):
        score += 2.5
    length = len(text)
    if 80 <= length <= 280:
        score += 2.0
    elif length > 280:
        score += 0.5
    if "responsible for" in low or "worked on" in low:
        score -= 1.0
    return score


def _fit_projects(projects: list[Any], keep: int = 5, bullets: int = 5) -> list[dict[str, Any]]:
    """Keep the strongest projects with their most important bullets."""
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        if not (item.get("name") or item.get("title")):
            continue
        desc = list(item.get("description") or [])
        score = sum(_bullet_score(str(b)) for b in desc) + (2.0 if item.get("technologies") else 0.0)
        score += min(3.0, len(desc) * 0.4)
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    out: list[dict[str, Any]] = []
    for _score, item in scored[:keep]:
        out.append(
            {
                "name": item.get("name") or item.get("title") or "",
                "description": [
                    _shorten_bullet_keep_core(b, max_chars=260)
                    for b in _select_bullets(list(item.get("description") or []), bullets)
                ],
                "technologies": list(item.get("technologies") or [])[:12],
                "link": item.get("link") or "",
                "duration": item.get("duration") or "",
            }
        )
    # Preserve original project order among the kept set for readability.
    if not out:
        return []
    kept_names = {str(p.get("name") or "").casefold() for p in out}
    ordered = []
    for item in projects:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or "").casefold()
        if name in kept_names:
            match = next((p for p in out if str(p.get("name") or "").casefold() == name), None)
            if match and match not in ordered:
                ordered.append(match)
    return ordered or out


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
