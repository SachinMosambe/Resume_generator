"""
Multi-agent resume generation pipeline.

Agents share a blackboard (ResumeKB + FormatSpec + ContentPlan + Drafts) and
run under hard budgets so the create -> criticise -> refine loop stays timely:

  Orchestrator
    1. ExtractionAgent  — section-aware source parse into a fact-ID knowledge base
    2. FormatAgent      — target template into a FormatSpec (source format ignored)
    3. StrategistAgent  — length-aware content plan (scored selection + grounded condense)
    4. WriterAgent      — compose the document from selected facts
    5. CriticAgent      — deterministic checks (free) + one LLM rubric pass
    6. RefinerAgent     — repair only flagged sections, then back to the Critic

Enabled via RESUME_AGENT_PIPELINE=true; deploys inside the same FastAPI service.

Import of AgentResumeGenerationService is lazy so modules like format_validator can
import FormatSpec from app.agent_pipeline.state without circular imports through
resume_generation_service.
"""

from __future__ import annotations

from typing import Any

__all__ = ["AgentResumeGenerationService"]


def __getattr__(name: str) -> Any:
    if name == "AgentResumeGenerationService":
        from app.agent_pipeline.service import AgentResumeGenerationService

        return AgentResumeGenerationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
