"""
Section-wise resume quality gate.

Runs after every generation pass. Validates each section independently,
applies deterministic repairs, and reports remaining critical issues.
Quality is prioritized over speed.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.logging import logger
from app.services.pdf_parser import repair_collapsed_spaces
from app.services.structured_resume_store import expand_to_bullets
from app.services.tech_glossary import normalize_skill_token, restore_tech_names


def audit_and_repair_document(
    document: dict[str, Any],
    candidate_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """
    Validate + repair every section.

    Returns (repaired_document, findings) where each finding is:
      {"section": "...", "severity": "critical|warn", "issue": "..."}
    """
    import copy

    doc = copy.deepcopy(document or {})
    findings: list[dict[str, str]] = []
    candidate_data = candidate_data or {}

    findings.extend(_check_header(doc, candidate_data))
    findings.extend(_repair_and_check_summary(doc))
    findings.extend(_repair_and_check_experience(doc, candidate_data))
    findings.extend(_repair_and_check_skills(doc, candidate_data))
    findings.extend(_repair_and_check_education(doc, candidate_data))
    findings.extend(_repair_and_check_projects(doc, candidate_data))
    findings.extend(_repair_and_check_certifications(doc, candidate_data))
    findings.extend(_check_section_titles(doc))

    critical = sum(1 for f in findings if f.get("severity") == "critical")
    warn = sum(1 for f in findings if f.get("severity") == "warn")
    logger.info(
        "resume_section_quality_audit",
        critical=critical,
        warnings=warn,
        issues=[f"{f['section']}:{f['issue']}" for f in findings[:12]],
    )
    return doc, findings


def critical_findings(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    return [f for f in findings if f.get("severity") == "critical"]


def findings_as_feedback(findings: list[dict[str, str]]) -> list[str]:
    """Convert findings into rewrite feedback strings."""
    out: list[str] = []
    for f in findings:
        section = f.get("section") or "resume"
        issue = f.get("issue") or ""
        sev = (f.get("severity") or "warn").upper()
        out.append(f"[{sev}] {section}: {issue}")
    return out


def _check_header(doc: dict[str, Any], candidate_data: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    header = doc.get("header") if isinstance(doc.get("header"), dict) else {}
    name = str(header.get("name") or candidate_data.get("name") or "").strip()
    if not name or len(name.split()) < 2:
        src_name = str(candidate_data.get("name") or "").strip()
        if src_name and len(src_name.split()) >= 2:
            header["name"] = src_name
            doc["header"] = header
            name = src_name
        else:
            findings.append(
                {"section": "header", "severity": "critical", "issue": "Candidate name is missing."}
            )
    else:
        header["name"] = name
        doc["header"] = header

    contact = header.get("contact") if isinstance(header.get("contact"), list) else []
    contact = [str(c).strip() for c in contact if str(c).strip()]
    email = str(candidate_data.get("email") or "").strip()
    phone = str(candidate_data.get("phone") or "").strip()
    location = str(candidate_data.get("location") or "").strip()

    # Fix truncated / missing email in contact.
    contact_emails = [c for c in contact if "@" in c]
    bad_email = False
    for em in contact_emails:
        local = em.split("@", 1)[0]
        if len(local) < 5 or local.isdigit():
            bad_email = True
    if email and ("@" not in " ".join(contact) or bad_email):
        contact = [c for c in contact if "@" not in c]
        contact.insert(0, email)
    if phone and not any(re.search(r"\d{5,}", c) for c in contact):
        contact.append(phone)
    if location:
        # Avoid duplicate city tokens.
        if not any(location.casefold() in c.casefold() or c.casefold() in location.casefold() for c in contact):
            contact.append(location)
    # Dedupe contact while preserving order.
    seen = set()
    clean_contact = []
    for c in contact:
        key = c.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean_contact.append(c)
    header["contact"] = clean_contact
    doc["header"] = header

    final_emails = [c for c in clean_contact if "@" in c]
    if not final_emails:
        findings.append(
            {"section": "header", "severity": "critical", "issue": "Valid email is missing from contact."}
        )
    elif any(len(e.split("@")[0]) < 5 for e in final_emails):
        findings.append(
            {
                "section": "header",
                "severity": "critical",
                "issue": "Email looks truncated; restore full address from source.",
            }
        )
    return findings


def _repair_and_check_summary(doc: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        if "summary" not in str(section.get("title") or "").lower() and section.get("type") != "text":
            # Only touch first text/summary-like section
            continue
        title = str(section.get("title") or "").lower()
        if "summary" not in title and "objective" not in title and "profile" not in title:
            continue
        content = restore_tech_names(repair_collapsed_spaces(str(section.get("content") or "").strip()))
        content = re.sub(r"\s+", " ", content).strip()
        # Strip leading NAME IS / NAME is boilerplate duplication if present awkwardly.
        content = re.sub(r"^[A-Z][A-Za-z .'-]{2,40}\s+is\s+a\s+", "A ", content, count=1)
        section["content"] = content
        if len(content) < 80:
            findings.append(
                {
                    "section": "summary",
                    "severity": "critical",
                    "issue": "Professional summary is too short or empty.",
                }
            )
        elif _looks_mashed(content):
            findings.append(
                {
                    "section": "summary",
                    "severity": "critical",
                    "issue": "Summary has mashed/jammed words; needs rewrite with normal spacing.",
                }
            )
        break
    return findings


def _repair_and_check_experience(
    doc: dict[str, Any],
    candidate_data: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    src_roles = [r for r in (candidate_data.get("experience") or []) if isinstance(r, dict)]
    src_by_key = {
        _role_key(r.get("company"), r.get("duration") or r.get("dates")): r for r in src_roles
    }

    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "experience" not in title and stype not in {"experience", "employment"}:
            continue

        items = section.get("content") if isinstance(section.get("content"), list) else []
        cleaned: list[dict[str, Any]] = []
        env_as_title = 0
        gap_roles = 0
        thin_roles = 0
        para_roles = 0
        mashed = 0
        bullet_titles = 0
        duplicates_removed = 0
        seen_keys: set[str] = set()

        for item in items:
            if not isinstance(item, dict):
                continue
            role = dict(item)
            company = str(role.get("company") or "").strip()
            role_title = str(role.get("title") or role.get("role") or "").strip()
            location = str(role.get("location") or "").strip()
            duration = str(role.get("duration") or role.get("dates") or "").strip()

            if _is_gap_period(company, role_title):
                gap_roles += 1
                continue

            # Environment lines must never be titles/locations.
            if re.match(r"(?i)^environment\s*:", role_title):
                env_payload = role_title.split(":", 1)[1].strip() if ":" in role_title else ""
                role_title = ""
                env_as_title += 1
                _merge_env_techs(role, env_payload)
            if re.match(r"(?i)^environment\s*:", location):
                env_payload = location.split(":", 1)[1].strip() if ":" in location else ""
                location = ""
                env_as_title += 1
                _merge_env_techs(role, env_payload)
            if re.match(r"(?i)^environment\s*:", company):
                gap_roles += 1
                continue

            # Bullet/sentence wrongly placed as title → move into description.
            if _looks_like_bullet_as_title(role_title):
                bullets_seed = role.get("description") if isinstance(role.get("description"), list) else []
                role["description"] = [role_title, *bullets_seed]
                role_title = ""
                bullet_titles += 1
                # Recover real title from source when possible.
                src = src_by_key.get(_role_key(company, duration))
                if src and str(src.get("title") or "").strip():
                    role_title = str(src.get("title") or "").strip()

            bullets_raw = role.get("description") or role.get("details") or []
            bullets: list[str] = []
            for b in expand_to_bullets(
                [
                    repair_collapsed_spaces(str(x))
                    for x in (bullets_raw if isinstance(bullets_raw, list) else [bullets_raw])
                ],
                max_bullets=10,
            ):
                text = re.sub(r"\s+", " ", str(b).strip())
                if not text or len(text) < 12:
                    continue
                if re.match(r"(?i)^environment\s*:", text):
                    _merge_env_techs(role, text.split(":", 1)[1].strip() if ":" in text else "")
                    continue
                if _looks_mashed(text):
                    mashed += 1
                    text = repair_collapsed_spaces(text)
                bullets.append(restore_tech_names(text))

            techs = []
            for t in role.get("technologies") or []:
                name = str(t).strip()
                if not name or len(name) > 50 or len(name.split()) > 5:
                    continue
                if name.lower().startswith("environment"):
                    continue
                techs.append(name)

            role["company"] = company
            role["title"] = role_title
            role["location"] = location
            role["duration"] = duration
            role["description"] = _dedupe_bullets(bullets)
            role["technologies"] = techs[:10]

            if not (company or role_title):
                continue

            key = _role_key(company, duration)
            if key and key in seen_keys:
                # Keep the richer duplicate.
                duplicates_removed += 1
                for idx, existing in enumerate(cleaned):
                    if _role_key(existing.get("company"), existing.get("duration")) == key:
                        if len(role["description"]) > len(existing.get("description") or []):
                            cleaned[idx] = role
                        elif role_title and not existing.get("title"):
                            existing["title"] = role_title
                        break
                continue
            if key:
                seen_keys.add(key)

            if len(role["description"]) < 2:
                thin_roles += 1
            if len(role["description"]) <= 2 and any(
                len(b) > 350 and b.count(". ") >= 2 for b in role["description"]
            ):
                para_roles += 1
            cleaned.append(role)

        section["content"] = cleaned
        section["type"] = "experience"

        if duplicates_removed:
            findings.append(
                {
                    "section": "experience",
                    "severity": "warn",
                    "issue": f"Removed {duplicates_removed} duplicate employer rows.",
                }
            )
        if bullet_titles:
            findings.append(
                {
                    "section": "experience",
                    "severity": "warn",
                    "issue": f"Moved {bullet_titles} bullet-like role titles back into bullets.",
                }
            )
        if env_as_title:
            findings.append(
                {
                    "section": "experience",
                    "severity": "critical",
                    "issue": "Environment/tech lines were used as role titles; repaired, verify role titles.",
                }
            )
        if gap_roles:
            findings.append(
                {
                    "section": "experience",
                    "severity": "warn",
                    "issue": f"Removed {gap_roles} Gap Period / invalid employer rows.",
                }
            )
        if mashed:
            # Deterministic repair already attempted — warn only unless still badly jammed.
            still = sum(1 for r in cleaned for b in (r.get("description") or []) if _looks_mashed(b))
            if still:
                findings.append(
                    {
                        "section": "experience",
                        "severity": "critical",
                        "issue": "Experience bullets contain mashed/jammed text.",
                    }
                )
            else:
                findings.append(
                    {
                        "section": "experience",
                        "severity": "warn",
                        "issue": "Repaired mashed/jammed experience text.",
                    }
                )
        if para_roles:
            findings.append(
                {
                    "section": "experience",
                    "severity": "critical",
                    "issue": "Some roles still use paragraph streams instead of discrete bullets.",
                }
            )
        if thin_roles >= max(2, int(len(cleaned) * 0.4)):
            findings.append(
                {
                    "section": "experience",
                    "severity": "critical",
                    "issue": "Too many roles have fewer than 2 bullets; restore genuine achievements.",
                }
            )
        if src_roles and len(cleaned) < max(1, int(len(src_roles) * 0.75)):
            findings.append(
                {
                    "section": "experience",
                    "severity": "critical",
                    "issue": f"Experience incomplete ({len(cleaned)}/{len(src_roles)} roles).",
                }
            )
        if not cleaned and src_roles:
            findings.append(
                {
                    "section": "experience",
                    "severity": "critical",
                    "issue": "Experience section is empty after cleanup.",
                }
            )
        break
    return findings


def _role_key(company: Any, duration: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", f"{company or ''}{duration or ''}".lower())


def _looks_like_bullet_as_title(title: str) -> bool:
    text = str(title or "").strip()
    if len(text) < 60:
        return False
    if text.count(". ") >= 1 or text.endswith("."):
        return True
    if len(text.split()) >= 14 and re.match(
        r"(?i)^(architected|developed|designed|implemented|built|led|engineered|applied|managed|created|utilized|worked|responsible)\b",
        text,
    ):
        return True
    return False


def _dedupe_bullets(bullets: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for b in bullets:
        key = re.sub(r"[^a-z0-9]+", "", b.lower())
        if len(key) < 12 or key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def _looks_mashed(text: str) -> bool:
    sample = re.sub(r"\s+", " ", str(text or "").strip())
    if len(sample) < 40:
        return False
    letters = sum(1 for c in sample if c.isalpha())
    if letters < 40:
        return False
    # Ignore CamelCase tech tokens (SpringBoot, WebFlux, OpenShift) — not mashed English.
    long_tokens = []
    for tok in re.findall(r"[A-Za-z]{18,}", sample):
        if re.search(r"[a-z][A-Z]", tok):
            continue  # CamelCase
        if tok.lower() in {
            "microservices",
            "personalization",
            "recommendation",
            "authentication",
            "infrastructure",
            "containerized",
            "telecommunications",
        }:
            continue
        long_tokens.append(tok)
    if sample.count(" ") / max(letters, 1) < 0.08:
        return True
    return len(long_tokens) >= 2


def _repair_and_check_skills(
    doc: dict[str, Any],
    candidate_data: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    src_grouped = candidate_data.get("skills_by_category")
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "skill" not in title and stype not in {"skills", "skill"}:
            continue

        content = section.get("content")
        # Prefer source categories when document skills look remapped/wrong.
        if isinstance(src_grouped, dict) and src_grouped:
            bad_soft = False
            if isinstance(content, dict):
                soft = content.get("Soft Skills") or content.get("soft skills") or []
                soft_text = " ".join(str(x).lower() for x in soft)
                if re.search(r"microservices|distributed systems|spring boot|ci/cd|kafka", soft_text):
                    bad_soft = True
            if bad_soft or not isinstance(content, dict) or len(content) < 2:
                section["content"] = {
                    str(k): [normalize_skill_token(str(v)) for v in (vals or []) if str(v).strip()][:16]
                    for k, vals in src_grouped.items()
                    if str(k).strip() and vals
                }
                findings.append(
                    {
                        "section": "skills",
                        "severity": "warn",
                        "issue": "Restored source skill categories after bad remapping.",
                    }
                )
                content = section["content"]

        if isinstance(content, dict):
            cleaned = {}
            for cat, vals in content.items():
                skills = []
                for v in vals or []:
                    name = normalize_skill_token(str(v))
                    if not name or len(name) > 80 or len(name.split()) > 12:
                        continue
                    if re.search(r"(?i)\b(responsible for|architected and|developed a)\b", name):
                        continue
                    skills.append(name)
                if skills:
                    cleaned[str(cat).strip()] = skills[:16]
            section["content"] = cleaned
            section["type"] = "skills"
            if sum(len(v) for v in cleaned.values()) < 8:
                findings.append(
                    {
                        "section": "skills",
                        "severity": "critical",
                        "issue": "Skills section is too thin after cleanup.",
                    }
                )
        elif isinstance(content, list) and len(content) < 8:
            findings.append(
                {
                    "section": "skills",
                    "severity": "critical",
                    "issue": "Skills section is too thin.",
                }
            )
        break
    return findings


def _repair_and_check_education(
    doc: dict[str, Any],
    candidate_data: dict[str, Any],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    stubs = {"institute", "college", "university", "school", "academy", "iit", "institution"}
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "education" not in title and stype != "education":
            continue

        items = section.get("content") if isinstance(section.get("content"), list) else []
        cleaned: list[dict[str, Any]] = []
        stub_hits = 0
        src_edu = [e for e in (candidate_data.get("education") or []) if isinstance(e, dict)]
        for item in items:
            if not isinstance(item, dict):
                continue
            degree = str(item.get("degree") or item.get("title") or "").strip()
            institution = str(
                item.get("institution")
                or item.get("school")
                or item.get("university")
                or item.get("college")
                or item.get("company")
                or ""
            ).strip()
            year = str(item.get("year") or item.get("duration") or item.get("date") or "").strip()
            if institution.casefold() in stubs:
                stub_hits += 1
                institution = ""
            # Recover full institution from source when stub was stripped.
            if degree and not institution and src_edu:
                for src in src_edu:
                    src_degree = str(src.get("degree") or "").strip().lower()
                    if src_degree and (src_degree in degree.lower() or degree.lower() in src_degree):
                        institution = str(src.get("institution") or src.get("school") or "").strip()
                        if institution.casefold() in stubs:
                            institution = ""
                        if not year:
                            year = str(src.get("year") or "").strip()
                        break
            if not degree and not institution:
                continue
            # Drop experience-style contamination.
            blob = f"{degree} {institution}".lower()
            if re.search(r"\b(developed|implemented|deployed|microservices)\b", blob):
                continue
            cleaned.append(
                {
                    "degree": degree,
                    "institution": institution,
                    "year": year,
                    "location": str(item.get("location") or "").strip(),
                    "cgpa": str(item.get("cgpa") or "").strip(),
                }
            )

        if not cleaned:
            # Restore from candidate data when section was destroyed.
            for src in candidate_data.get("education") or []:
                if not isinstance(src, dict):
                    continue
                degree = str(src.get("degree") or "").strip()
                institution = str(src.get("institution") or src.get("school") or "").strip()
                if institution.casefold() in stubs:
                    institution = ""
                if degree or institution:
                    cleaned.append(
                        {
                            "degree": degree,
                            "institution": institution,
                            "year": str(src.get("year") or "").strip(),
                            "location": str(src.get("location") or "").strip(),
                            "cgpa": str(src.get("cgpa") or "").strip(),
                        }
                    )
            if cleaned:
                findings.append(
                    {
                        "section": "education",
                        "severity": "warn",
                        "issue": "Restored education from source after empty/invalid section.",
                    }
                )

        section["content"] = cleaned
        section["type"] = "education"
        if stub_hits:
            findings.append(
                {
                    "section": "education",
                    "severity": "warn",
                    "issue": "Removed stub institution labels (Institute/College/IIT).",
                }
            )
        if not cleaned and candidate_data.get("education"):
            findings.append(
                {
                    "section": "education",
                    "severity": "critical",
                    "issue": "Education is missing or invalid.",
                }
            )
        break
    return findings


def _repair_and_check_projects(
    doc: dict[str, Any],
    candidate_data: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    candidate_data = candidate_data or {}
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "project" not in title and stype != "projects":
            continue
        items = section.get("content") if isinstance(section.get("content"), list) else []
        cleaned = []
        mashed = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or item.get("company") or "").strip()
            name = restore_tech_names(name)
            if not name or re.match(r"(?i)^environment\s*:", name) or _is_gap_period(name, ""):
                continue
            # If name contains a second project glued on, split.
            extra_name = ""
            split = re.search(r"(?<=[.!?])\s+(?=[A-Z][A-Za-z0-9].{0,40}[–—\-])", name)
            if split:
                extra_name = name[split.start() :].strip()
                name = name[: split.start()].strip()
            bullets = [
                restore_tech_names(b)
                for b in expand_to_bullets(
                    [repair_collapsed_spaces(str(b)) for b in (item.get("description") or [])],
                    max_bullets=6,
                )
            ]
            # Split bullets that contain another project title.
            final_bullets = []
            pending_project = None
            for b in bullets:
                m = re.search(r"(?<=[.!?])\s+(?=[A-Z][A-Za-z0-9][^\n]{0,50}[–—\-])", b)
                if m:
                    final_bullets.append(b[: m.start()].strip())
                    pending_project = b[m.start() :].strip()
                elif _looks_mashed(b):
                    mashed += 1
                    final_bullets.append(repair_collapsed_spaces(b))
                else:
                    final_bullets.append(b)
            cleaned.append({**item, "name": name, "description": [x for x in final_bullets if x]})
            if extra_name or pending_project:
                new_name = extra_name or pending_project or ""
                # First sentence/chunk as name if needed.
                new_name = re.split(r"(?<=[.!?])\s+", new_name)[0].strip()
                if new_name and len(new_name) <= 120:
                    cleaned.append(
                        {
                            "name": restore_tech_names(new_name),
                            "description": [],
                            "technologies": [],
                            "link": "",
                            "duration": "",
                        }
                    )
                    mashed += 1
        if not cleaned and candidate_data.get("projects"):
            for src in candidate_data.get("projects") or []:
                if isinstance(src, dict) and src.get("name"):
                    cleaned.append(
                        {
                            "name": restore_tech_names(str(src.get("name"))),
                            "description": [
                                restore_tech_names(str(b))
                                for b in expand_to_bullets(src.get("description") or [], max_bullets=5)
                            ],
                            "technologies": list(src.get("technologies") or [])[:10],
                            "link": str(src.get("link") or ""),
                            "duration": str(src.get("duration") or ""),
                        }
                    )
            if cleaned:
                findings.append(
                    {
                        "section": "projects",
                        "severity": "warn",
                        "issue": "Restored projects from source after empty/mashed section.",
                    }
                )
        section["content"] = cleaned
        if mashed:
            findings.append(
                {
                    "section": "projects",
                    "severity": "warn",
                    "issue": "Split/repaired mashed project content.",
                }
            )
        break
    return findings


def _repair_and_check_certifications(
    doc: dict[str, Any],
    candidate_data: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    candidate_data = candidate_data or {}
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "certif" not in title and stype not in {"bullets", "certifications"}:
            continue
        if "achievement" in title or "award" in title:
            continue
        content = section.get("content")
        if not isinstance(content, list):
            continue
        cleaned: list[str] = []
        mashed = 0
        for raw in content:
            text = restore_tech_names(str(raw or "").strip())
            if not text:
                continue
            if re.search(r"(?i)\bleadership\b|\bachievements?\b|\bmentored\b|\bchampionship\b", text):
                mashed += 1
                text = re.split(
                    r"(?i)\b(?:leadership\s*&?\s*achievements?|leadership|achievements?|led\s+\d+)\b",
                    text,
                    maxsplit=1,
                )[0].strip(" |")
            if "|" in text and (len(text) > 40 or text.count("|") >= 1):
                mashed += 1
                parts = [restore_tech_names(p.strip()) for p in text.split("|") if len(p.strip()) > 3]
                cleaned.extend(parts)
            elif text:
                cleaned.append(text)
        # Dedupe
        seen = set()
        unique = []
        for c in cleaned:
            key = re.sub(r"[^a-z0-9]+", "", c.lower())
            if key in seen or len(key) < 6:
                continue
            seen.add(key)
            unique.append(c)
        if not unique and candidate_data.get("certifications"):
            unique = [restore_tech_names(str(c)) for c in candidate_data["certifications"] if str(c).strip()]
            findings.append(
                {
                    "section": "certifications",
                    "severity": "warn",
                    "issue": "Restored certifications from source.",
                }
            )
        section["content"] = unique
        if mashed:
            findings.append(
                {
                    "section": "certifications",
                    "severity": "critical" if len(unique) <= 1 and mashed else "warn",
                    "issue": "Certifications were mashed with leadership/other content; split into separate items.",
                }
            )
        break
    return findings


def _check_section_titles(doc: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    allowed = (
        "summary",
        "experience",
        "education",
        "skill",
        "project",
        "certif",
        "achievement",
        "language",
        "objective",
        "profile",
    )
    for section in doc.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        clean = title[:-1].strip() if title.endswith(":") else title
        low = clean.lower()
        if not clean:
            findings.append(
                {"section": "structure", "severity": "critical", "issue": "Empty section title found."}
            )
            continue
        if len(clean) > 40 or "," in clean:
            findings.append(
                {
                    "section": "structure",
                    "severity": "critical",
                    "issue": f"Invalid section title looks like body text: {clean[:60]}",
                }
            )
            continue
        if not any(token in low for token in allowed):
            findings.append(
                {
                    "section": "structure",
                    "severity": "critical",
                    "issue": f"Non-canonical section title: {clean}",
                }
            )
    return findings


def _merge_env_techs(role: dict[str, Any], payload: str) -> None:
    if not payload:
        return
    existing = role.setdefault("technologies", [])
    for tech in re.split(r"[,;|]+", payload):
        name = tech.strip()
        if not name or len(name) > 50 or len(name.split()) > 5:
            continue
        if name.casefold() not in {str(x).casefold() for x in existing}:
            existing.append(name)


def _is_gap_period(company: str, title: str) -> bool:
    blob = f"{company} {title}".strip().lower()
    return bool(re.search(r"\bgap\s*period\b", blob))
