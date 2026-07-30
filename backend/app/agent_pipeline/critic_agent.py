"""
Critic Agent — score a draft and produce section-targeted fix instructions.

Three of four rubric dimensions are free deterministic checks (grounding via
the KB blob, completeness vs role identities, format/length vs the FormatSpec).
Only writing quality needs an LLM call, and only when the budget allows.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.tools.llm_client import llm_call_json_with_metrics
from app.core.logging import logger
from app.services.resume_llm_condense import _bullet_grounded
from app.services.resume_section_quality import audit_and_repair_document

from app.agent_pipeline.state import Budgets, FormatSpec, ResumeKB, norm_text

_CHARS_PER_PAGE = 3200

_RUBRIC_SYSTEM = """You are a strict resume writing-quality judge. Return ONLY valid JSON.
Judge wording quality only: clarity, action verbs, mashed/jammed text, tone, bullet crispness.
Do NOT judge facts (they are verified separately). Do NOT suggest adding new content.
"""


@dataclass
class CriticReport:
    document: dict[str, Any]
    score: float
    findings: list[dict[str, str]] = field(default_factory=list)
    llm_used: bool = False


def review(
    document: dict[str, Any],
    kb: ResumeKB,
    spec: FormatSpec,
    candidate_data: dict[str, Any],
    budgets: Budgets,
    *,
    use_llm_rubric: bool = True,
) -> CriticReport:
    # Deterministic section audit applies safe repairs and reports findings.
    doc, findings = audit_and_repair_document(document, candidate_data)

    findings.extend(_check_grounding(doc, kb))
    findings.extend(_check_completeness(doc, kb))
    findings.extend(_check_length(doc, spec))

    score = _deterministic_score(findings)
    llm_used = False

    # LLM rubric only when the draft is worth polishing and budget remains.
    if use_llm_rubric and score >= 55 and budgets.allow_llm(min_time_left_s=15.0):
        rubric = _llm_rubric(doc, budgets)
        if rubric is not None:
            llm_used = True
            writing_score = float(rubric.get("writing_score") or 70)
            for issue in rubric.get("issues") or []:
                if isinstance(issue, dict) and issue.get("issue"):
                    findings.append(
                        {
                            "section": str(issue.get("section") or "resume"),
                            "severity": "critical"
                            if str(issue.get("severity")) == "critical"
                            else "warn",
                            "issue": str(issue["issue"])[:200],
                        }
                    )
            score = round(0.7 * _deterministic_score(findings) + 0.3 * writing_score, 1)

    logger.info(
        "agent_critic_review",
        score=score,
        critical=sum(1 for f in findings if f.get("severity") == "critical"),
        warnings=sum(1 for f in findings if f.get("severity") == "warn"),
        llm_rubric=llm_used,
    )
    return CriticReport(document=doc, score=score, findings=findings, llm_used=llm_used)


def _deterministic_score(findings: list[dict[str, str]]) -> float:
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    warn = sum(1 for f in findings if f.get("severity") == "warn")
    return max(0.0, 100.0 - 12.0 * critical - 2.0 * warn)


def _experience_sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        stype = str(section.get("type") or "").lower()
        if "experience" in title or stype == "experience":
            out.append(section)
    return out


def _check_grounding(document: dict[str, Any], kb: ResumeKB) -> list[dict[str, str]]:
    """Every experience bullet must trace to KB facts — cheap lookup, no LLM."""
    findings: list[dict[str, str]] = []
    src_bullets = [f.text for f in kb.facts.values() if f.meta.get("kind") == "bullet"]
    total = 0
    ungrounded = 0
    for section in _experience_sections(document):
        for role in section.get("content") or []:
            if not isinstance(role, dict):
                continue
            for bullet in role.get("description") or []:
                total += 1
                if not _bullet_grounded(str(bullet), kb.grounding_blob, src_bullets):
                    ungrounded += 1
    if total and ungrounded:
        ratio = ungrounded / total
        findings.append(
            {
                "section": "experience",
                "severity": "critical" if ratio > 0.15 else "warn",
                "issue": f"{ungrounded}/{total} bullets not grounded in source facts",
            }
        )
    return findings


def _check_completeness(document: dict[str, Any], kb: ResumeKB) -> list[dict[str, str]]:
    """All source role identities must appear — employers are never dropped."""
    findings: list[dict[str, str]] = []
    doc_companies: set[str] = set()
    for section in _experience_sections(document):
        for role in section.get("content") or []:
            if isinstance(role, dict):
                doc_companies.add(norm_text(role.get("company")))

    missing = []
    for company, title, duration in kb.role_identities():
        key = norm_text(company)
        if not key:
            continue
        if key not in doc_companies and not any(key in d or d in key for d in doc_companies if d):
            missing.append(company or title or duration)
    for name in missing[:5]:
        findings.append(
            {
                "section": "experience",
                "severity": "critical",
                "issue": f"source role missing from output: {name}",
            }
        )
    return findings


def _check_length(document: dict[str, Any], spec: FormatSpec) -> list[dict[str, str]]:
    chars = len(json.dumps(document, ensure_ascii=True))
    # JSON overhead roughly cancels layout overhead; close enough for a gate.
    pages = chars / _CHARS_PER_PAGE
    if pages > spec.target_pages + 1.0:
        return [
            {
                "section": "structure",
                "severity": "warn",
                "issue": f"estimated {pages:.1f} pages vs target {spec.target_pages}",
            }
        ]
    return []


def _document_text_sample(document: dict[str, Any], limit: int = 9000) -> str:
    parts: list[str] = []
    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        parts.append(str(section.get("title") or ""))
        content = section.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    parts.extend(str(b) for b in (item.get("description") or []))
                else:
                    parts.append(str(item))
    text = "\n".join(p for p in parts if p)
    return text[:limit]


def _llm_rubric(document: dict[str, Any], budgets: Budgets) -> dict[str, Any] | None:
    try:
        result = llm_call_json_with_metrics(
            _RUBRIC_SYSTEM,
            "\n".join(
                [
                    "Rate the writing quality of this resume draft (0-100) and list wording defects.",
                    'Return JSON: {"writing_score": 0, "issues":'
                    ' [{"section": "summary|experience|skills|education|projects|certifications",'
                    ' "severity": "critical|warn", "issue": "..."}]}',
                    "",
                    "DRAFT:",
                    _document_text_sample(document),
                ]
            ),
            validate=lambda d: []
            if isinstance(d, dict) and "writing_score" in d
            else ["writing_score required"],
            repair_attempts=0,
            validation_attempts=1,
            max_tokens=1024,
        )
        budgets.spend_llm()
        data = result.data
        score = data.get("writing_score")
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            data["writing_score"] = 70
        return data
    except Exception as exc:
        budgets.spend_llm()
        logger.warning("agent_critic_rubric_failed", error=str(exc))
        return None
