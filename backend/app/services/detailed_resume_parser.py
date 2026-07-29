"""
Deterministic Resume Parser for Professional Resume Generation.

Extracts comprehensive, structured data from resumes using regex and
section-based parsing — zero LLM tokens, fast and reliable.
"""
from typing import Any

from app.services.pdf_parser import extract_text_from_pdf
from app.core.logging import logger

import re

# ─── Section heading aliases ───────────────────────────────────
_SECTION_HEADINGS = {
    "summary": ["summary", "professional summary", "profile", "objective", "about me", "about", "career objective", "professional profile"],
    "skills": ["skills", "technical skills", "core skills", "key skills", "competencies", "expertise", "technologies", "technical expertise"],
    "experience": ["experience", "work experience", "professional experience", "employment history", "career history", "work history", "professional background", "employment"],
    "education": ["education", "academic background", "academics", "qualifications", "degrees", "academic qualifications", "educational background", "academic credentials"],
    "projects": ["projects", "personal projects", "academic projects", "key projects", "project experience"],
    "certifications": ["certifications", "certificates", "licenses", "accreditations", "professional certifications"],
    "achievements": ["achievements", "awards", "honors", "accomplishments", "recognition"],
    "languages": ["languages", "language proficiency", "spoken languages"],
}

_DATE_PATTERN = re.compile(
    r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\s*[-–]\s*(?:Present|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}|\d{4})|\d{4}\s*[-–]\s*(?:Present|\d{4})',
    re.IGNORECASE,
)

_DEGREE_KEYWORDS = [
    "bachelor", "master", "phd", "doctorate", "mba", "bs", "ba", "ms", "ma",
    "b.tech", "b.e.", "m.tech", "m.e.", "b.sc", "m.sc", "b.com", "m.com",
    "bca", "mca", "bba", "bdes", "mdes", "associate", "diploma", "certificate",
    "high school", "12th", "10th", "ssc", "hsc", "cbse", "icse", "b.e", "m.e",
    "b.tech", "m.tech", "b.sc", "m.sc", "b.com", "m.com",
]


def _normalize_heading(line: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", line.lower()).strip()


def _find_section(text: str, target_keys: list[str]) -> list[str]:
    """Extract lines between a target section heading and the next known section heading."""
    all_normalized = set()
    for aliases in _SECTION_HEADINGS.values():
        all_normalized.update(_normalize_heading(a) for a in aliases)

    target_normalized = {_normalize_heading(k) for k in target_keys}
    captured: list[str] = []
    in_section = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        normalized = _normalize_heading(line)
        if not line:
            if in_section:
                captured.append("")
            continue
        if normalized in target_normalized or any(normalized.startswith(f"{t} ") for t in target_normalized):
            in_section = True
            continue
        if in_section and (normalized in all_normalized or any(normalized.startswith(f"{h} ") for h in all_normalized)):
            break
        if in_section:
            captured.append(line)
    return captured


def _is_section_heading_line(line: str) -> bool:
    """Heuristic: detect if a line is likely a section heading."""
    normalized = _normalize_heading(line)
    if not normalized:
        return False
    all_normalized = set()
    for aliases in _SECTION_HEADINGS.values():
        all_normalized.update(_normalize_heading(a) for a in aliases)
    return normalized in all_normalized


# ─── Contact extractors ────────────────────────────────────────
def _extract_email(text: str) -> str:
    match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    return match.group(0) if match else ""


def _extract_phone(text: str) -> str:
    patterns = [
        r'\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}',
        r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}',
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',
        r'\+91\s?\d{5}\s?\d{5}',
    ]
    for p in patterns:
        match = re.search(p, text)
        if match:
            return match.group(0).strip()
    return ""


def _extract_linkedin(text: str) -> str:
    match = re.search(r'https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_]+', text, re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_portfolio(text: str) -> str:
    match = re.search(r'https?://(?:www\.)?(?:github|gitlab|bitbucket)\.com/[A-Za-z0-9\-_]+', text, re.IGNORECASE)
    if match:
        return match.group(0)
    # Iterate over all URLs and return the first non-LinkedIn one
    url_pattern = re.compile(
        r'https?://(?:www\.)?[A-Za-z0-9\-_]+(?:\.[A-Za-z0-9\-_]+)*?\.(?:com|io|dev|net|org)[A-Za-z0-9\-_/.]*',
        re.IGNORECASE,
    )
    for m in url_pattern.finditer(text):
        url = m.group(0)
        if "linkedin" not in url.lower():
            return url
    return ""


def _extract_name(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:10]:
        if len(line) < 3 or len(line) > 60:
            continue
        lower = line.lower()
        if any(k in lower for k in ["resume", "cv", "curriculum", "page", "http", "www", "@", "phone", "email", "address", "linkedin"]):
            continue
        if re.search(r'\d{4}', line):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and not re.search(r'[^a-zA-Z\s\.\-]', line):
            # Title-case or all-caps heuristic
            title_case = sum(1 for w in words if w and w[0].isupper())
            if title_case >= len(words) // 2:
                return line
    return ""


def _extract_location(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for line in lines[:20]:
        # Match "City, ST" or "City, Country" patterns
        match = re.search(
            r'([A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?),\s*(?:[A-Z]{2,3}|[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)',
            line,
        )
        if match:
            loc = match.group(0)
            if not any(k in loc.lower() for k in ["page", "http", "www", "@", "experience", "education", "skills", "project", "certif"]):
                return loc
    return ""


# ─── Section extractors ────────────────────────────────────────
def _extract_summary(text: str) -> str:
    lines = _find_section(text, _SECTION_HEADINGS["summary"])
    if not lines:
        return ""
    paragraphs = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            current.append(line)
    if current:
        paragraphs.append(" ".join(current))
    summary = " ".join(paragraphs).strip()
    return summary[:900] if len(summary) > 900 else summary


def _extract_skills(text: str) -> list[str]:
    lines = _find_section(text, _SECTION_HEADINGS["skills"])
    if not lines:
        return []
    raw = " ".join(lines)
    parts = re.split(r'[,;|•\-\*\n\r]+', raw)
    skills = []
    for p in parts:
        s = p.strip()
        if not s:
            continue
        s = re.sub(r'^[\-\*\u2022\s]+', '', s).strip()
        if len(s.split()) > 6 or len(s) > 50 or len(s) < 2:
            continue
        skills.append(s)
    return _dedupe(skills)


def _extract_experience(text: str) -> list[dict[str, Any]]:
    lines = _find_section(text, _SECTION_HEADINGS["experience"])
    if not lines:
        return []

    experiences: list[dict[str, Any]] = []
    current_job: dict[str, Any] | None = None
    current_bullets: list[str] = []

    def _save_current():
        nonlocal current_job, current_bullets
        if current_job:
            current_job["description"] = [b for b in current_bullets if b]
            # Infer technologies from bullets
            techs: set[str] = set()
            for b in current_job["description"]:
                techs.update(_infer_technologies(b))
            if techs:
                current_job["technologies"] = list(techs)
            experiences.append(current_job)
        current_job = None
        current_bullets = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Heuristic: if this line (or next 2 lines) contains a date range,
        # treat it as the start of a new job block.
        window = " ".join(lines[i : min(i + 3, len(lines))])
        date_match = _DATE_PATTERN.search(window)

        if date_match and not _is_bullet(line):
            _save_current()
            duration = date_match.group(0).strip()

            # Try to identify title / company from the window
            window_before_date = window[: date_match.start()].strip()
            window_after_date = window[date_match.end() :].strip()

            title = ""
            company = ""
            location = ""

            # Common pattern: Title on line 1, Company on line 2, Date on line 3
            if i + 2 < len(lines) and _DATE_PATTERN.search(lines[i + 2]):
                title = line
                company = lines[i + 1].strip()
                duration = lines[i + 2].strip()
                i += 3
            elif i + 1 < len(lines) and _DATE_PATTERN.search(lines[i + 1]):
                # Two-line block: title + date, or company + date
                second = lines[i + 1].strip()
                if date_match.start() < len(lines[i]):
                    # Date is on the same line as title
                    title = window_before_date or line
                    company = window_after_date
                    i += 2
                else:
                    title = line
                    company = second[: date_match.start() - len(lines[i]) - 1].strip()
                    duration = date_match.group(0).strip()
                    i += 2
            else:
                # Date on same line as title/company
                parts = window_before_date.split(" at ")
                if len(parts) == 2:
                    title = parts[0].strip()
                    company = parts[1].strip()
                else:
                    title = window_before_date or line
                i += 1

            # Clean company of trailing location/dates
            company = re.sub(r'[,\|]\s*' + _DATE_PATTERN.pattern, '', company, flags=re.IGNORECASE).strip()
            location_match = re.search(r'([A-Za-z][A-Za-z\s,]+?)(?:\s*[|,]\s*\d{4}|$)', company)
            if location_match and len(location_match.group(1).split()) <= 4:
                # Heuristic: last part after comma might be location
                if ',' in company:
                    parts = company.rsplit(',', 1)
                    if len(parts) == 2 and len(parts[1].strip().split()) <= 3:
                        company = parts[0].strip()
                        location = parts[1].strip()

            current_job = {
                "title": _clean_text(title),
                "company": _clean_text(company),
                "location": _clean_text(location),
                "duration": _clean_text(duration),
                "description": [],
                "technologies": [],
            }
            continue

        # Collect bullet points / detail lines for current job.
        # Wrapped resume lines should continue the previous bullet sentence.
        if current_job:
            if _is_section_heading_line(line):
                i += 1
                continue
            clean = _clean_bullet_text(line)
            if clean and not _DATE_PATTERN.search(clean):
                if _is_bullet(line):
                    current_bullets.append(clean)
                elif current_bullets:
                    # Continuation line for prior bullet.
                    current_bullets[-1] = f"{current_bullets[-1]} {clean}".strip()
                else:
                    # Some resumes don't use bullet markers; keep as sentence bullets.
                    current_bullets.append(clean)
        i += 1

    _save_current()
    return experiences


def _extract_education(text: str) -> list[dict[str, Any]]:
    lines = _find_section(text, _SECTION_HEADINGS["education"])
    if not lines:
        return []

    education: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_details: list[str] = []

    def _save_current():
        nonlocal current, current_details
        if current and current.get("degree"):
            current["details"] = [d for d in current_details if d]
            education.append(current)
        current = None
        current_details = []

    year_re = re.compile(r'\b(19\d{2}|20\d{2})\b')
    inst_re = re.compile(r'((?:[A-Za-z][a-z]+\s+)*(?:University|College|Institute|School|Academy|IIT|NIT|IIIT|IIM|BITS|Tech))')

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                _save_current()
            continue

        line_lower = line.lower()
        has_degree = any(kw in line_lower for kw in _DEGREE_KEYWORDS)

        if has_degree and (not current or not current.get("degree")):
            if current:
                _save_current()

            year_match = year_re.search(line)
            year = year_match.group(1) if year_match else ""
            inst_match = inst_re.search(line)
            institution = inst_match.group(1) if inst_match else ""

            degree = line
            if institution:
                degree = degree.replace(institution, "").strip()
            if year:
                degree = degree.replace(year, "").strip()
            degree = re.sub(r'[|,;]', ' ', degree).strip()
            degree = re.sub(r'\s+', ' ', degree).strip()

            if len(degree) > 3:
                current = {
                    "degree": degree,
                    "institution": institution,
                    "location": "",
                    "year": year,
                    "cgpa": "",
                    "details": [],
                }
                current_details = []
        elif current:
            if not current.get("institution"):
                inst_match = inst_re.search(line)
                if inst_match:
                    current["institution"] = inst_match.group(1)
                    continue
            if not current.get("year"):
                year_match = year_re.search(line)
                if year_match:
                    current["year"] = year_match.group(1)
                    continue
            # CGPA / GPA / percentage
            if not current.get("cgpa"):
                cgpa_match = re.search(r'(?:cgpa|gpa|percentage)[\s:]*([\d.]+\s*/?\s*\d*)', line, re.IGNORECASE)
                if cgpa_match:
                    current["cgpa"] = cgpa_match.group(1).strip()
                    continue
            clean = re.sub(r'^[\-\*\u2022\s>]+', '', line).strip()
            if clean:
                current_details.append(clean)

    _save_current()
    return education


def _extract_projects(text: str) -> list[dict[str, Any]]:
    lines = _find_section(text, _SECTION_HEADINGS["projects"])
    if not lines:
        return []

    projects: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_desc: list[str] = []

    def _save_current():
        nonlocal current, current_desc
        if current and current.get("name"):
            current["description"] = [d for d in current_desc if d]
            projects.append(current)
        current = None
        current_desc = []

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                _save_current()
            continue

        clean = _clean_bullet_text(line)
        if not clean:
            continue

        if not current:
            # First line in a block is the project name
            tech_match = re.search(r'\(([^)]+)\)', clean)
            techs = []
            if tech_match:
                techs = [t.strip() for t in tech_match.group(1).split(",") if t.strip()]
                clean = clean.replace(tech_match.group(0), "").strip()
            current = {
                "name": clean,
                "description": [],
                "technologies": techs,
                "link": "",
                "duration": "",
            }
            current_desc = []
        else:
            if _is_bullet(line):
                current_desc.append(clean)
            elif current_desc:
                current_desc[-1] = f"{current_desc[-1]} {clean}".strip()
            else:
                current_desc.append(clean)

    _save_current()
    return projects


def _extract_bullet_list(text: str, section_key: str) -> list[str]:
    lines = _find_section(text, _SECTION_HEADINGS[section_key])
    items: list[str] = []
    for line in lines:
        clean = _clean_bullet_text(line)
        if not clean or len(clean) <= 2:
            continue
        if _is_bullet(line):
            items.append(clean)
        elif items:
            items[-1] = f"{items[-1]} {clean}".strip()
        else:
            items.append(clean)
    return _dedupe(items)


def _infer_technologies(text: str) -> set[str]:
    """Infer technologies mentioned in a bullet point."""
    tech_keywords = {
        "python", "java", "javascript", "typescript", "go", "golang", "rust", "c++", "c#",
        "ruby", "scala", "kotlin", "swift", "php", "shell", "bash", "sql",
        "html", "css", "react", "angular", "vue", "svelte", "next.js", "nuxt",
        "fastapi", "flask", "django", "spring boot", "express", "node.js", "nodejs",
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "cassandra",
        "dynamodb", "snowflake", "bigquery", "sqlite", "oracle", "mssql",
        "aws", "azure", "gcp", "google cloud", "kubernetes", "k8s", "docker",
        "terraform", "ansible", "jenkins", "ci/cd", "devops",
        "machine learning", "deep learning", "nlp", "computer vision", "pytorch",
        "tensorflow", "scikit-learn", "pandas", "numpy", "spark", "hadoop",
        "git", "github", "gitlab", "jira", "confluence", "linux", "unix",
        "figma", "adobe xd", "sketch", "prototyping", "wireframing",
    }
    found = set()
    text_lower = text.lower()
    for tech in tech_keywords:
        if tech in text_lower:
            found.add(tech.title() if tech not in {"aws", "gcp", "sql", "api", "ci/cd", "k8s", "nlp", "html", "css"} else tech.upper() if tech != "ci/cd" else "CI/CD")
    return found


def _is_bullet(line: str) -> bool:
    return bool(re.match(r'^[\-\*\u2022\u2023\u25AA\u25AB\u25CF\u25E6\u2043\u2219\uf0a7\uf0b7▪■●◦•>]+\s*', line.strip()))


def _clean_bullet_text(line: str) -> str:
    clean = re.sub(r'^[\-\*\u2022\u2023\u25AA\u25AB\u25CF\u25E6\u2043\u2219\uf0a7\uf0b7▪■●◦•>\s]+', '', str(line or '')).strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean


def _clean_text(text: Any) -> str:
    if not text:
        return ""
    text = str(text).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _empty_resume_data() -> dict[str, Any]:
    return {
        "name": "", "email": "", "phone": "", "location": "",
        "linkedin": "", "portfolio": "", "summary": "",
        "skills": [], "experience": [], "education": [],
        "projects": [], "certifications": [], "achievements": [], "languages": [],
    }


# ─── Public API ────────────────────────────────────────────────
def parse_resume_detailed(resume_path: str | None, resume_text: str | None = None) -> dict[str, Any]:
    """
    Parse resume with full detail using deterministic regex extraction.
    Zero LLM tokens — fast and privacy-preserving.
    """
    if not resume_text and resume_path:
        resume_text = extract_text_from_pdf(resume_path)

    if not resume_text:
        logger.warning("detailed_parser_no_text", resume_path=resume_path)
        return _empty_resume_data()

    result = {
        "name": _extract_name(resume_text),
        "email": _extract_email(resume_text),
        "phone": _extract_phone(resume_text),
        "location": _extract_location(resume_text),
        "linkedin": _extract_linkedin(resume_text),
        "portfolio": _extract_portfolio(resume_text),
        "summary": _extract_summary(resume_text),
        "skills": _extract_skills(resume_text),
        "experience": _extract_experience(resume_text),
        "education": _extract_education(resume_text),
        "projects": _extract_projects(resume_text),
        "certifications": _extract_bullet_list(resume_text, "certifications"),
        "achievements": _extract_bullet_list(resume_text, "achievements"),
        "languages": _extract_bullet_list(resume_text, "languages"),
    }

    logger.info(
        "deterministic_parse_complete",
        experience_count=len(result.get("experience", [])),
        education_count=len(result.get("education", [])),
        skills_count=len(result.get("skills", [])),
        projects_count=len(result.get("projects", [])),
    )
    return result
