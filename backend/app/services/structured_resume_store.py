"""
Canonical structured resume store.

Parse once into section-wise JSON of any length. Generation reads from this store
and applies client format layout — the LLM must never be the only copy of body content.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import logger


def build_structured_resume(candidate_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize candidate_data into a durable section store with no content caps."""
    skills_by_category = candidate_data.get("skills_by_category")
    if not isinstance(skills_by_category, dict) or not skills_by_category:
        skills_by_category = _skills_list_to_categories(candidate_data.get("skills"))

    experience = [_normalize_experience(item) for item in _as_list(candidate_data.get("experience"))]
    experience = [item for item in experience if item.get("company") or item.get("title")]

    education = [_normalize_education(item) for item in _as_list(candidate_data.get("education"))]
    education = [item for item in education if item.get("degree") or item.get("institution")]

    projects = [_normalize_project(item) for item in _as_list(candidate_data.get("projects"))]
    projects = [item for item in projects if item.get("name")]

    store = {
        "version": 1,
        "header": {
            "name": str(candidate_data.get("name") or "").strip(),
            "email": str(candidate_data.get("email") or "").strip(),
            "phone": str(candidate_data.get("phone") or "").strip(),
            "location": str(candidate_data.get("location") or "").strip(),
            "linkedin": str(candidate_data.get("linkedin") or "").strip(),
            "portfolio": str(candidate_data.get("portfolio") or "").strip(),
            "role": str(
                candidate_data.get("job_role")
                or candidate_data.get("job_title")
                or candidate_data.get("job_applied")
                or ""
            ).strip(),
        },
        "summary": str(candidate_data.get("summary") or "").strip(),
        "skills": _as_str_list(candidate_data.get("skills")),
        "skills_by_category": {
            str(k).strip(): _as_str_list(v)
            for k, v in (skills_by_category or {}).items()
            if str(k).strip() and _as_str_list(v)
        },
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": _as_str_list(candidate_data.get("certifications")),
        "achievements": _as_str_list(candidate_data.get("achievements")),
        "languages": _as_str_list(candidate_data.get("languages")),
        "raw_resume_text": str(candidate_data.get("raw_resume_text") or ""),
        "stats": {
            "experience_count": len(experience),
            "experience_bullets": sum(len(e.get("description") or []) for e in experience),
            "education_count": len(education),
            "skills_count": sum(len(v) for v in (skills_by_category or {}).values())
            or len(_as_str_list(candidate_data.get("skills"))),
            "projects_count": len(projects),
            "raw_chars": len(str(candidate_data.get("raw_resume_text") or "")),
        },
    }
    logger.info(
        "structured_resume_store_built",
        experience_count=store["stats"]["experience_count"],
        experience_bullets=store["stats"]["experience_bullets"],
        education_count=store["stats"]["education_count"],
        skills_count=store["stats"]["skills_count"],
        raw_chars=store["stats"]["raw_chars"],
    )
    return store


def apply_store_to_candidate_data(candidate_data: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    """Merge store fields back so builders always see full section content."""
    merged = dict(candidate_data or {})
    header = store.get("header") or {}
    for key in ("name", "email", "phone", "location", "linkedin", "portfolio"):
        if header.get(key):
            merged[key] = header[key]
    if header.get("role"):
        merged["job_role"] = header["role"]
    merged["summary"] = store.get("summary") or merged.get("summary") or ""
    merged["skills"] = store.get("skills") or merged.get("skills") or []
    merged["skills_by_category"] = store.get("skills_by_category") or {}
    merged["experience"] = store.get("experience") or []
    merged["education"] = store.get("education") or []
    merged["projects"] = store.get("projects") or []
    merged["certifications"] = store.get("certifications") or []
    merged["achievements"] = store.get("achievements") or []
    merged["languages"] = store.get("languages") or []
    merged["structured_resume"] = store
    merged["structured_resume_json"] = store
    return merged


def is_large_resume(store: dict[str, Any]) -> bool:
    """True when a single LLM full-document rewrite is likely to truncate."""
    stats = store.get("stats") or {}
    return (
        int(stats.get("experience_count") or 0) >= 4
        or int(stats.get("experience_bullets") or 0) >= 25
        or int(stats.get("raw_chars") or 0) >= 12000
    )


def document_from_store(
    store: dict[str, Any],
    format_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build client-formatted document JSON directly from the section store."""
    metadata = format_metadata or {}
    section_order = metadata.get("sections") or metadata.get("section_order") or [
        "summary",
        "skills",
        "experience",
        "projects",
        "education",
        "certifications",
        "achievements",
        "languages",
    ]
    labels = metadata.get("section_labels") if isinstance(metadata.get("section_labels"), dict) else {}

    default_titles = {
        "summary": "PROFESSIONAL SUMMARY:",
        "skills": "TECHNICAL SKILLS:",
        "experience": "PROFESSIONAL EXPERIENCE:",
        "projects": "PROJECTS:",
        "education": "EDUCATION:",
        "certifications": "CERTIFICATIONS:",
        "achievements": "ACHIEVEMENTS:",
        "languages": "LANGUAGES:",
    }

    header = store.get("header") or {}
    contact = [
        v
        for v in (
            header.get("email"),
            header.get("phone"),
            header.get("location"),
            header.get("linkedin"),
            header.get("portfolio"),
        )
        if v
    ]

    sections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_name in section_order:
        canonical = _canonical(raw_name)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        title = str(labels.get(canonical) or default_titles.get(canonical) or f"{canonical.upper()}:")
        if not title.endswith(":"):
            title = f"{title}:"

        section = _section_payload(store, canonical, title.upper() if len(title) < 40 else title)
        if section:
            sections.append(section)

    for canonical in ("summary", "skills", "experience", "education", "projects", "certifications"):
        if canonical in seen:
            continue
        section = _section_payload(store, canonical, default_titles[canonical])
        if section:
            sections.append(section)

    return {
        "header": {
            "name": header.get("name") or "",
            "role": header.get("role") or "",
            "contact": contact,
        },
        "sections": sections,
    }


def _section_payload(store: dict[str, Any], canonical: str, title: str) -> dict[str, Any] | None:
    if canonical == "summary":
        summary = str(store.get("summary") or "").strip()
        if not summary:
            return None
        return {"type": "text", "title": title, "content": summary}
    if canonical == "skills":
        grouped = store.get("skills_by_category") or {}
        if isinstance(grouped, dict) and grouped:
            return {"type": "skills", "title": title, "content": grouped}
        skills = store.get("skills") or []
        if skills:
            return {"type": "skills", "title": title, "content": skills}
        return None
    if canonical in {"experience", "education", "projects"}:
        items = store.get(canonical) or []
        if not items:
            return None
        return {"type": canonical, "title": title, "content": items}
    if canonical in {"certifications", "achievements", "languages"}:
        values = store.get(canonical) or []
        if not values:
            return None
        return {"type": "bullets", "title": title, "content": values}
    return None


def _canonical(name: Any) -> str:
    text = str(name or "").lower()
    if "summary" in text or "profile" in text or "objective" in text:
        return "summary"
    if "skill" in text or "technolog" in text or "competenc" in text:
        return "skills"
    if "experience" in text or "employment" in text or "work history" in text:
        return "experience"
    if "education" in text or "academic" in text or "qualif" in text:
        return "education"
    if "project" in text:
        return "projects"
    if "certif" in text or "license" in text:
        return "certifications"
    if "achieve" in text or "award" in text:
        return "achievements"
    if "language" in text and "framework" not in text:
        return "languages"
    return ""


def _normalize_experience(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "title": "",
            "company": str(item or "").strip(),
            "location": "",
            "duration": "",
            "description": [],
            "technologies": [],
        }
    desc = item.get("description") or item.get("details") or item.get("responsibilities") or item.get("bullets") or []
    techs = item.get("technologies") or item.get("environment") or item.get("tech_stack") or []
    if isinstance(techs, str):
        techs = [t.strip() for t in techs.replace(";", ",").split(",") if t.strip()]
    return {
        "title": str(item.get("title") or item.get("role") or item.get("position") or "").strip(),
        "company": str(item.get("company") or item.get("organization") or item.get("employer") or "").strip(),
        "location": str(item.get("location") or "").strip(),
        "duration": str(item.get("duration") or item.get("dates") or item.get("period") or "").strip(),
        "description": [str(b).strip() for b in _as_list(desc) if str(b).strip()],
        "technologies": [str(t).strip() for t in _as_list(techs) if str(t).strip()],
    }


def _normalize_education(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "degree": str(item or "").strip(),
            "institution": "",
            "location": "",
            "year": "",
            "cgpa": "",
            "details": [],
        }
    details = item.get("details") or []
    return {
        "degree": str(item.get("degree") or item.get("qualification") or "").strip(),
        "institution": str(
            item.get("institution") or item.get("school") or item.get("university") or ""
        ).strip(),
        "location": str(item.get("location") or "").strip(),
        "year": str(item.get("year") or item.get("graduation_year") or item.get("dates") or "").strip(),
        "cgpa": str(item.get("cgpa") or item.get("gpa") or "").strip(),
        "details": [str(d).strip() for d in _as_list(details) if str(d).strip()],
    }


def _normalize_project(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"name": str(item or "").strip(), "description": [], "technologies": [], "link": "", "duration": ""}
    desc = item.get("description") or item.get("details") or []
    techs = item.get("technologies") or []
    return {
        "name": str(item.get("name") or item.get("title") or "").strip(),
        "description": [str(b).strip() for b in _as_list(desc) if str(b).strip()],
        "technologies": [str(t).strip() for t in _as_list(techs) if str(t).strip()],
        "link": str(item.get("link") or item.get("url") or "").strip(),
        "duration": str(item.get("duration") or item.get("dates") or "").strip(),
    }


def _skills_list_to_categories(skills: Any) -> dict[str, list[str]]:
    values = _as_str_list(skills)
    if not values:
        return {}
    return {"Technical Skills": values}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_str_list(value: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in _as_list(value):
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
