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
"""

from app.agent_pipeline.service import AgentResumeGenerationService

__all__ = ["AgentResumeGenerationService"]
