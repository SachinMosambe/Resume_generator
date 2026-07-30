"""
Refiner Agent — repair only the sections the Critic flagged.

Reuses the proven section repairer (grounded on source facts, tech-glossary
normalization on apply). Never rewrites the whole document, so round two of
the loop is cheap and convergent.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.services.resume_quality_agent import (
    _apply_section_payload,
    _extract_section_payload,
    _repair_section,
    _source_facts_for_section,
    _unique_sections,
)
from app.services.resume_section_quality import critical_findings

from app.agent_pipeline.state import Budgets

_MAX_SECTIONS_PER_ROUND = 4


def refine(
    document: dict[str, Any],
    findings: list[dict[str, str]],
    candidate_data: dict[str, Any],
    budgets: Budgets,
) -> tuple[dict[str, Any], list[str]]:
    """Return (document, sections_repaired). LLM cost: one call per failed section."""
    crits = critical_findings(findings)
    if not crits:
        return document, []

    doc = document
    repaired: list[str] = []
    for section_name in _unique_sections(crits)[:_MAX_SECTIONS_PER_ROUND]:
        if not budgets.allow_llm(min_time_left_s=12.0):
            logger.info("agent_refiner_budget_stop", repaired=repaired)
            break
        current_payload = _extract_section_payload(doc, section_name)
        if current_payload is None:
            continue
        issues = [f["issue"] for f in crits if f.get("section") == section_name][:8]
        source_facts = _source_facts_for_section(candidate_data, section_name)
        payload = _repair_section(section_name, current_payload, source_facts, issues)
        budgets.spend_llm()
        if not payload:
            continue
        doc = _apply_section_payload(doc, section_name, payload)
        repaired.append(section_name)

    logger.info("agent_refiner_complete", sections_repaired=repaired, llm_calls=budgets.llm_calls)
    return doc, repaired
