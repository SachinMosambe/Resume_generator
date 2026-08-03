from typing import Any


SECTION_LABELS = {
    "header": "Profile",
    "summary": "Professional Summary",
    "experience": "Professional Experience",
    "education": "Education",
    "skills": "Technical Skills",
    "projects": "Projects",
    "certifications": "Certifications",
    "achievements": "Achievements",
    "languages": "Languages",
}

DEFAULT_SECTION_ORDER = [
    "header",
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "achievements",
    "languages",
]


def build_resume_document(candidate_data: dict[str, Any], format_metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = format_metadata or {}
    sections = metadata.get("sections") or DEFAULT_SECTION_ORDER
    ordered_sections = _complete_section_order(
        _ordered_sections(sections, metadata.get("section_order")),
        candidate_data,
    )
    labels = metadata.get("section_labels") if isinstance(metadata.get("section_labels"), dict) else {}
    if not labels and isinstance(metadata.get("field_mapping"), dict):
        labels = metadata.get("field_mapping") or {}

    return {
        "header": _build_header(candidate_data),
        "sections": [
            section
            for section in (
                _build_section(section_name, candidate_data, labels)
                for section_name in ordered_sections
                if _canonical_section(section_name) != "header"
            )
            if section and section.get("content")
        ],
    }


def normalize_resume_document(document: dict[str, Any], candidate_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize generated resume JSON into renderer-safe structure."""
    if not isinstance(document, dict):
        return build_resume_document(candidate_data, None)

    raw_header = document.get("header") if isinstance(document.get("header"), dict) else {}
    header = _build_header(candidate_data)
    if not header.get("role") and raw_header.get("role"):
        header["role"] = str(raw_header["role"]).strip()
    # Client policy: never surface personal contact details on generated resumes.
    header["contact"] = []

    sections: list[dict[str, Any]] = []
    for section in _list(document.get("sections")):
        if not isinstance(section, dict):
            continue
        section_type = str(section.get("type") or "text").strip().lower()
        if section_type not in {"text", "skills", "experience", "education", "projects", "bullets"}:
            section_type = "text"
        title = str(section.get("title") or "Section").strip()
        from app.models.format_schema import to_heading_title_case

        title = to_heading_title_case(title, keep_colon=False) or title
        content = section.get("content")
        if section_type == "skills":
            content = _clean_skills_content(content)
            if not content:
                continue
        elif section_type in {"experience", "education", "projects", "bullets"}:
            content = [item for item in _list(content) if str(item).strip()]
            if not content:
                continue
        else:
            content = str(content or "").strip()
            if not content:
                continue
        sections.append({"type": section_type, "title": title, "content": content})

    sections = _ensure_candidate_sections(sections, candidate_data)
    if not sections:
        return build_resume_document(candidate_data, None)
    return {"header": header, "sections": sections}


def _ordered_sections(sections: list[Any], section_order: list[Any] | None) -> list[str]:
    normalized = [str(section) for section in sections if str(section).strip()]
    if not section_order:
        return normalized

    ordered: list[str] = []
    for index in section_order:
        try:
            ordered.append(normalized[int(index)])
        except (ValueError, IndexError, TypeError):
            continue

    for section in normalized:
        if section not in ordered:
            ordered.append(section)
    return ordered


def _complete_section_order(ordered: list[str], candidate_data: dict[str, Any]) -> list[str]:
    """Keep client order, then append available candidate sections the format missed."""
    completed = [section for section in ordered if str(section).strip()]
    seen = {_canonical_section(section) for section in completed}

    for section_name in DEFAULT_SECTION_ORDER:
        canonical = _canonical_section(section_name)
        if canonical in seen:
            continue
        if canonical == "header" or _build_section(canonical, candidate_data):
            completed.append(canonical)
            seen.add(canonical)

    return completed


def _ensure_candidate_sections(
    sections: list[dict[str, Any]],
    candidate_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Backfill important sections if the LLM draft skipped candidate data."""
    repaired = list(sections)
    present = {_section_canonical(section) for section in repaired}

    for section_name in DEFAULT_SECTION_ORDER:
        canonical = _canonical_section(section_name)
        if canonical == "header" or canonical in present:
            continue
        fallback_section = _build_section(canonical, candidate_data)
        if fallback_section:
            repaired.append(fallback_section)
            present.add(canonical)

    return repaired


def _section_canonical(section: dict[str, Any]) -> str:
    title = str(section.get("title") or "").strip()
    section_type = str(section.get("type") or "").strip()
    if title and title.lower() != "section":
        return _canonical_section(title)
    return _canonical_section(section_type)


def _build_header(candidate_data: dict[str, Any]) -> dict[str, Any]:
    """Build header with candidate name only (no personal contact details)."""
    return {
        "name": candidate_data.get("name") or "Candidate",
        "role": candidate_data.get("job_role") or candidate_data.get("job_applied") or "",
        "contact": [],
    }


def _build_section(
    section_name: str,
    candidate_data: dict[str, Any],
    labels: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a resume section with detailed content."""
    from app.models.format_schema import to_heading_title_case

    canonical = _canonical_section(section_name)
    label = None
    if isinstance(labels, dict):
        label = labels.get(canonical) or labels.get(section_name)
    title = to_heading_title_case(label or SECTION_LABELS.get(canonical) or _titleize(section_name), keep_colon=False)

    if canonical == "summary":
        content = _summary(candidate_data)
        if not content:
            return None
        return {"type": "text", "title": title, "content": content}
    
    if canonical == "experience":
        experience = candidate_data.get("experience", [])
        # Fallback to extracted_data if available
        if not experience:
            extracted = candidate_data.get("extracted_data") or {}
            experience = extracted.get("experience") or extracted.get("resume_experience") or []
        if not experience:
            return None
        return {"type": "experience", "title": title, "content": experience}
    
    if canonical == "education":
        education = candidate_data.get("education", [])
        # Fallback to extracted_data if available
        if not education:
            extracted = candidate_data.get("extracted_data") or {}
            education = extracted.get("education") or extracted.get("resume_education") or []
        if not education:
            return None
        return {"type": "education", "title": title, "content": education}
    
    if canonical == "skills":
        skills = _skills(candidate_data)
        if not skills:
            return None
        return {"type": "skills", "title": title, "content": skills}
    
    if canonical == "projects":
        projects = candidate_data.get("projects", [])
        if not projects:
            return None
        return {"type": "projects", "title": title, "content": projects}
    
    if canonical == "certifications":
        certs = candidate_data.get("certifications", [])
        if not certs:
            return None
        return {"type": "bullets", "title": title, "content": certs}
    
    if canonical == "achievements":
        achievements = candidate_data.get("achievements", [])
        if not achievements:
            return None
        return {"type": "bullets", "title": title, "content": achievements}
    
    if canonical == "languages":
        languages = candidate_data.get("languages", [])
        if not languages:
            return None
        return {"type": "bullets", "title": title, "content": languages}

    # Default: try to get content from candidate data
    content = candidate_data.get(canonical, "")
    if not content:
        return None
    return {"type": "text", "title": title, "content": content}


def _canonical_section(section_name: str) -> str:
    normalized = section_name.lower().replace("_", " ").strip()
    if "experience" in normalized or "employment" in normalized or "work" in normalized:
        return "experience"
    if "education" in normalized or "academic" in normalized or "qualification" in normalized or "degree" in normalized:
        return "education"
    if "skill" in normalized or "competenc" in normalized or "expertise" in normalized:
        return "skills"
    if "project" in normalized:
        return "projects"
    if "cert" in normalized or "license" in normalized:
        return "certifications"
    if "summary" in normalized or "objective" in normalized or "profile" in normalized:
        return "summary"
    if "header" in normalized or "contact" in normalized or "info" in normalized:
        return "header"
    if "achievement" in normalized or "award" in normalized or "honor" in normalized:
        return "achievements"
    if "language" in normalized:
        return "languages"
    return normalized or "summary"


def _summary(candidate_data: dict[str, Any]) -> str:
    extracted = candidate_data.get("extracted_data") or {}
    # Prefer actual resume summary over evaluation-generated summary
    return (
        extracted.get("summary")
        or extracted.get("professional_summary")
        or candidate_data.get("summary")
        or candidate_data.get("main_summary")
        or candidate_data.get("linkedin_summary")
        or ""
    )


def _skills(candidate_data: dict[str, Any]) -> list[str] | dict[str, list[str]]:
    """Extract and categorize skills for professional resume display."""
    extracted = candidate_data.get("extracted_data") or {}
    # Prefer stored category labels from the section store / parser.
    grouped = candidate_data.get("skills_by_category")
    if isinstance(grouped, dict) and grouped:
        cleaned = {
            str(k).strip(): _dedupe([str(s).strip() for s in _list(v) if str(s).strip()])
            for k, v in grouped.items()
            if str(k).strip()
        }
        cleaned = {k: v for k, v in cleaned.items() if v}
        if cleaned:
            return cleaned
    store = extracted.get("structured_resume") if isinstance(extracted, dict) else None
    if isinstance(store, dict) and isinstance(store.get("skills_by_category"), dict):
        cleaned = {
            str(k).strip(): _dedupe([str(s).strip() for s in _list(v) if str(s).strip()])
            for k, v in store["skills_by_category"].items()
            if str(k).strip()
        }
        cleaned = {k: v for k, v in cleaned.items() if v}
        if cleaned:
            return cleaned

    skills = _list(candidate_data.get("skills"))
    if not skills:
        skills = _list(candidate_data.get("skills_matched"))
    if not skills:
        skills = _list(extracted.get("skills"))
    if not skills:
        skills = _list(candidate_data.get("skills_not_matched"))

    skills = _dedupe([str(skill).strip() for skill in skills if str(skill).strip()])

    categorized = _categorize_skills(skills)
    if categorized:
        return categorized

    return skills


def _clean_skills_content(content: Any) -> list[str] | dict[str, list[str]]:
    if isinstance(content, dict):
        cleaned: dict[str, list[str]] = {}
        for category, skill_values in content.items():
            category_name = str(category).strip()
            skills = _dedupe(
                [str(skill).strip() for skill in _list(skill_values) if str(skill).strip()]
            )
            if category_name and skills:
                cleaned[category_name] = skills
        return cleaned

    if isinstance(content, str):
        content = content.replace("\n", ",").replace(";", ",")
    return _dedupe([str(item).strip() for item in _list(content) if str(item).strip()])


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _categorize_skills(skills: list[str]) -> dict[str, list[str]] | None:
    """Categorize skills into logical groups for professional display."""
    if not skills:
        return None
    
    # Define category keywords
    categories = {
        "Languages": ["java", "python", "javascript", "js", "typescript", "ts", "c++", "c#", "go", "rust", "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "perl", "shell", "bash", "sql", "html", "css"],
        "Frameworks": ["spring", "react", "angular", "vue", "django", "flask", "express", "fastapi", "laravel", "rails", "bootstrap", "tailwind", "next.js", "nuxt", "hibernate", "jpa", "struts", "maven", "gradle"],
        "Databases": ["mysql", "postgresql", "postgres", "mongodb", "oracle", "sqlite", "redis", "cassandra", "dynamodb", "firebase", "elasticsearch", "neo4j"],
        "Tools & Platforms": ["git", "github", "gitlab", "docker", "kubernetes", "k8s", "aws", "azure", "gcp", "jenkins", "jira", "confluence", "postman", "swagger", "linux", "windows"],
        "Cloud & DevOps": ["aws", "azure", "gcp", "docker", "kubernetes", "k8s", "terraform", "ansible", "jenkins", "ci/cd", "github actions", "gitlab ci"],
        "Libraries": ["pandas", "numpy", "scipy", "scikit-learn", "tensorflow", "pytorch", "keras", "matplotlib", "seaborn", "plotly", "lodash", "axios"],
    }
    
    categorized: dict[str, list[str]] = {cat: [] for cat in categories}
    uncategorized: list[str] = []
    
    for skill in skills:
        skill_lower = skill.lower()
        found = False
        for category, keywords in categories.items():
            if any(keyword in skill_lower for keyword in keywords):
                categorized[category].append(skill)
                found = True
                break
        if not found:
            uncategorized.append(skill)
    
    # Remove empty categories
    categorized = {k: v for k, v in categorized.items() if v}
    
    # If no meaningful categorization, return flat list
    if len(categorized) < 2 and len(uncategorized) > len(skills) // 2:
        return None
    
    # Add uncategorized as "Other" if any remain
    if uncategorized:
        categorized["Other"] = uncategorized
    
    return categorized if categorized else None


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        for key in ("items", "values", "skills", "experience", "education", "projects", "certifications"):
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
        return [f"{key}: {item}" for key, item in value.items() if item]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in str(value).replace("_", " ").split())
