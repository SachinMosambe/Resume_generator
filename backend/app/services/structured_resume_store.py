"""
Canonical structured resume store.

Parse once into section-wise JSON of any length. Generation reads from this store
and applies client format layout — the LLM must never be the only copy of body content.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.logging import logger


def build_structured_resume(candidate_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize candidate_data into a durable section store with no content caps."""
    from app.services.pdf_parser import repair_collapsed_spaces

    skills_by_category = candidate_data.get("skills_by_category")
    if not isinstance(skills_by_category, dict) or not skills_by_category:
        skills_by_category = _skills_list_to_categories(candidate_data.get("skills"))

    experience = [_normalize_experience(item) for item in _as_list(candidate_data.get("experience"))]
    experience = [item for item in experience if item.get("company") or item.get("title")]
    for role in experience:
        role["description"] = expand_to_bullets(
            [repair_collapsed_spaces(str(b)) for b in (role.get("description") or []) if str(b).strip()]
        )

    education = normalize_education_entries(
        [_normalize_education(item) for item in _as_list(candidate_data.get("education"))]
    )

    projects = [_normalize_project(item) for item in _as_list(candidate_data.get("projects"))]
    projects = [item for item in projects if item.get("name")]
    for project in projects:
        project["description"] = expand_to_bullets(
            [repair_collapsed_spaces(str(b)) for b in (project.get("description") or []) if str(b).strip()]
        )

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
        "summary": repair_collapsed_spaces(str(candidate_data.get("summary") or "").strip()),
        "skills": _as_str_list(candidate_data.get("skills")),
        "skills_by_category": {
            str(k).strip(): _as_str_list(v)
            for k, v in (skills_by_category or {}).items()
            if str(k).strip() and _as_str_list(v)
        },
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": [
            repair_collapsed_spaces(c) for c in _as_str_list(candidate_data.get("certifications"))
        ],
        "achievements": [
            repair_collapsed_spaces(a) for a in _as_str_list(candidate_data.get("achievements"))
        ],
        "languages": _as_str_list(candidate_data.get("languages")),
        "raw_resume_text": repair_collapsed_spaces(str(candidate_data.get("raw_resume_text") or "")),
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
    merged["education"] = normalize_education_entries(store.get("education") or [])
    merged["projects"] = store.get("projects") or []
    merged["certifications"] = store.get("certifications") or []
    merged["achievements"] = store.get("achievements") or []
    merged["languages"] = store.get("languages") or []
    merged["structured_resume"] = store
    merged["structured_resume_json"] = store
    return merged


def normalize_education_entries(entries: Any) -> list[dict[str, Any]]:
    """
    Clean education into clear Degree / Institution / Year rows.
    Dedupes Dice short forms like 'Bachelors @ School' against full degree lines.
    """
    import re

    noise = re.compile(
        r"(?i)\b(preferred|desired work|willing to relocate|work authorization|visa sponsorship|"
        r"profile source|profile downloaded|employment type|authorized to work)\b"
    )
    at_re = re.compile(
        r"(?i)^\s*((?:bachelor|master|masters|bachelors|phd|mba|b\.?tech|m\.?tech|ms|bs|ba|ma|"
        r"bachelor of[\w\s]+|master of[\w\s]+)[^@]{0,80}?)\s*@\s*(.+?)\s*$"
    )

    cleaned: list[dict[str, Any]] = []
    for item in entries or []:
        if not isinstance(item, dict):
            text = str(item or "").strip()
            if not text or noise.search(text):
                continue
            item = {"degree": text, "institution": "", "year": "", "location": "", "details": []}

        degree = str(item.get("degree") or item.get("qualification") or "").strip()
        institution = str(
            item.get("institution") or item.get("school") or item.get("university") or ""
        ).strip()
        year = str(item.get("year") or item.get("graduation_year") or item.get("dates") or "").strip()
        location = str(item.get("location") or "").strip()
        details = [str(d).strip() for d in (item.get("details") or []) if str(d).strip() and not noise.search(str(d))]

        if noise.search(degree) or noise.search(institution):
            continue

        # Split "Bachelors @ Delhi Technological University"
        at_match = at_re.match(degree) if degree and not institution else None
        if at_match:
            degree = at_match.group(1).strip(" :-")
            institution = at_match.group(2).strip(" :-")

        # Repair PDF mashups before peeling school names.
        degree = re.sub(
            r"(?i)\b(University|College|Institute|School|Academy)of\b",
            r"\1 of",
            degree,
        )
        institution = re.sub(
            r"(?i)\b(University|College|Institute|School|Academy)of\b",
            r"\1 of",
            institution,
        )

        # If degree still contains university phrase, peel it out.
        if degree and not institution:
            uni = re.search(
                r"((?:[A-Z][A-Za-z.&'\-]+\s+){0,8}"
                r"(?:University|College|Institute|School|Academy)"
                r"(?:\s*\([^)]{1,48}\))?"
                r"(?:\s+of\s+[A-Za-z][A-Za-z.&'\-\s]+(?:\([^)]{1,48}\))?)*"
                r"(?:\s+[A-Za-z][A-Za-z.&'\-]+){0,4})",
                degree,
            )
            if uni:
                institution = uni.group(1).strip()
                degree = degree.replace(uni.group(1), "").strip(" ,|-")

        degree = re.sub(r"\s+", " ", degree).strip(" ,|-")
        institution = re.sub(r"\s+", " ", institution).strip(" ,|-")
        # Normalize short labels
        degree = re.sub(r"(?i)^bachelors?\b", "Bachelor", degree)
        degree = re.sub(r"(?i)^masters?\b", "Master", degree)
        if re.fullmatch(r"(?i)bachelor", degree):
            degree = "Bachelor's Degree"
        if re.fullmatch(r"(?i)master", degree):
            degree = "Master's Degree"

        # Reject stub institution labels extracted from templates/columns.
        stub_institutions = {
            "institute", "college", "university", "school", "academy", "iit",
            "department", "faculty", "campus", "institution",
        }
        if institution.casefold() in stub_institutions:
            institution = ""

        if not degree and not institution:
            continue

        if len(degree) <= 3 and not institution:
            continue

        cleaned.append(
            {
                "degree": degree,
                "institution": institution,
                "location": location,
                "year": year,
                "cgpa": str(item.get("cgpa") or "").strip(),
                "details": details[:2],
            }
        )

    # Dedupe: prefer longer/more specific degree for same institution+level.
    by_inst: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []

    def _inst_key(name: str) -> str:
        text = (name or "").lower()
        # Keep campus tokens in the display merge score; only strip for keying after
        # normalizing "university of illinois at springfield" → same school family.
        text = re.sub(r"\bat\s+[a-z].*$", "", text)  # drop "at Springfield" for key only
        text = re.sub(r",\s*[a-z].*$", "", text)  # drop ", Delhi, India"
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"formerly.*$", "", text)
        return re.sub(r"[^a-z0-9]+", "", text)

    for row in cleaned:
        inst_key = _inst_key(row.get("institution") or "")
        deg_key = re.sub(r"[^a-z0-9]+", "", (row.get("degree") or "").lower())
        if not inst_key:
            extras.append(row)
            continue
        if "master" in deg_key or "mba" in deg_key or deg_key.startswith("ms") or deg_key.startswith("msc"):
            level = "master"
        elif "bachelor" in deg_key or "btech" in deg_key or deg_key.startswith("bs") or deg_key.startswith("bsc"):
            level = "bachelor"
        else:
            level = deg_key[:16] or "other"
        key = f"{inst_key}|{level}"
        prev = by_inst.get(key)
        if not prev:
            by_inst[key] = row
            continue
        # Keep the richer degree string / year / more complete institution.
        prev_score = (
            len(prev.get("degree") or "")
            + (8 if prev.get("year") else 0)
            + len(prev.get("institution") or "")
            + (10 if "of " in (prev.get("degree") or "").lower() else 0)
        )
        new_score = (
            len(row.get("degree") or "")
            + (8 if row.get("year") else 0)
            + len(row.get("institution") or "")
            + (10 if "of " in (row.get("degree") or "").lower() else 0)
        )
        if new_score > prev_score:
            # Preserve year if the richer row lacks it.
            if not row.get("year") and prev.get("year"):
                row["year"] = prev["year"]
            by_inst[key] = row
        elif not prev.get("year") and row.get("year"):
            prev["year"] = row["year"]

    # Stable order: masters first then bachelors then others, by year desc if present.
    merged = list(by_inst.values()) + extras

    def sort_key(row: dict[str, Any]) -> tuple:
        deg = (row.get("degree") or "").lower()
        level = 0 if "master" in deg or "mba" in deg else (1 if "bachelor" in deg else 2)
        year = str(row.get("year") or "")
        m = re.search(r"(19|20)\d{2}", year)
        year_num = int(m.group(0)) if m else 0
        return (level, -year_num)

    merged.sort(key=sort_key)
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
        title = _safe_section_title(labels.get(canonical), default_titles.get(canonical) or f"{canonical.upper()}:")

        section = _section_payload(store, canonical, title)
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


def _safe_section_title(label: Any, default: str) -> str:
    """Use template labels only when they look like short canonical headings."""
    title = str(label or "").strip()
    fallback = default if default.endswith(":") else f"{default}:"
    if not title:
        return fallback
    clean = title[:-1].strip() if title.endswith(":") else title
    if len(clean) > 36 or len(clean.split()) > 4:
        return fallback
    low = clean.lower()
    if "," in low or "|" in low or "@" in low:
        return fallback
    # Must contain a recognizable section keyword.
    keywords = (
        "summary", "objective", "profile", "skill", "experience", "employment",
        "education", "project", "certif", "achievement", "award", "language",
    )
    if not any(k in low for k in keywords):
        return fallback
    titled = clean.upper()
    return titled if titled.endswith(":") else f"{titled}:"


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
    title = str(item.get("title") or item.get("role") or item.get("position") or "").strip()
    company = str(item.get("company") or item.get("organization") or item.get("employer") or "").strip()
    location = str(item.get("location") or "").strip()
    if re.match(r"(?i)^environment\s*:", title):
        title = ""
    if re.match(r"(?i)^environment\s*:", location):
        location = ""
    if re.search(r"(?i)\bgap\s*period\b", f"{company} {title}"):
        return {
            "title": "",
            "company": "",
            "location": "",
            "duration": "",
            "description": [],
            "technologies": [],
        }
    clean_techs = []
    for t in _as_list(techs):
        name = str(t).strip()
        if not name or len(name) > 60 or len(name.split()) > 6:
            continue
        if name.lower().startswith("environment"):
            continue
        clean_techs.append(name)
    return {
        "title": title,
        "company": company,
        "location": location,
        "duration": str(item.get("duration") or item.get("dates") or item.get("period") or "").strip(),
        "description": expand_to_bullets(_as_list(desc)),
        "technologies": clean_techs[:12],
    }


_ACTION_VERB_START = re.compile(
    r"^(?:"
    r"Architected|Developed|Designed|Implemented|Built|Led|Created|Improved|Optimized|"
    r"Deployed|Integrated|Managed|Delivered|Engineered|Collaborated|Mentored|Configured|"
    r"Migrated|Reduced|Increased|Automated|Established|Owned|Supported|Analyzed|Processed|"
    r"Enabled|Wrote|Maintained|Refactored|Troubleshot|Coordinated|Partnered|Worked|"
    r"Responsible|Spearheaded|Drove|Executed|Enhanced|Launched|Conducted|Performed|"
    r"Utilized|Leveraged|Applied|Contributed|Assisted|Presented|Facilitated"
    r")\b",
    re.I,
)


def expand_to_bullets(values: list[Any], *, max_bullets: int = 12) -> list[str]:
    """
    Turn paragraph streams into discrete professional bullets.

    Splits on bullet glyphs and on sentence boundaries that start with action verbs.
    """
    out: list[str] = []
    for raw in values or []:
        text = re.sub(r"\s+", " ", str(raw or "").strip())
        if not text:
            continue
        # Glyph-separated chunks first.
        chunks = [
            c.strip(" -•\t")
            for c in re.split(r"(?:(?<=\s)|^)[•\u2022\u25CF\u25E6▪●◦\*]\s+", text)
            if c and c.strip(" -•\t")
        ]
        if len(chunks) <= 1:
            chunks = [text]

        for chunk in chunks:
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if not chunk:
                continue
            sentence_count = len(re.findall(r"[.!?](?:\s+|$)", chunk))
            if len(chunk) >= 180 and sentence_count >= 2:
                sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'])", chunk)
                buf: list[str] = []
                for sentence in sentences:
                    s = sentence.strip()
                    if not s:
                        continue
                    if buf and _ACTION_VERB_START.match(s):
                        joined = " ".join(buf).strip()
                        if joined:
                            out.append(joined)
                        buf = [s]
                    else:
                        buf.append(s)
                if buf:
                    out.append(" ".join(buf).strip())
            else:
                out.append(chunk)

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in out:
        key = re.sub(r"[^a-z0-9]+", "", item.lower())
        if len(key) < 12 or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max_bullets:
            break
    return unique


def store_needs_llm_polish(store: dict[str, Any]) -> bool:
    """True only when deterministic formatting is not enough (mashed/broken text)."""
    summary = str(store.get("summary") or "")
    if _text_looks_mashed(summary):
        return True
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        bullets = role.get("description") or []
        if not bullets:
            continue
        # Still one mega-paragraph after expansion → needs LLM rewrite help.
        if len(bullets) <= 2 and any(len(str(b)) > 420 for b in bullets):
            return True
        for b in bullets:
            if _text_looks_mashed(str(b)):
                return True
            if len(str(b)) > 520 and str(b).count(". ") >= 3:
                return True
    return False


def _text_looks_mashed(text: str) -> bool:
    sample = re.sub(r"\s+", " ", str(text or "").strip())
    if len(sample) < 40:
        return False
    letters = sum(1 for c in sample if c.isalpha())
    if letters < 40:
        return False
    if sample.count(" ") / max(letters, 1) < 0.08:
        return True
    return len(re.findall(r"[A-Za-z]{22,}", sample)) >= 2


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
        "description": expand_to_bullets(_as_list(desc)),
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
