"""
Fit a full structured resume into a client-ready page budget.

Rules:
- Never invent employers, dates, skills, or bullets.
- Never move content across sections.
- Small/medium resumes: keep everything as-is.
- Long careers: moderate summarize (dedupe + soft caps) before hard page-fit.
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
# Code/CLI dumps and misplaced section labels — not client-ready bullets.
_GARBAGE_BULLET_RE = re.compile(
    r"(?i)("
    r"\.builder\s*\(|\.get\s*or\s*create\s*\(|\.getOrCreate\s*\(|"
    r"Session\.builder|SparkSession|"
    r"openstack\s+server\s+create|--image\s+|\\\s*--|"
    r"```|npm\s+install|pip\s+install|"
    r"^\s*education\s*:"
    r")"
)
_CONTACT_MASH_RE = re.compile(
    r"(?i)^(?:[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,5}\s*[|•]\s*)?"
    r"(?:C\s*:\s*\S+\s*)?(?:[|•]\s*)?(?:E\s*:\s*\S+\s*)+"
)
_TITLE_ONLY_BULLET_RE = re.compile(
    r"(?i)^(java|python|full[\s-]?stack|backend|frontend|software|senior|lead|"
    r"technology|engineer|developer|programmer|architect)"
    r"([\s/-]+(java|python|full[\s-]?stack|backend|frontend|software|senior|lead|"
    r"technology|engineer|developer|programmer|architect)){0,4}$"
)


def resolve_target_pages(pages_full: float, configured: float = 5.0) -> float:
    """
    Scale the fit target with source length for a readable client resume.

    A ~9 page career resume should land around ~5 pages with essence kept —
    never collapse to ~2 pages.
    """
    configured = max(4.0, float(configured or 5.0))
    pages_full = max(0.5, float(pages_full or 0.5))
    if pages_full <= configured + 0.2:
        return configured
    # Keep ~55-60% of source length, capped for readable client formats.
    scaled = pages_full * 0.58
    return round(min(6.0, max(configured, scaled)), 2)


def light_trim_store(store: dict[str, Any]) -> dict[str, Any]:
    """
    Keep nearly all content for long careers.

    Only soft-shortens mega-paragraph bullets; never drops roles/projects/bullets.
    """
    fitted = copy.deepcopy(store)
    fitted["summary"] = _fit_summary(str(fitted.get("summary") or ""), max_chars=2200)
    experience = []
    for role in fitted.get("experience") or []:
        if not isinstance(role, dict):
            continue
        clone = dict(role)
        clone["description"] = [
            _shorten_bullet_keep_core(str(b), max_chars=340)
            for b in (role.get("description") or [])
            if str(b).strip()
        ]
        experience.append(clone)
    fitted["experience"] = experience
    projects = []
    for proj in fitted.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        clone = dict(proj)
        clone["description"] = [
            _shorten_bullet_keep_core(str(b), max_chars=300)
            for b in (proj.get("description") or [])
            if str(b).strip()
        ]
        projects.append(clone)
    fitted["projects"] = projects
    fitted["stats"] = {
        **(fitted.get("stats") or {}),
        "experience_count": len(experience),
        "experience_bullets": sum(len(r.get("description") or []) for r in experience),
        "projects_count": len(projects),
        "light_trimmed": True,
    }
    fitted["fit"] = {
        "applied": False,
        "mode": "light_trim",
        "pages_before": round(estimate_pages(store), 2),
        "pages_after": round(estimate_pages(fitted), 2),
        "roles_kept": len(experience),
        "bullets_kept": fitted["stats"]["experience_bullets"],
        "projects_kept": len(projects),
    }
    logger.info("resume_light_trim_applied", **fitted["fit"])
    return fitted


def moderate_summarize_store(store: dict[str, Any]) -> dict[str, Any]:
    """
    Better client summary for long careers — not aggressive.

    Keeps every role and nearly all unique substance. Removes contact mash,
    code/CLI dumps, near-duplicate bullets, and soft-caps density by recency.
    """
    fitted = copy.deepcopy(store)
    before = estimate_pages(store)
    fitted["summary"] = _fit_summary(str(fitted.get("summary") or ""), max_chars=1800)

    experience: list[dict[str, Any]] = []
    roles = [r for r in (fitted.get("experience") or []) if isinstance(r, dict)]
    for idx, role in enumerate(roles):
        clone = dict(role)
        cleaned = _clean_role_bullets(list(role.get("description") or []))
        quota = _moderate_role_quota(idx, len(roles), len(cleaned))
        selected = _select_bullets(cleaned, quota)
        clone["description"] = [_shorten_bullet_keep_core(b, max_chars=300) for b in selected]
        techs = [
            str(t).strip()
            for t in (role.get("technologies") or [])
            if str(t).strip() and len(str(t).strip()) <= 60 and len(str(t).split()) <= 6
        ][:16]
        clone["technologies"] = techs
        experience.append(clone)
    fitted["experience"] = experience

    projects: list[dict[str, Any]] = []
    for proj in fitted.get("projects") or []:
        if not isinstance(proj, dict):
            continue
        clone = dict(proj)
        cleaned = _clean_role_bullets(list(proj.get("description") or []))
        selected = _select_bullets(cleaned, min(6, max(3, len(cleaned))))
        clone["description"] = [_shorten_bullet_keep_core(b, max_chars=280) for b in selected]
        projects.append(clone)
    fitted["projects"] = projects
    fitted["education"] = _fit_education(fitted.get("education") or [])

    fitted["stats"] = {
        **(fitted.get("stats") or {}),
        "experience_count": len(experience),
        "experience_bullets": sum(len(r.get("description") or []) for r in experience),
        "projects_count": len(projects),
        "moderately_summarized": True,
    }
    fitted["fit"] = {
        "applied": True,
        "mode": "moderate_summarize",
        "pages_before": round(before, 2),
        "pages_after": round(estimate_pages(fitted), 2),
        "roles_kept": len(experience),
        "bullets_kept": fitted["stats"]["experience_bullets"],
        "projects_kept": len(projects),
    }
    logger.info("resume_moderate_summarize_applied", **fitted["fit"])
    return fitted


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
    # Retention floor: keep essence of a long career (~75%+ of bullets).
    source_bullets = sum(len(r.get("description") or []) for r in (original.get("experience") or []) if isinstance(r, dict))
    kept_bullets = sum(len(r.get("description") or []) for r in (fitted.get("experience") or []) if isinstance(r, dict))
    min_keep = max(source_bullets * 75 // 100, len(original.get("experience") or []) * 5)
    if source_bullets and kept_bullets < min_keep:
        fitted["experience"] = _fit_experience(
            original.get("experience") or [],
            target_pages=effective_target,
            min_total_bullets=min_keep,
        )
    fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=6, bullets=6)
    fitted["education"] = _fit_education(fitted.get("education") or [])
    fitted["certifications"] = list(fitted.get("certifications") or [])[:16]
    fitted["achievements"] = list(fitted.get("achievements") or [])[:14]
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

    # Almost never tighten — extreme brevity is worse than a longer client resume.
    if after > effective_target + 2.0:
        fitted["experience"] = _fit_experience(
            fitted.get("experience") or [],
            target_pages=effective_target,
            tight=True,
            min_total_bullets=max(source_bullets * 75 // 100, len(original.get("experience") or []) * 5),
        )
        fitted["skills_by_category"] = _fit_skills(fitted.get("skills_by_category") or {}, max_per_category=16)
        fitted["skills"] = _flatten_skills(fitted["skills_by_category"])
        fitted["projects"] = _fit_projects(fitted.get("projects") or [], keep=5, bullets=5)
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
    text = _clean_summary_text(text)
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
        if len(kept) >= 8:
            break
    out = " ".join(kept).strip()
    return out or text[:max_chars].rsplit(" ", 1)[0].strip()


def _clean_summary_text(text: str) -> str:
    """Strip contact/name mash that leaked into the professional summary."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    # "NAME | C: phone | E: email Summary starts here"
    text = re.sub(
        r"(?i)^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,5}\s*[|•]\s*"
        r"C\s*:\s*\S+\s*[|•]\s*E\s*:\s*\S+\s*",
        "",
        text,
    ).strip()
    text = _CONTACT_MASH_RE.sub("", text).strip()
    text = re.sub(
        r"(?i)^(?:phone|email|mobile|tel)\s*:\s*\S+(?:\s*[|•,]\s*)?",
        "",
        text,
    ).strip()
    return text


def _moderate_role_quota(role_index: int, role_count: int, available: int) -> int:
    """Soft density caps by recency — keep substance, trim only redundancy."""
    _ = role_count
    if available <= 0:
        return 0
    if role_index == 0:
        cap = 12
    elif role_index == 1:
        cap = 11
    elif role_index <= 3:
        cap = 10
    elif role_index <= 5:
        cap = 8
    else:
        cap = 6
    return min(available, cap)


def _clean_role_bullets(bullets: list[str]) -> list[str]:
    """Drop garbage/code dumps and collapse near-duplicates; keep richer wording."""
    cleaned: list[str] = []
    for raw in bullets:
        text = re.sub(r"\s+", " ", str(raw or "").strip())
        if len(text) < 25:
            continue
        if _is_garbage_bullet(text):
            continue
        cleaned.append(text)
    return _collapse_near_duplicate_bullets(cleaned)


def _is_garbage_bullet(text: str) -> bool:
    if _GARBAGE_BULLET_RE.search(text):
        return True
    if _TITLE_ONLY_BULLET_RE.match(text.strip()):
        return True
    # Dense code-ish tokens without normal prose spacing.
    if text.count("(") >= 2 and text.count(")") >= 2 and len(text) > 80:
        if re.search(r"[A-Za-z]\.[A-Za-z].*\(.*\)\.", text):
            return True
    return False


def _collapse_near_duplicate_bullets(bullets: list[str]) -> list[str]:
    kept: list[str] = []
    for bullet in bullets:
        dup_at = None
        for i, existing in enumerate(kept):
            if _bullets_near_duplicate(existing, bullet):
                dup_at = i
                break
        if dup_at is None:
            kept.append(bullet)
            continue
        # Keep the higher-signal / more specific wording.
        if _bullet_score(bullet) > _bullet_score(kept[dup_at]) or (
            len(bullet) > len(kept[dup_at]) + 20 and _bullet_score(bullet) >= _bullet_score(kept[dup_at]) - 0.5
        ):
            kept[dup_at] = bullet
    return kept


def _bullets_near_duplicate(a: str, b: str) -> bool:
    ta = _overlap_tokens(a)
    tb = _overlap_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    jaccard = inter / union
    if jaccard >= 0.58:
        return True
    if inter >= 5 and jaccard >= 0.42:
        return True
    ha = {m.group(0).lower() for m in _HIGH_SIGNAL_RE.finditer(a)}
    hb = {m.group(0).lower() for m in _HIGH_SIGNAL_RE.finditer(b)}
    if ha and hb and ha == hb and jaccard >= 0.18 and len(ha) >= 2:
        return True
    if len(ha & hb) >= 2 and jaccard >= 0.28:
        return True
    if _theme_collision(ta, tb):
        return True
    return False


def _theme_collision(ta: set[str], tb: set[str]) -> bool:
    """True when two bullets restate the same accessibility/integration theme."""
    a11y = {"wcag", "accessibility", "508", "aria", "section"}
    stacks = {"angular", "react", "vue", "html", "html5", "typescript"}
    if (ta & a11y) and (tb & a11y) and ((ta & stacks) & (tb & stacks)):
        return True
    mule = {"mulesoft", "anypoint", "raml", "dataweave", "weave"}
    if (ta & mule) and (tb & mule):
        # Only collapse near-identical MuleSoft rewrites, not distinct mule workstreams.
        sub_a = _mule_subtheme(ta)
        sub_b = _mule_subtheme(tb)
        if sub_a and sub_a == sub_b:
            return True
    return False


def _mule_subtheme(tokens: set[str]) -> str:
    if tokens & {"munit", "testing", "validation"}:
        return "test"
    if tokens & {"policy", "oauth", "manager", "rate"}:
        return "policy"
    if tokens & {"raml", "dataweave", "weave", "anypoint", "integration"}:
        return "integration"
    return ""


def _overlap_tokens(text: str) -> set[str]:
    stop = {
        "with", "from", "using", "that", "this", "have", "been", "were", "their",
        "team", "project", "system", "application", "applications", "services",
        "based", "across", "including", "through", "while", "into", "over",
        "and", "the", "for", "supporting", "utilizing", "leveraging", "platforms",
        "standards", "compliant", "modules", "frontend", "backend", "enterprise",
    }
    out: set[str] = set()
    for raw in re.findall(r"[a-z0-9][a-z0-9+.#-]{2,}", (text or "").lower()):
        token = raw.strip(".-+")
        # Normalize "react.js" / "node.js" style tokens to the product stem.
        if "." in token:
            token = token.split(".", 1)[0]
        if len(token) < 3 or token in stop:
            continue
        out.add(token)
    return out


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
    body_pages = max(2.5, target_pages - 1.0)
    total_budget = int(body_pages * 28)
    if tight:
        total_budget = max(64, int(total_budget * 0.92))
    # Floor scales with role count so multi-employer careers stay informative.
    total_budget = max(n * 7, min(total_budget, 220))
    if min_total_bullets:
        total_budget = max(total_budget, int(min_total_bullets))

    weights = [max(1.0, float(n - i)) for i in range(n)]
    weight_sum = sum(weights) or 1.0
    min_each = 6 if not tight else 5
    quotas = [max(min_each, int(round(total_budget * (w / weight_sum)))) for w in weights]
    max_each = 24 if not tight else 16
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
    cleaned = [b for b in cleaned if len(b) >= 25 and not _is_garbage_bullet(b)]
    cleaned = _collapse_near_duplicate_bullets(cleaned)
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
            # Skip if near-dup of something already chosen.
            if any(_bullets_near_duplicate(cleaned[idx], cleaned[j]) for j in chosen_idxs):
                continue
            chosen_idxs.append(idx)
    for idx in ranked_idxs:
        if len(chosen_idxs) >= quota:
            break
        if idx in chosen_idxs:
            continue
        if any(_bullets_near_duplicate(cleaned[idx], cleaned[j]) for j in chosen_idxs):
            continue
        chosen_idxs.append(idx)
    # If still short after near-dup skips, fill remaining slots.
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
