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
    "achievements": [
        "achievements",
        "awards",
        "honors",
        "accomplishments",
        "recognition",
        "leadership",
        "leadership & achievements",
        "leadership and achievements",
        "extracurricular",
        "activities",
        "positions of responsibility",
    ],
    "languages": ["languages", "language proficiency", "spoken languages"],
}

# Supports: Aug 2025 - April 2026 | Aug 2025 to April 2026 | 2021–2022 | Jan 2021 – Present
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_SEP = r"(?:[-–—/]|to)"
_DATE_PATTERN = re.compile(
    rf"(?:{_MONTH}\s+\d{{4}}\s*{_DATE_SEP}\s*(?:Present|Current|{_MONTH}\s+\d{{4}}|\d{{4}})"
    rf"|\d{{4}}\s*{_DATE_SEP}\s*(?:Present|Current|\d{{4}}))",
    re.IGNORECASE,
)

_DICE_NOISE_RE = re.compile(
    r"(?i)\b("
    r"preferred|desired work|willing to relocate|work authorization|employment type|"
    r"profile source|profile downloaded|total experience|visa sponsorship|"
    r"authorized to work|contract\s*-\s*corp|now or in the future"
    r")\b"
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


def _is_known_heading(normalized: str, headings: set[str]) -> bool:
    """True when a line is a section heading, not body text that starts with a heading word."""
    if not normalized:
        return False
    if normalized in headings:
        return True
    # Long lines with lists/content are never headings (e.g. "Languages & Frameworks: Java, ...").
    if len(normalized.split()) > 6 or "," in normalized:
        return False
    for heading in headings:
        if normalized.startswith(f"{heading} "):
            rest = normalized[len(heading) :].strip()
            if len(rest.split()) <= 3 and len(rest) <= 40:
                return True
    return False


def _find_all_sections(text: str, target_keys: list[str]) -> list[str]:
    """Collect lines from every matching section heading (not just the first)."""
    all_normalized = set()
    for aliases in _SECTION_HEADINGS.values():
        all_normalized.update(_normalize_heading(a) for a in aliases)

    target_normalized = {_normalize_heading(k) for k in target_keys}
    captured: list[str] = []
    in_section = False

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        normalized = _normalize_heading(line)
        if not line:
            if in_section:
                captured.append("")
            continue
        if _is_known_heading(normalized, target_normalized):
            in_section = True
            captured.append("")  # separate blocks
            continue
        if in_section and _is_known_heading(normalized, all_normalized):
            in_section = False
            continue
        if in_section:
            captured.append(line)
    return captured


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
        if _is_known_heading(normalized, target_normalized):
            in_section = True
            continue
        if in_section and _is_known_heading(normalized, all_normalized):
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
    return _is_known_heading(normalized, all_normalized)


# ─── Contact extractors ────────────────────────────────────────
def _extract_email(text: str) -> str:
    # Prefer longest plausible email (avoid truncated fragments like 7814@gmail.com mid-token).
    matches = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")
    if not matches:
        # Recover emails broken by space repair: sachin 7814 @ gmail.com → join nearby.
        soft = re.search(
            r"\b([A-Za-z0-9._%+-]+)\s*@\s*([A-Za-z0-9.-]+)\s*\.\s*([A-Za-z]{2,})\b",
            text or "",
        )
        if soft:
            return f"{soft.group(1)}@{soft.group(2)}.{soft.group(3)}".replace(" ", "")
        return ""
    # Prefer emails with a local-part that looks complete (>= 5 chars) when available.
    ranked = sorted(matches, key=lambda e: (len(e.split("@")[0]) >= 5, len(e)), reverse=True)
    return ranked[0]


def _extract_phone(text: str) -> str:
    patterns = [
        r"\+?\d{1,3}[-.\s]?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}",
        r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}",
        r"\d{3}[-.\s]?\d{3}[-.\s]?\d{4}",
        r"\+91\s?\d{5}\s?\d{5}",
    ]
    for p in patterns:
        match = re.search(p, text or "")
        if match:
            return match.group(0).strip()
    return ""


def _extract_linkedin(text: str) -> str:
    match = re.search(
        r"https?://(?:www\.)?linkedin\.com/in/[A-Za-z0-9\-_]+",
        text or "",
        re.IGNORECASE,
    )
    return match.group(0) if match else ""


def _extract_portfolio(text: str) -> str:
    match = re.search(
        r"https?://(?:www\.)?(?:github|gitlab|bitbucket)\.com/[A-Za-z0-9\-_]+",
        text or "",
        re.IGNORECASE,
    )
    if match:
        return match.group(0)
    url_pattern = re.compile(
        r"https?://(?:www\.)?[A-Za-z0-9\-_]+(?:\.[A-Za-z0-9\-_]+)*?\.(?:com|io|dev|net|org)[A-Za-z0-9\-_/.]*",
        re.IGNORECASE,
    )
    for m in url_pattern.finditer(text or ""):
        url = m.group(0)
        if "linkedin" not in url.lower():
            return url
    return ""


def _extract_name(text: str) -> str:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for line in lines[:12]:
        # Contact-style first lines: "Name | email | phone"
        if "|" in line or "•" in line:
            left = re.split(r"[|•]", line)[0].strip()
            if 2 <= len(left.split()) <= 5 and "@" not in left and not re.search(r"\d{5,}", left):
                if re.match(r"^[A-Za-z][A-Za-z .'-]+$", left):
                    return left
        if len(line) < 3 or len(line) > 60:
            continue
        lower = line.lower()
        if any(
            k in lower
            for k in [
                "resume",
                "cv",
                "curriculum",
                "page",
                "http",
                "www",
                "@",
                "phone",
                "email",
                "address",
                "linkedin",
            ]
        ):
            continue
        if re.search(r"\d{4}", line):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and not re.search(r"[^a-zA-Z\s.\-']", line):
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
    # No hard truncate — store keeps full summary for any-length resumes.
    return " ".join(paragraphs).strip()


def _extract_skills_by_category(text: str) -> dict[str, list[str]]:
    """Preserve category labels from lines like 'Tools: Git, Jenkins, Docker'."""
    lines = _find_section(text, _SECTION_HEADINGS["skills"])
    if not lines:
        return {}
    grouped: dict[str, list[str]] = {}
    pending_category = "Technical Skills"
    for raw in lines:
        line = raw.strip()
        if not line or _DICE_NOISE_RE.search(line):
            continue
        category = pending_category
        payload = line
        if ":" in line and not line.lower().startswith("http"):
            left, _, right = line.partition(":")
            left_clean = left.strip()
            # Category headers are short; long left sides are not categories.
            if right.strip() and len(left_clean.split()) <= 8 and len(left_clean) <= 60:
                category = left_clean
                payload = right.strip()
            elif not right.strip() and len(left_clean.split()) <= 8:
                pending_category = left_clean
                continue
        parts = re.split(r"[,;|•\*]+", payload)
        bucket = grouped.setdefault(category, [])
        for part in parts:
            skill = re.sub(r"^[\-\*\u2022\s]+", "", part).strip()
            if len(skill) < 2 or len(skill) > 100 or len(skill.split()) > 14:
                continue
            if skill.casefold() not in {s.casefold() for s in bucket}:
                bucket.append(skill)
        pending_category = category
    return {k: v for k, v in grouped.items() if v}


def _extract_skills(text: str) -> list[str]:
    grouped = _extract_skills_by_category(text)
    if grouped:
        flat: list[str] = []
        seen: set[str] = set()
        for values in grouped.values():
            for skill in values:
                key = skill.casefold()
                if key in seen:
                    continue
                seen.add(key)
                flat.append(skill)
        return flat
    return []


def _parse_job_header_line(line: str, date_match: re.Match) -> dict[str, str]:
    """Parse headers like: Company, Loc (Aug 2025 to April 2026) | Title | Project."""
    duration = date_match.group(0).strip()
    before = line[: date_match.start()].strip(" ,|(-–—")
    after = line[date_match.end() :].strip(" ,|)-–—")

    title = ""
    company = before
    location = ""

    # Pipe-separated: Company ... (dates) | Title | Project/Domain
    if "|" in after:
        parts = [p.strip() for p in after.split("|") if p.strip()]
        if parts:
            title = parts[0]
    elif after and not _DATE_PATTERN.fullmatch(after):
        # Trailing title on same line without pipes
        title = after

    # "Title at Company" before the date
    if " at " in before.lower() and not title:
        left, right = re.split(r"\s+at\s+", before, maxsplit=1, flags=re.IGNORECASE)
        title = left.strip()
        company = right.strip()

    # Company, City, ST  → split location from trailing city/state
    if "," in company:
        bits = [b.strip() for b in company.split(",") if b.strip()]
        if len(bits) >= 2:
            # Keep first chunk(s) as company; last 1–2 short chunks as location.
            loc_bits: list[str] = []
            while bits and len(bits) > 1 and len(bits[-1].split()) <= 3 and len(bits[-1]) <= 40:
                candidate = bits[-1]
                if re.search(r"(?i)\b(inc|llc|ltd|corp|technologies|systems|services|group)\b", candidate):
                    break
                loc_bits.insert(0, bits.pop())
                if len(loc_bits) >= 2:
                    break
            if loc_bits:
                company = ", ".join(bits).strip()
                location = ", ".join(loc_bits).strip()

    return {
        "title": _clean_text(title),
        "company": _clean_text(company),
        "location": _clean_text(location),
        "duration": _clean_text(duration),
    }


def _extract_experience(text: str) -> list[dict[str, Any]]:
    lines = _find_section(text, _SECTION_HEADINGS["experience"])
    # Fallback: whole document when heading-based section is empty/missing.
    if not lines or sum(1 for ln in lines if _DATE_PATTERN.search(ln)) == 0:
        lines = [ln.strip() for ln in (text or "").splitlines()]

    experiences: list[dict[str, Any]] = []
    current_job: dict[str, Any] | None = None
    current_bullets: list[str] = []

    def _save_current():
        nonlocal current_job, current_bullets
        if current_job and (current_job.get("company") or current_job.get("title")):
            cleaned_bullets: list[str] = []
            for b in current_bullets:
                if not b:
                    continue
                if re.match(r"(?i)^environment\s*:", b):
                    env_payload = b.split(":", 1)[1].strip() if ":" in b else ""
                    _add_environment_techs(current_job, env_payload)
                    continue
                cleaned_bullets.append(b)
            current_job["description"] = cleaned_bullets
            if re.match(r"(?i)^environment\s*:", str(current_job.get("title") or "")):
                current_job["title"] = ""
            if _is_gap_period_entry(
                str(current_job.get("company") or ""),
                str(current_job.get("title") or ""),
            ):
                current_job = None
                current_bullets = []
                return
            # Keep Environment techs only — never invent tools from bullet keyword scans.
            experiences.append(current_job)
        current_job = None
        current_bullets = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Skip section headings and Dice profile noise so they never become roles.
        if _is_section_heading_line(line) or _DICE_NOISE_RE.search(line):
            i += 1
            continue

        # Strip trailing "Gap Period [...]" annotations glued onto title/company lines.
        line = re.sub(
            r"(?i)\s*gap\s*period\s*[\[\(][^\]\)]*[\]\)]\s*$",
            "",
            line,
        ).strip()
        if not line or _is_gap_period_entry(line, ""):
            i += 1
            continue

        date_match = _DATE_PATTERN.search(line)
        # Title/company on this line, date on next line
        next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
        next_date = _DATE_PATTERN.search(next_line) if next_line and not _is_bullet(next_line) else None

        if date_match and not _is_bullet(line):
            _save_current()
            parsed = _parse_job_header_line(line, date_match)
            if _is_gap_period_entry(parsed.get("company") or "", parsed.get("title") or ""):
                i += 1
                continue
            # Optional next-line title when header only has company+dates
            if not parsed["title"] and next_line and not next_date and not _is_bullet(next_line):
                if (
                    not _is_section_heading_line(next_line)
                    and not re.match(r"(?i)^environment\s*:", next_line)
                    and not _is_gap_period_entry(next_line, "")
                    and len(next_line) < 120
                ):
                    parsed["title"] = _clean_text(next_line)
                    i += 1
            current_job = {
                **parsed,
                "description": [],
                "technologies": [],
            }
            i += 1
            continue

        if next_date and not _is_bullet(line) and not date_match:
            if re.match(r"(?i)^environment\s*:", line) or _is_gap_period_entry(line, ""):
                i += 1
                continue
            _save_current()
            # Title on line 1, company+date on line 2 — or company on line 1, date on line 2
            duration = next_date.group(0).strip()
            company_line = next_line
            before = company_line[: next_date.start()].strip(" ,|(-–—")
            title = line
            company = before or company_line
            location = ""
            if "," in company:
                bits = [b.strip() for b in company.split(",") if b.strip()]
                if len(bits) >= 2 and len(bits[-1].split()) <= 3:
                    location = bits[-1]
                    company = ", ".join(bits[:-1])
            current_job = {
                "title": _clean_text(title),
                "company": _clean_text(company),
                "location": _clean_text(location),
                "duration": _clean_text(duration),
                "description": [],
                "technologies": [],
            }
            i += 2
            continue

        # Collect bullets / detail lines for the current job.
        if current_job:
            if _is_section_heading_line(line):
                i += 1
                continue
            norm = _normalize_heading(line)
            # Environment: Java, Spring Boot, ... → technologies for this role
            if norm.startswith("environment") or line.lower().startswith("environment:"):
                env_payload = line.split(":", 1)[1].strip() if ":" in line else ""
                _add_environment_techs(current_job, env_payload)
                i += 1
                continue
            clean = _clean_bullet_text(line)
            if clean and not _DATE_PATTERN.search(clean):
                if _is_bullet(line):
                    current_bullets.append(clean)
                elif current_bullets and not clean[:1].isupper():
                    # Soft wrap / continuation of previous bullet.
                    current_bullets[-1] = f"{current_bullets[-1]} {clean}".strip()
                elif _looks_like_new_achievement_bullet(clean, current_bullets):
                    current_bullets.append(clean)
                elif current_bullets and len(clean.split()) < 8 and not clean.endswith("."):
                    current_bullets[-1] = f"{current_bullets[-1]} {clean}".strip()
                else:
                    # Prefer discrete bullets over paragraph streams.
                    current_bullets.append(clean)
        i += 1

    _save_current()
    return _dedupe_experience_roles(experiences)


def _add_environment_techs(job: dict[str, Any], payload: str) -> None:
    if not payload:
        return
    techs = [t.strip() for t in re.split(r"[,;|]+", payload) if t.strip()]
    existing = job.setdefault("technologies", [])
    for tech in techs:
        if len(tech) > 80 or len(tech.split()) > 8:
            continue
        if tech.casefold() not in {str(x).casefold() for x in existing}:
            existing.append(tech)


def _is_gap_period_entry(company: str, title: str) -> bool:
    blob = f"{company} {title}".strip().lower()
    if not blob:
        return False
    return bool(re.search(r"\bgap\s*period\b", blob)) or blob.startswith("gap period")


def _dedupe_experience_roles(roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate company+duration rows (e.g. repeated Gap Period / AIG)."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for role in roles:
        key = re.sub(
            r"[^a-z0-9]+",
            "",
            f"{role.get('company') or ''}{role.get('title') or ''}{role.get('duration') or ''}".lower(),
        )
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(role)
    return out


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


def _looks_like_new_achievement_bullet(clean: str, current_bullets: list[str]) -> bool:
    """True when a non-glyph line should start a new bullet instead of merging."""
    if not clean:
        return False
    if not current_bullets:
        return True
    prev = current_bullets[-1].rstrip()
    if prev.endswith((".", ";", ":")) and clean[:1].isupper():
        return True
    if _ACTION_VERB_START.match(clean) and len(prev) >= 60:
        return True
    if clean[:1].isupper() and len(clean.split()) >= 8 and len(prev) >= 80:
        return True
    return False


def _extract_education(text: str) -> list[dict[str, Any]]:
    # Use every Education block (Dice header + resume footer) plus degree/@ lines.
    lines = _find_all_sections(text, _SECTION_HEADINGS["education"])
    for ln in (text or "").splitlines():
        raw = ln.strip()
        if not raw:
            continue
        low = raw.lower()
        if "@" in raw and any(k in low for k in ("bachelor", "master", "phd", "mba", "b.tech", "m.tech")):
            lines.append(raw)
        elif any(k in low for k in ("bachelor", "master of", "b.tech", "m.tech", "bachelors", "masters")):
            if "university" in low or "college" in low or "institute" in low:
                lines.append(raw)

    education: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_details: list[str] = []

    def _save_current():
        nonlocal current, current_details
        if current and current.get("degree"):
            current["details"] = [d for d in current_details if d and not _DICE_NOISE_RE.search(d)]
            education.append(current)
        current = None
        current_details = []

    year_re = re.compile(r"\b(19\d{2}|20\d{2})\b")
    inst_re = re.compile(
        r"((?:[A-Za-z][A-Za-z.&'\-]+\s+){0,6}"
        r"(?:University|College|Institute|School|Academy|IIT|NIT|IIIT|IIM|BITS)"
        r"(?:\s+of\s+[A-Za-z][A-Za-z.&'\-]+(?:\s+[A-Za-z][A-Za-z.&'\-]+){0,4})?)"
    )
    at_re = re.compile(
        r"(?i)\b((?:bachelor|master|masters|phd|mba|b\.?tech|m\.?tech|bachelors|ms|bs|ba|ma)[^@]{0,60}?)\s*@\s*(.+)$"
    )

    for line in lines:
        line = line.strip()
        if not line or _DICE_NOISE_RE.search(line):
            continue
        # Don't treat job headers as education details.
        if _DATE_PATTERN.search(line) and ("|" in line or "," in line):
            continue

        # Dice-style: "Bachelors @ Delhi Technological University"
        at_match = at_re.search(line)
        if at_match:
            _save_current()
            degree = re.sub(r"\s+", " ", at_match.group(1)).strip(" :-")
            institution = re.sub(r"\s+", " ", at_match.group(2)).strip(" :-")
            year_match = year_re.search(line)
            education.append(
                {
                    "degree": _clean_text(degree),
                    "institution": _clean_text(institution),
                    "location": "",
                    "year": year_match.group(1) if year_match else "",
                    "cgpa": "",
                    "details": [],
                }
            )
            current = None
            current_details = []
            continue

        line_lower = line.lower()
        has_degree = any(kw in line_lower for kw in _DEGREE_KEYWORDS)

        if has_degree:
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
            degree = re.sub(r"[|,;]", " ", degree).strip()
            degree = re.sub(r"\s+", " ", degree).strip(" :-")
            # Fix soft-hyphen / broken wraps: "Tech nology" → "Technology"
            degree = re.sub(r"(?i)\btech\s+nology\b", "Technology", degree)
            degree = re.sub(r"(?i)\bengi\s+neering\b", "Engineering", degree)
            # Drop leftover city/state crumbs after institution removal
            degree = re.sub(r"(?i)\b(springfield|delhi|india|il|tx|pa|nj|ks|va)\b", "", degree).strip(" ,")
            degree = re.sub(r"\s+", " ", degree).strip(" ,-")

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
            continue
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
            if not current.get("cgpa"):
                cgpa_match = re.search(
                    r"(?:cgpa|gpa|percentage)[\s:]*([\d.]+\s*/?\s*\d*)", line, re.IGNORECASE
                )
                if cgpa_match:
                    current["cgpa"] = cgpa_match.group(1).strip()
                    continue
            clean = re.sub(r"^[\-\*\u2022\s>]+", "", line).strip()
            if clean and not _DICE_NOISE_RE.search(clean) and len(clean) < 160:
                current_details.append(clean)

    _save_current()
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in education:
        inst = (item.get("institution") or "").lower()
        deg = (item.get("degree") or "").lower()
        key = f"{inst}|{deg[:48]}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


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

    def _looks_like_project_title(clean: str) -> bool:
        if not clean or _is_bullet(clean):
            return False
        # RetrieveIQ – Something | EMIPredictAI–Financial ...
        if re.search(r"[–—\-]\s*[A-Z]", clean) and len(clean.split()) <= 14:
            return True
        if re.match(r"^[A-Z][A-Za-z0-9]+(?:[A-Z][a-z0-9]+)+", clean) and len(clean) <= 90:
            return True
        if len(clean.split()) <= 10 and not clean.endswith(".") and clean[:1].isupper():
            # Title-ish line without being a long sentence.
            if clean.count(". ") == 0 and len(clean) <= 100:
                return True
        return False

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                _save_current()
            continue

        clean = _clean_bullet_text(line)
        if not clean:
            continue

        # Split mashed ".... generation. EMIPredictAI–..." into bullet + new project.
        split_match = re.search(
            r"(?<=[.!?])\s+(?=[A-Z][A-Za-z0-9].{0,40}[–—\-])",
            clean,
        )
        if current and split_match and not _is_bullet(line):
            left = clean[: split_match.start()].strip()
            right = clean[split_match.start() :].strip()
            if left:
                current_desc.append(left)
            _save_current()
            clean = right
            line = right

        if not current or (_looks_like_project_title(clean) and not _is_bullet(line) and current_desc):
            if current and _looks_like_project_title(clean) and not _is_bullet(line):
                _save_current()
            if not current:
                tech_match = re.search(r"\(([^)]+)\)", clean)
                techs = []
                if tech_match:
                    techs = [t.strip() for t in tech_match.group(1).split(",") if t.strip()]
                    clean = clean.replace(tech_match.group(0), "").strip()
                # Trim trailing sentence fragments incorrectly glued to title.
                name = re.split(r"(?<=[.!?])\s+", clean)[0].strip()
                current = {
                    "name": name,
                    "description": [],
                    "technologies": techs,
                    "link": "",
                    "duration": "",
                }
                current_desc = []
                continue

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
        # Split pipe-glued certification mega-lines.
        if "|" in clean and len(clean) > 80:
            parts = [p.strip() for p in clean.split("|") if p.strip()]
            # Also cut leadership bleed after certifications.
            expanded: list[str] = []
            for part in parts:
                cut = re.split(
                    r"(?i)\b(?:leadership\s*&?\s*achievements?|leadership|achievements?)\b",
                    part,
                    maxsplit=1,
                )[0].strip(" |")
                if cut and len(cut) > 3:
                    expanded.append(cut)
            if expanded:
                items.extend(expanded)
                continue
        if _is_bullet(line):
            items.append(clean)
        elif items and not re.match(r"(?i)^(leadership|achievements?|awards?)\b", clean):
            items[-1] = f"{items[-1]} {clean}".strip()
        else:
            items.append(clean)
    # Final split of leftover mega-items.
    final: list[str] = []
    for item in items:
        if "|" in item and len(item) > 100:
            final.extend([p.strip() for p in item.split("|") if len(p.strip()) > 3])
        else:
            # Strip leadership bleed.
            cut = re.split(
                r"(?i)\b(?:leadership\s*&?\s*achievements?|led\s+\d+-participant)\b",
                item,
                maxsplit=1,
            )[0].strip(" |")
            if cut:
                final.append(cut)
    return _dedupe(final)


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
        "skills": [], "skills_by_category": {}, "experience": [], "education": [],
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

    skills_by_category = _extract_skills_by_category(resume_text)
    skills = []
    for values in skills_by_category.values():
        skills.extend(values)
    if not skills:
        skills = _extract_skills(resume_text)

    result = {
        "name": _extract_name(resume_text),
        "email": _extract_email(resume_text),
        "phone": _extract_phone(resume_text),
        "location": _extract_location(resume_text),
        "linkedin": _extract_linkedin(resume_text),
        "portfolio": _extract_portfolio(resume_text),
        "summary": _extract_summary(resume_text),
        "skills": _dedupe(skills),
        "skills_by_category": skills_by_category,
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
        skill_categories=len(result.get("skills_by_category") or {}),
        projects_count=len(result.get("projects", [])),
    )
    return result
