"""
Flag-gated entry point for the multi-agent pipeline.

Subclasses ResumeGenerationService and swaps only the document-generation
stage, so branding, logo handling, DOCX rendering, upload, and the deploy
shape (same FastAPI app / Dockerfile / render.yaml) are all unchanged.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.services.resume_generation_service import ResumeGenerationService
from app.services.resume_section_quality import audit_and_repair_document, critical_findings
from app.services.structured_resume_store import apply_store_to_candidate_data


class AgentResumeGenerationService(ResumeGenerationService):
    """Same public contract as ResumeGenerationService; agent loop inside."""

    def _generate_professional_document(
        self,
        candidate_data: dict[str, Any],
        format_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from app.agent_pipeline.orchestrator import run_pipeline

        metadata = self._metadata_for_generation(format_metadata or {})
        document, state = run_pipeline(candidate_data, metadata)

        # Sync candidate_data with the selected content so downstream
        # reliability enforcement sees the same ground truth as the agents.
        if state.plan is not None:
            candidate_data = apply_store_to_candidate_data(candidate_data, state.plan.render_store)
            if isinstance(candidate_data.get("extracted_data"), dict) and state.kb is not None:
                candidate_data["extracted_data"] = {
                    **candidate_data["extracted_data"],
                    "structured_resume": state.kb.store,
                    "structured_resume_render": state.plan.render_store,
                }

        # Final safety net — identical guarantees to the classic pipeline.
        document = self._enforce_document_reliability(document, candidate_data, metadata)
        document, findings = audit_and_repair_document(document, candidate_data)
        document = self._enforce_document_reliability(document, candidate_data, metadata)
        document["client_name"] = candidate_data.get("client_name", "")

        remaining = critical_findings(findings)
        if remaining:
            logger.warning(
                "agent_pipeline_remaining_critical",
                count=len(remaining),
                issues=[f"{f['section']}:{f['issue']}" for f in remaining[:6]],
            )
        return document
