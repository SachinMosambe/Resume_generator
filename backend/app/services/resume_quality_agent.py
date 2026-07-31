"""
Section Critique + Repair agents.

Efficient reflection loop:
  for each failed section (max 2 rounds):
    Critic → Repairer (grounded) → Critic again
Never rewrites the whole resume; only failed sections.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.agents.tools.llm_client import llm_call_json_with_metrics
from app.core.config import settings
from app.core.logging import logger
from app.services.resume_section_quality import (
    audit_and_repair_document,
    critical_findings,
    findings_as_feedback,
)
from app.services.tech_glossary import normalize_skill_token, restore_tech_names

_CRITIC_SYSTEM = """You are a strict resume QA critic for ONE section only.
Return JSON only. Do not invent facts. Flag only real defects.
Severity: critical = must fix before shipping; warn = optional.
"""

_REPAIR_SYSTEM = """You are a senior resume section editor.
Fix ONLY the given section using SOURCE FACTS. Never invent employers, schools, skills, dates, or metrics.
Return JSON only for the repaired section payload.
Keep tech names canonical (FastAPI, LangGraph, PostgreSQL, EC2, S3 — never Fast API / Lang Graph / EC 2).
"""


def run_section_quality_agents(
    document: dict[str, Any],
    candidate_data: dict[str, Any],
    *,
    max_rounds: int = 2,
    max_llm_calls: int = 5,
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    """
    Deterministic audit first, then targeted LLM critic/repair for remaining critical sections.
    """
    doc, findings = audit_and_repair_document(document, candidate_data)
    metrics = {"llm_calls": 0, "sections_repaired": [], "rounds": 0}

    if not bool(getattr(settings, "RESUME_LLM_CONDENSE", True)):
        return doc, findings, metrics

    for round_idx in range(max(1, max_rounds)):
        crits = critical_findings(findings)
        if not crits:
            break
        metrics["rounds"] = round_idx + 1
        # Group by section; repair worst sections first.
        sections_to_fix = _unique_sections(crits)
        for section_name in sections_to_fix:
            if metrics["llm_calls"] >= max_llm_calls:
                break
            source_facts = _source_facts_for_section(candidate_data, section_name)
            current_payload = _extract_section_payload(doc, section_name)
            if current_payload is None:
                continue

            # Critic pass (optional when deterministic already listed issues).
            issues = [f["issue"] for f in crits if f.get("section") == section_name]
            if metrics["llm_calls"] < max_llm_calls:
                critic = _critic_section(section_name, current_payload, source_facts, issues)
                metrics["llm_calls"] += 1
                if critic and critic.get("pass") is True and not critic.get("issues"):
                    continue
                if critic and isinstance(critic.get("issues"), list) and critic["issues"]:
                    issues = [str(x) for x in critic["issues"]][:8]

            if metrics["llm_calls"] >= max_llm_calls:
                break
            repaired_payload = _repair_section(section_name, current_payload, source_facts, issues)
            metrics["llm_calls"] += 1
            if not repaired_payload:
                continue
            doc = _apply_section_payload(doc, section_name, repaired_payload)
            metrics["sections_repaired"].append(section_name)

        # Re-audit after this round.
        doc, findings = audit_and_repair_document(doc, candidate_data)
        if metrics["llm_calls"] >= max_llm_calls:
            break

    logger.info(
        "resume_quality_agents_complete",
        llm_calls=metrics["llm_calls"],
        rounds=metrics["rounds"],
        repaired=metrics["sections_repaired"],
        critical_remaining=len(critical_findings(findings)),
        feedback=findings_as_feedback(critical_findings(findings))[:6],
    )
    return doc, findings, metrics


def _unique_sections(findings: list[dict[str, str]]) -> list[str]:
    order = ["header", "summary", "experience", "skills", "projects", "education", "certifications", "structure"]
    seen = set()
    out: list[str] = []
    names = [f.get("section") or "" for f in findings]
    for preferred in order:
        if preferred in names and preferred not in seen:
            out.append(preferred)
            seen.add(preferred)
    for name in names:
        if name and name not in seen:
            out.append(name)
            seen.add(name)
    return out


def _source_facts_for_section(candidate_data: dict[str, Any], section: str) -> dict[str, Any]:
    if section == "header":
        return {
            "name": candidate_data.get("name") or "",
            "email": candidate_data.get("email") or "",
            "phone": candidate_data.get("phone") or "",
            "location": candidate_data.get("location") or "",
        }
    if section == "summary":
        return {"summary": str(candidate_data.get("summary") or "")[:2500]}
    if section == "experience":
        roles = []
        for r in candidate_data.get("experience") or []:
            if not isinstance(r, dict):
                continue
            roles.append(
                {
                    "company": r.get("company") or "",
                    "title": r.get("title") or "",
                    "duration": r.get("duration") or "",
                    "location": r.get("location") or "",
                    "description": list(r.get("description") or [])[:10],
                    "technologies": list(r.get("technologies") or [])[:12],
                }
            )
        return {"experience": roles[:14]}
    if section == "skills":
        return {
            "skills_by_category": candidate_data.get("skills_by_category") or {},
            "skills": list(candidate_data.get("skills") or [])[:80],
        }
    if section == "education":
        return {"education": candidate_data.get("education") or []}
    if section == "projects":
        return {"projects": candidate_data.get("projects") or []}
    if section == "certifications":
        return {
            "certifications": candidate_data.get("certifications") or [],
            "achievements": candidate_data.get("achievements") or [],
        }
    return {}


def _extract_section_payload(doc: dict[str, Any], section: str) -> Any:
    if section == "header":
        return doc.get("header") or {}
    for sec in doc.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").lower()
        stype = str(sec.get("type") or "").lower()
        if section == "summary" and ("summary" in title or "objective" in title or "profile" in title):
            return {"title": sec.get("title"), "content": sec.get("content")}
        if section == "experience" and ("experience" in title or stype == "experience"):
            return {"title": sec.get("title"), "content": sec.get("content")}
        if section == "skills" and ("skill" in title or stype in {"skills", "skill"}):
            return {"title": sec.get("title"), "content": sec.get("content")}
        if section == "education" and ("education" in title or stype == "education"):
            return {"title": sec.get("title"), "content": sec.get("content")}
        if section == "projects" and ("project" in title or stype == "projects"):
            return {"title": sec.get("title"), "content": sec.get("content")}
        if section == "certifications" and ("certif" in title or "achievement" in title):
            return {"title": sec.get("title"), "content": sec.get("content")}
    return None


def _apply_section_payload(doc: dict[str, Any], section: str, payload: Any) -> dict[str, Any]:
    import copy

    out = copy.deepcopy(doc)
    if section == "header" and isinstance(payload, dict):
        header = out.setdefault("header", {})
        if payload.get("name"):
            header["name"] = str(payload["name"]).strip()
        if payload.get("role") not in (None, ""):
            header["role"] = str(payload["role"]).strip()
        # Client policy: never keep personal contact details on the resume.
        header["contact"] = []
        out["header"] = header
        return out

    for sec in out.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").lower()
        stype = str(sec.get("type") or "").lower()
        match = False
        if section == "summary" and ("summary" in title or "objective" in title):
            match = True
        elif section == "experience" and ("experience" in title or stype == "experience"):
            match = True
        elif section == "skills" and ("skill" in title or stype in {"skills", "skill"}):
            match = True
        elif section == "education" and ("education" in title or stype == "education"):
            match = True
        elif section == "projects" and ("project" in title or stype == "projects"):
            match = True
        elif section == "certifications" and ("certif" in title or "achievement" in title):
            match = True
        if not match:
            continue
        content = payload.get("content") if isinstance(payload, dict) else payload
        if section == "summary" and isinstance(content, str):
            sec["content"] = restore_tech_names(content)
        elif section == "skills" and isinstance(content, dict):
            sec["content"] = {
                str(k): [normalize_skill_token(v) for v in (vals or []) if str(v).strip()][:16]
                for k, vals in content.items()
                if str(k).strip()
            }
        elif section in {"experience", "projects", "education"} and isinstance(content, list):
            cleaned = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                clone = dict(item)
                for key in ("description", "details"):
                    if isinstance(clone.get(key), list):
                        clone[key] = [restore_tech_names(str(b)) for b in clone[key] if str(b).strip()]
                for key in ("title", "company", "name", "degree", "institution"):
                    if clone.get(key):
                        clone[key] = restore_tech_names(str(clone[key]))
                cleaned.append(clone)
            sec["content"] = cleaned
        elif section == "certifications" and isinstance(content, list):
            sec["content"] = [restore_tech_names(str(x)) for x in content if str(x).strip()]
        if isinstance(payload, dict) and payload.get("title"):
            sec["title"] = str(payload["title"])
        break
    return out


def _critic_section(
    section: str,
    payload: Any,
    source_facts: dict[str, Any],
    known_issues: list[str],
) -> dict[str, Any] | None:
    try:
        user = "\n".join(
            [
                f"Section: {section}",
                f"Known issues: {json.dumps(known_issues[:8], ensure_ascii=True)}",
                "SOURCE FACTS:",
                json.dumps(source_facts, ensure_ascii=True)[:12000],
                "CURRENT SECTION:",
                json.dumps(payload, ensure_ascii=True)[:12000],
                'Return JSON: {"pass": true|false, "issues": ["..."]}',
            ]
        )
        result = llm_call_json_with_metrics(
            _CRITIC_SYSTEM,
            user,
            validate=lambda d: [] if isinstance(d, dict) and "pass" in d else ["pass required"],
            repair_attempts=0,
            validation_attempts=1,
            max_tokens=1024,
        )
        return result.data if isinstance(result.data, dict) else None
    except Exception as exc:
        logger.warning("resume_section_critic_failed", section=section, error=str(exc))
        return None


def _repair_section(
    section: str,
    payload: Any,
    source_facts: dict[str, Any],
    issues: list[str],
) -> dict[str, Any] | None:
    try:
        schema_hint = {
            "header": {"name": "string", "role": "string", "contact": []},
            "summary": {"title": "PROFESSIONAL SUMMARY:", "content": "string"},
            "experience": {
                "title": "PROFESSIONAL EXPERIENCE:",
                "content": [
                    {
                        "company": "",
                        "title": "",
                        "duration": "",
                        "location": "",
                        "description": ["bullet"],
                        "technologies": [],
                    }
                ],
            },
            "skills": {"title": "TECHNICAL SKILLS:", "content": {"Category": ["skill"]}},
            "education": {
                "title": "EDUCATION:",
                "content": [{"degree": "", "institution": "", "year": ""}],
            },
            "projects": {
                "title": "PROJECTS:",
                "content": [{"name": "", "description": ["bullet"], "technologies": []}],
            },
            "certifications": {"title": "CERTIFICATIONS:", "content": ["cert name"]},
        }.get(section, {"content": payload})

        user = "\n".join(
            [
                f"Repair section: {section}",
                f"Issues to fix: {json.dumps(issues[:10], ensure_ascii=True)}",
                "SOURCE FACTS (only use these):",
                json.dumps(source_facts, ensure_ascii=True)[:14000],
                "CURRENT SECTION:",
                json.dumps(payload, ensure_ascii=True)[:12000],
                "Return repaired section JSON matching:",
                json.dumps(schema_hint, ensure_ascii=True),
            ]
        )
        result = llm_call_json_with_metrics(
            _REPAIR_SYSTEM,
            user,
            validate=lambda d: [] if isinstance(d, dict) else ["object required"],
            repair_attempts=1,
            validation_attempts=1,
            max_tokens=min(4096, max(settings.RESUME_GENERATION_MAX_TOKENS // 2, 2048)),
        )
        return result.data if isinstance(result.data, dict) else None
    except Exception as exc:
        logger.warning("resume_section_repair_failed", section=section, error=str(exc))
        return None
