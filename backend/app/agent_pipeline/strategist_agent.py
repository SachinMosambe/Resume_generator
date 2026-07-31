"""
Content Strategist — length-aware content plan.

Short resumes pass through untouched. Long careers use light trim only
(keep nearly all bullets). Medium oversized resumes use scored selection.
Never LLM-compress length — that collapses long resumes to ~2 pages.
"""
from __future__ import annotations

from app.core.logging import logger
from app.services.structured_resume_store import is_large_resume
from app.services.resume_page_fitter import (
    estimate_pages,
    fit_store_to_pages,
    light_trim_store,
    needs_page_fit,
    resolve_target_pages,
)

from app.agent_pipeline.state import Budgets, ContentPlan, FormatSpec, ResumeKB, norm_text


def plan_content(kb: ResumeKB, spec: FormatSpec, budgets: Budgets) -> ContentPlan:
    full_store = kb.store
    pages_before = estimate_pages(full_store)
    target = resolve_target_pages(pages_before, spec.target_pages)
    _ = budgets

    if is_large_resume(full_store):
        fitted = light_trim_store(full_store)
        plan = ContentPlan(
            render_store=fitted,
            pages_before=pages_before,
            pages_after=estimate_pages(fitted),
            fitted=False,
            llm_condensed=False,
        )
        plan.selected_fact_ids = list(kb.facts.keys())
        logger.info(
            "agent_plan_keep_dense",
            pages_before=round(pages_before, 2),
            pages_after=round(plan.pages_after, 2),
            target=target,
        )
        return plan

    if not needs_page_fit(full_store, target_pages=target):
        plan = ContentPlan(
            render_store=full_store,
            pages_before=pages_before,
            pages_after=pages_before,
        )
        plan.selected_fact_ids = list(kb.facts.keys())
        logger.info("agent_plan_keep_all", pages=round(pages_before, 2), target=target)
        return plan

    fitted = fit_store_to_pages(full_store, target_pages=target)
    plan = ContentPlan(
        render_store=fitted,
        pages_before=pages_before,
        pages_after=estimate_pages(fitted),
        fitted=True,
        llm_condensed=False,
    )
    plan.selected_fact_ids = _trace_selected_facts(kb, fitted)
    logger.info(
        "agent_plan_fitted",
        pages_before=round(plan.pages_before, 2),
        pages_after=round(plan.pages_after, 2),
        target=target,
        llm_condensed=False,
        roles_kept=len(fitted.get("experience") or []),
        facts_selected=len(plan.selected_fact_ids),
    )
    return plan


def _trace_selected_facts(kb: ResumeKB, render_store: dict) -> list[str]:
    """Map surviving content back to KB fact IDs (traceability for the Critic)."""
    surviving = {
        norm_text(b)[:60]
        for role in render_store.get("experience") or []
        if isinstance(role, dict)
        for b in role.get("description") or []
    }
    selected: list[str] = []
    for fact in kb.facts.values():
        if fact.section != "experience" or fact.meta.get("kind") != "bullet":
            selected.append(fact.id)
            continue
        key = norm_text(fact.text)[:60]
        if any(key and (key in s or s in key) for s in surviving if s):
            selected.append(fact.id)
    return selected
