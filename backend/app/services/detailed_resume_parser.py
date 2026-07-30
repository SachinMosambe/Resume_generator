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
    # Prefer an ALL-CAPS name banner common on Dice exports ("HARKARAN SIDHU | C: | E:").
    for line in lines[:20]:
        if "|" in line or "•" in line:
            left = re.split(r"[|•]", line)[0].strip()
            if 2 <= len(left.split()) <= 5 and "@" not in left and not re.search(r"\d{5,}", left):
                if re.match(r"^[A-Za-z][A-Za-z .'-]+$", left):
                    return left.title() if left.isupper() else left
    for line in lines[:16]:
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
                "preferred",
                "location",
                "summary",
                "education",
                "experience",
            ]
        ):
            continue
        if re.search(r"\d{4}", line):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and not re.search(r"[^a-zA-Z\s.\-']", line):
            title_case = sum(1 for w in words if w and w[0].isupper())
            if title_case >= len(words) // 2:
                return line.title() if line.isupper() else line
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
    # Common jammed headings without a colon: "Frameworks Python, PyTorch, ..."
    cat_prefix = re.compile(
        r"(?i)^(ML\s*&\s*AI|AI\s*/?\s*ML|Frameworks(?:\s*&\s*Databases)?|MLOps|"
        r"Cloud(?:\s*&\s*Tools)?|Data\s*Eng\.?|DevOps|Programming(?:\s*Languages)?|"
        r"Tools(?:\s*&\s*Platforms)?|Soft\s*Skills|Data\s*&\s*AI|Backend(?:\s*&\s*Frameworks)?|"
        r"Data\s*Science(?:\s*&\s*MLOps)?|Languages(?:\s*&\s*Frameworks)?)\b\s+"
    )
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
        else:
            m = cat_prefix.match(line)
            if m:
                category = re.sub(r"\s+", " ", m.group(1)).strip()
                payload = line[m.end() :].strip(" ,;|-")
                if not payload:
                    pending_category = category
                    continue
        parts = _split_skills_payload(payload)
        bucket = grouped.setdefault(category, [])
        for part in parts:
            skill = re.sub(r"^[\-\*\u2022\s]+", "", part).strip()
            if len(skill) < 2 or len(skill) > 100 or len(skill.split()) > 14:
                continue
            if skill.casefold() not in {s.casefold() for s in bucket}:
                bucket.append(skill)
        pending_category = category
    return {k: v for k, v in grouped.items() if v}


def _split_skills_payload(payload: str) -> list[str]:
    """Split skills on commas/pipes without breaking parenthetical groups like AWS (EC2, S3)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in str(payload or ""):
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in ",;|•*" and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


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

    # Pipe BEFORE dates: "Staff Engineer — AI/ML | Nagarro India July 2025 – Present"
    # or "AI/MLDeveloper|Aptino Technologies Mar 2026—Present"
    if "|" in before:
        parts = [p.strip() for p in before.split("|") if p.strip()]
        if len(parts) >= 2:
            left, right = parts[0], " | ".join(parts[1:]).strip()
            # Prefer role-like left as title when both sides look plausible.
            left_is_title = not _is_invalid_job_title(left) and len(left) <= 90
            right_is_company = len(right) >= 2 and not _is_invalid_job_title(right)
            if left_is_title and (right_is_company or len(parts) >= 2):
                title = left
                company = right

    # Pipe-separated: Company ... (dates) | Title | Project/Domain
    if "|" in after:
        parts = [p.strip() for p in after.split("|") if p.strip()]
        if parts and not _is_invalid_job_title(parts[0]):
            title = parts[0]
    elif after and not _DATE_PATTERN.fullmatch(after) and not _is_invalid_job_title(after):
        # Trailing title on same line without pipes
        title = after

    # "Title at Company" before the date
    if " at " in before.lower() and not title:
        left, right = re.split(r"\s+at\s+", before, maxsplit=1, flags=re.IGNORECASE)
        if not _is_invalid_job_title(left):
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
            # Optional next-line title when header only has company+dates.
            # Skip action-verb / sentence lines (common Dice PDF reordering).
            if not parsed["title"]:
                look = i + 1
                scanned = 0
                while look < len(lines) and scanned < 3:
                    candidate = lines[look].strip()
                    if not candidate:
                        look += 1
                        scanned += 1
                        continue
                    if _DATE_PATTERN.search(candidate) or _is_bullet(candidate):
                        break
                    # Location crumbs like "TX" / "India" / "Irving, TX" — keep as location.
                    if _looks_like_location_only(candidate):
                        if not parsed.get("location"):
                            parsed["location"] = _clean_text(candidate)
                        lines[look] = ""
                        look += 1
                        scanned += 1
                        continue
                    if (
                        not _is_section_heading_line(candidate)
                        and not re.match(r"(?i)^environment\s*:", candidate)
                        and not _is_gap_period_entry(candidate, "")
                        and not _is_invalid_job_title(candidate)
                        and len(candidate) < 120
                    ):
                        parsed["title"] = _clean_text(candidate)
                        # Consume only the title line; later loop continues after header.
                        lines[look] = ""
                        break
                    # Short non-title crumbs — skip.
                    if len(candidate.split()) <= 3 and len(candidate) <= 40:
                        look += 1
                        scanned += 1
                        continue
                    break
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
            # Soft-wrap crumbs ("across squads.") must stay on the previous role.
            if current_job and _looks_like_soft_wrap_continuation(line):
                clean_wrap = _clean_bullet_text(line)
                if clean_wrap:
                    if current_bullets:
                        current_bullets[-1] = f"{current_bullets[-1]} {clean_wrap}".strip()
                    else:
                        current_bullets.append(clean_wrap)
                i += 1
                continue
            _save_current()
            # Title on line 1, company+date on line 2 — or company on line 1, date on line 2
            duration = next_date.group(0).strip()
            company_line = next_line
            before = company_line[: next_date.start()].strip(" ,|(-–—")
            title = "" if _is_invalid_job_title(line) else line
            company = before or company_line
            location = ""
            # Also split "Title | Company <dates>" on the dated line.
            if "|" in before:
                bits = [b.strip() for b in before.split("|") if b.strip()]
                if len(bits) >= 2 and not title:
                    maybe_title, maybe_company = bits[0], " | ".join(bits[1:]).strip()
                    if not _is_invalid_job_title(maybe_title):
                        title = maybe_title
                        company = maybe_company
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
            current_bullets = []
            if _is_invalid_job_title(line) and line.strip():
                clean_seed = _clean_bullet_text(line)
                if clean_seed:
                    current_bullets.append(clean_seed)
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
    roles = _dedupe_experience_roles(experiences)
    return [_promote_title_from_first_bullet(role) for role in roles]


def _looks_like_embedded_role_title(text: str) -> bool:
    """True for Dice lines like 'Technology Lead| Project...' or 'Jr. Java Back-End Engineer | ...'."""
    t = str(text or "").strip()
    if not t or _is_invalid_job_title(t.split("|", 1)[0].strip()):
        return False
    left = t.split("|", 1)[0].strip()
    words = left.split()
    if not (1 <= len(words) <= 10):
        return False
    if _ACTION_VERB_START.match(left):
        return False
    if re.search(
        r"(?i)\b(engineer|developer|analyst|manager|architect|consultant|lead|intern|"
        r"specialist|programmer|freelancer)\b",
        left,
    ):
        return True
    if "|" in t and len(left) <= 60:
        return True
    return False


def _promote_title_from_first_bullet(role: dict[str, Any]) -> dict[str, Any]:
    """Recover missing titles that Dice dumps as the first detail line."""
    if not isinstance(role, dict):
        return role
    title = str(role.get("title") or "").strip()
    bullets = role.get("description") if isinstance(role.get("description"), list) else []
    # Location crumbs wrongly captured as title → move to location and recover title.
    if title and _looks_like_location_only(title):
        if not str(role.get("location") or "").strip():
            role = {**role, "location": title}
        title = ""
        role = {**role, "title": ""}
    if title or not bullets:
        return role
    first = str(bullets[0] or "").strip()
    if not _looks_like_embedded_role_title(first):
        return role
    left, _, right = first.partition("|")
    left = left.strip()
    right = right.strip()
    if _is_invalid_job_title(left):
        return role
    role = dict(role)
    role["title"] = _clean_text(left)
    remaining = list(bullets[1:])
    if right and len(right) > 24 and not re.match(r"(?i)^environment\s*:", right):
        # Keep project/domain context as a normal bullet.
        remaining.insert(0, right)
    role["description"] = remaining
    return role


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
    """Drop duplicate company+duration rows; keep the richer title/bullet set."""
    out: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for role in roles:
        key = _experience_role_key(role.get("company"), role.get("duration"))
        if not key:
            out.append(role)
            continue
        if key in index_by_key:
            prev = out[index_by_key[key]]
            prev_bullets = prev.get("description") if isinstance(prev.get("description"), list) else []
            new_bullets = role.get("description") if isinstance(role.get("description"), list) else []
            if len(new_bullets) > len(prev_bullets):
                # Preserve a good title if the richer row lacks one.
                if not role.get("title") and prev.get("title"):
                    role = {**role, "title": prev.get("title")}
                out[index_by_key[key]] = role
            elif role.get("title") and not prev.get("title"):
                prev["title"] = role.get("title")
            continue
        index_by_key[key] = len(out)
        out.append(role)
    return out


def _normalize_duration_key(duration: Any) -> str:
    text = str(duration or "").lower()
    text = text.replace("–", " ").replace("—", " ").replace("-", " ")
    text = re.sub(r"\s+to\s+", " ", text)
    months = {
        "january": "jan",
        "february": "feb",
        "march": "mar",
        "april": "apr",
        "may": "may",
        "june": "jun",
        "july": "jul",
        "august": "aug",
        "september": "sep",
        "october": "oct",
        "november": "nov",
        "december": "dec",
    }
    for long, short in months.items():
        text = text.replace(long, short)
    return re.sub(r"[^a-z0-9]+", "", text)


def _normalize_company_key(company: Any) -> str:
    text = str(company or "").lower()
    text = re.sub(r"\b(inc|llc|ltd|corp|co|limited|technologies|technology|pvt|private)\b\.?", "", text)
    return re.sub(r"[^a-z0-9]+", "", text)


def _experience_role_key(company: Any, duration: Any) -> str:
    company_key = _normalize_company_key(company)
    duration_key = _normalize_duration_key(duration)
    if not company_key:
        return ""
    return f"{company_key}|{duration_key}"


def _looks_like_location_only(text: str) -> bool:
    """True for bare location crumbs like 'TX', 'Remote', 'Irving, TX', 'India'."""
    t = str(text or "").strip()
    if not t:
        return True
    if re.fullmatch(r"(?i)remote|onsite|on-site|hybrid|wfh", t):
        return True
    if re.fullmatch(r"[A-Z]{2}", t):
        return True
    if re.fullmatch(r"(?i)india|usa|u\.s\.a\.?|united states|canada|uk|u\.k\.?", t):
        return True
    # City, ST / City, Country
    if re.fullmatch(r"(?i)[A-Za-z][A-Za-z .'-]{0,40},\s*([A-Z]{2}|[A-Za-z][A-Za-z .'-]{1,20})", t):
        if not re.search(
            r"(?i)\b(engineer|developer|analyst|manager|architect|lead|consultant|intern)\b",
            t,
        ):
            return True
    return False


def _is_invalid_job_title(text: str) -> bool:
    """True when a line is clearly a bullet/sentence, not a job title."""
    t = str(text or "").strip()
    if not t:
        return True
    if _looks_like_location_only(t):
        return True
    # Ignore common abbreviations (Jr./Sr./St.) when detecting sentence periods.
    t_for_sentence = re.sub(r"\b(Jr|Sr|Dr|Mr|Mrs|Ms|St|Dept)\.", r"\1", t, flags=re.I)
    if len(t) > 110 or t_for_sentence.count(". ") >= 1:
        return True
    words = t.split()
    # Lowercase sentence fragments / wrap crumbs are never titles.
    if t[:1].islower():
        return True
    if t_for_sentence.endswith(".") and len(words) >= 2:
        # Titles almost never end with a period; bullets/wraps often do.
        if not re.search(
            r"(?i)\b(engineer|developer|analyst|manager|architect|consultant|intern|lead|director|specialist)\b",
            t,
        ):
            return True
        if len(words) >= 6:
            return True
    if _ACTION_VERB_START.match(t) and len(words) >= 8:
        return True
    if len(words) >= 14:
        return True
    return False


def _looks_like_soft_wrap_continuation(line: str) -> bool:
    """True for wrapped bullet tails that precede the next dated employer line."""
    t = str(line or "").strip()
    if not t or _is_bullet(t) or _DATE_PATTERN.search(t):
        return False
    if t[:1].islower():
        return True
    words = t.split()
    if t.endswith(".") and len(words) <= 10 and _is_invalid_job_title(t):
        return True
    if _is_invalid_job_title(t) and len(words) <= 12:
        return True
    return False


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

        # Skip non-degree job-like dated lines, but KEEP degree rows that include
        # dates + pipes (e.g. "M.Tech ... | CGPA:9.09/10 Aug 2022—May 2024").
        if _DATE_PATTERN.search(line) and ("|" in line or "," in line) and not has_degree:
            continue

        if has_degree:
            if current:
                _save_current()

            # Prefer full date ranges on education lines when present.
            date_match = _DATE_PATTERN.search(line)
            year = date_match.group(0).strip() if date_match else ""
            if not year:
                year_match = year_re.search(line)
                year = year_match.group(1) if year_match else ""
            # CGPA on same line: "...|CGPA:9.09/10 Aug 2022—May 2024"
            cgpa = ""
            cgpa_match = re.search(
                r"(?:cgpa|gpa|percentage)[\s:]*([\d.]+(?:\s*/\s*\d+)?)",
                line,
                re.IGNORECASE,
            )
            if cgpa_match:
                cgpa = cgpa_match.group(1).strip()
            inst_match = inst_re.search(line)
            institution = inst_match.group(1) if inst_match else ""

            degree = line
            if institution:
                degree = degree.replace(institution, "").strip()
            if year:
                degree = degree.replace(year, "").strip()
            if cgpa:
                degree = re.sub(
                    r"(?i)(?:cgpa|gpa|percentage)[\s:]*" + re.escape(cgpa),
                    "",
                    degree,
                ).strip()
            degree = re.sub(r"[|,;]", " ", degree).strip()
            degree = re.sub(r"\s+", " ", degree).strip(" :-")
            # Fix soft-hyphen / broken wraps: "Tech nology" → "Technology"
            degree = re.sub(r"(?i)\btech\s+nology\b", "Technology", degree)
            degree = re.sub(r"(?i)\bengi\s+neering\b", "Engineering", degree)
            # Campus tokens belong on the institution (e.g. University of Illinois at Springfield).
            campus_match = re.search(
                r"(?i)\b(springfield|amravati|kharagpur|delhi)\b",
                degree,
            )
            if campus_match and institution:
                campus = campus_match.group(1).title()
                if campus.lower() not in institution.lower():
                    if "illinois" in institution.lower() and campus.lower() == "springfield":
                        institution = f"{institution} at Springfield"
                    elif campus.lower() not in {"delhi"}:
                        institution = f"{institution}, {campus}"
            # Drop leftover city/state crumbs after institution removal
            degree = re.sub(r"(?i)\b(springfield|delhi|india|il|tx|pa|nj|ks|va)\b", "", degree).strip(" ,")
            degree = re.sub(r"\s+", " ", degree).strip(" ,-")

            if len(degree) > 3:
                current = {
                    "degree": degree,
                    "institution": institution,
                    "location": "",
                    "year": year,
                    "cgpa": cgpa,
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
    non_cert_bleed = re.compile(
        r"(?i)\b(?:"
        r"leadership\s*&?\s*achievements?|leadership|achievements?|awards?|"
        r"led\s+\d+|mentored\s+\d+|core\s+committee|teaching\s+assistant|"
        r"championship|table\s+tennis|doubles\s+championship"
        r")\b"
    )
    for line in lines:
        clean = _clean_bullet_text(line)
        if not clean or len(clean) <= 2:
            continue
        if non_cert_bleed.search(clean) and section_key == "certifications":
            clean = non_cert_bleed.split(clean, maxsplit=1)[0].strip(" |")
            if not clean or len(clean) <= 3:
                continue
        # Split pipe-glued certification mega-lines.
        if "|" in clean and len(clean) > 80:
            parts = [p.strip() for p in clean.split("|") if p.strip()]
            expanded: list[str] = []
            for part in parts:
                cut = non_cert_bleed.split(part, maxsplit=1)[0].strip(" |")
                if cut and len(cut) > 3 and not _is_non_cert_item(cut):
                    expanded.append(cut)
            if expanded:
                items.extend(expanded)
                continue
        if _is_bullet(line):
            if section_key == "certifications" and _is_non_cert_item(clean):
                continue
            items.append(clean)
        elif items and not re.match(r"(?i)^(leadership|achievements?|awards?)\b", clean):
            # Soft-wrap continuation (e.g. "Specialization (DeepLearning.AI)").
            if section_key == "certifications" and re.fullmatch(
                r"(?i)specialization(?:\s*\([^)]*\))?",
                clean,
            ):
                items[-1] = f"{items[-1]} {clean}".strip()
                continue
            if section_key == "certifications" and _is_non_cert_item(clean):
                continue
            items[-1] = f"{items[-1]} {clean}".strip()
        else:
            if section_key == "certifications" and _is_non_cert_item(clean):
                continue
            items.append(clean)
    # Final split of leftover mega-items.
    final: list[str] = []
    for item in items:
        if "|" in item and len(item) > 100:
            for p in item.split("|"):
                cut = p.strip()
                if len(cut) > 3 and not _is_non_cert_item(cut):
                    final.append(cut)
        else:
            cut = non_cert_bleed.split(item, maxsplit=1)[0].strip(" |")
            if cut and not _is_non_cert_item(cut):
                final.append(cut)
    # Merge wrap fragments: "Natural Language Processing" + "Specialization (Deep Learning.AI)"
    merged: list[str] = []
    for item in final:
        if merged and re.fullmatch(r"(?i)specialization(?:\s*\([^)]*\))?", item.strip()):
            merged[-1] = f"{merged[-1]} {item.strip()}".strip()
            continue
        merged.append(item)
    return _dedupe(merged)


def _is_non_cert_item(text: str) -> bool:
    """Reject leadership / sports / conference lines that bled into certifications."""
    t = str(text or "").strip()
    if not t:
        return True
    if re.search(
        r"(?i)\b("
        r"led\s+\d+|mentored|championship|table\s+tennis|core\s+committee|"
        r"teaching\s+assistant|conference|doubles\b"
        r")\b",
        t,
    ):
        return True
    # Bare wrap fragments that are not standalone certs.
    if re.fullmatch(r"(?i)specialization(?:\s*\([^)]*\))?", t):
        return True
    return False


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
    text = re.sub(r"\s+", " ", text)
    # Common PDF jams in role titles / degree labels.
    text = re.sub(r"(?i)\b(AI/?ML)(Developer|Engineer|Architect|Specialist)\b", r"\1 \2", text)
    text = re.sub(r"(?i)\b(Master|Bachelor)(of)\b", r"\1 \2", text)
    text = re.sub(r"(?i)\b(Institute|College|University)(of)\b", r"\1 \2", text)
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

    # Repair jammed PDF text once up front so section extractors see readable lines.
    from app.services.pdf_parser import repair_collapsed_spaces

    resume_text = repair_collapsed_spaces(resume_text)

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
