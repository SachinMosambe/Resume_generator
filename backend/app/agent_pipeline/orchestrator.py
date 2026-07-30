"""
Orchestrator — runs the agent loop under hard budgets and keeps the best draft.

Flow:
  ExtractionAgent -> FormatAgent -> StrategistAgent -> WriterAgent
  -> [CriticAgent -> RefinerAgent] x max_rounds (early exit on score threshold)

Guarantees:
- Every draft is scored and kept; the loop can never ship worse than the best seen.
- Wall-clock budget: on expiry the best draft so far ships — never a failure.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import logger

from app.agent_pipeline import (
    critic_agent,
    extraction_agent,
    format_agent,
    refiner_agent,
    strategist_agent,
    writer_agent,
)
from app.agent_pipeline.state import Budgets, Draft, PipelineState


def run_pipeline(
    candidate_data: dict[str, Any],
    format_metadata: dict[str, Any] | None,
) -> tuple[dict[str, Any], PipelineState]:
    """Return (best document, final blackboard state)."""
    state = PipelineState(candidate_data=candidate_data, budgets=Budgets.from_settings())
    threshold = float(getattr(settings, "AGENT_SCORE_THRESHOLD", 85.0) or 85.0)

    state.kb = extraction_agent.build_kb(candidate_data, state.budgets)
    state.spec = format_agent.build_format_spec(format_metadata)
    state.plan = strategist_agent.plan_content(state.kb, state.spec, state.budgets)

    document = writer_agent.compose(state.plan, state.spec, candidate_data)

    for round_idx in range(max(1, state.budgets.max_rounds)):
        report = critic_agent.review(
            document,
            state.kb,
            state.spec,
            candidate_data,
            state.budgets,
            use_llm_rubric=round_idx == 0 or state.budgets.allow_llm(),
        )
        document = report.document  # deterministic repairs already applied
        state.drafts.append(
            Draft(
                document=document,
                score=report.score,
                findings=report.findings,
                round_idx=round_idx,
                label=f"round{round_idx}",
            )
        )

        has_critical = any(f.get("severity") == "critical" for f in report.findings)
        if report.score >= threshold and not has_critical:
            logger.info("agent_loop_early_exit", round=round_idx, score=report.score)
            break
        if state.budgets.expired() or not state.budgets.allow_llm():
            logger.info(
                "agent_loop_budget_exhausted",
                round=round_idx,
                elapsed_s=round(state.budgets.elapsed(), 1),
                llm_calls=state.budgets.llm_calls,
            )
            break
        if round_idx + 1 >= state.budgets.max_rounds:
            break

        document, repaired = refiner_agent.refine(
            document, report.findings, candidate_data, state.budgets
        )
        if not repaired:
            logger.info("agent_loop_no_repairs_possible", round=round_idx)
            break

    best = state.best
    assert best is not None  # at least one draft is always appended
    logger.info(
        "agent_pipeline_complete",
        rounds=len(state.drafts),
        best_score=best.score,
        best_round=best.round_idx,
        llm_calls=state.budgets.llm_calls,
        elapsed_s=round(state.budgets.elapsed(), 1),
        pages_before=round(state.plan.pages_before, 2),
        pages_after=round(state.plan.pages_after, 2),
    )
    return best.document, state
