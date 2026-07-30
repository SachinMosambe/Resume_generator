"""
Writer Agent — compose the document from the content plan.

Grounded by construction: the document is built deterministically from the
selected facts in the render store (any LLM wording work already happened in
the Strategist's grounded condense pass).
"""
from __future__ import annotations

from typing import Any

from app.agents.resume_generation_agent import normalize_resume_document
from app.core.logging import logger
from app.services.structured_resume_store import document_from_store

from app.agent_pipeline.state import ContentPlan, FormatSpec


def compose(
    plan: ContentPlan,
    spec: FormatSpec,
    candidate_data: dict[str, Any],
) -> dict[str, Any]:
    document = document_from_store(plan.render_store, spec.metadata)
    document = normalize_resume_document(document, candidate_data)
    document["client_name"] = candidate_data.get("client_name", "")
    logger.info(
        "agent_writer_composed",
        sections=len(document.get("sections") or []),
        fitted=plan.fitted,
        llm_condensed=plan.llm_condensed,
    )
    return document
