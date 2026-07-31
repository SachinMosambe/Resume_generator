"""
Shared blackboard state for the multi-agent pipeline.

Every agent reads/writes these structures; nothing else is shared. All state is
per-request (no globals), so the pipeline scales horizontally like the rest of
the FastAPI app.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings


@dataclass
class Budgets:
    """Hard limits that keep the create->critique->refine loop timely."""

    max_rounds: int = 2
    max_llm_calls: int = 8
    time_budget_s: float = 90.0
    llm_enabled: bool = True
    started: float = field(default_factory=time.monotonic)
    llm_calls: int = 0

    @classmethod
    def from_settings(cls) -> "Budgets":
        return cls(
            max_rounds=int(getattr(settings, "AGENT_MAX_ROUNDS", 2) or 2),
            max_llm_calls=int(getattr(settings, "AGENT_MAX_LLM_CALLS", 8) or 8),
            time_budget_s=float(getattr(settings, "AGENT_TIME_BUDGET_SECONDS", 90) or 90),
            llm_enabled=bool(getattr(settings, "RESUME_LLM_CONDENSE", True)),
        )

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def time_left(self) -> float:
        return self.time_budget_s - self.elapsed()

    def expired(self) -> bool:
        return self.time_left() <= 0

    def allow_llm(self, *, min_time_left_s: float = 10.0) -> bool:
        """True when another LLM call fits inside both call and time budgets."""
        return (
            self.llm_enabled
            and self.llm_calls < self.max_llm_calls
            and self.time_left() > min_time_left_s
        )

    def spend_llm(self, count: int = 1) -> None:
        self.llm_calls += count


@dataclass
class Fact:
    """One grounded atom from the source resume (bullet, skill, degree, ...)."""

    id: str
    section: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


_NORM_RE = re.compile(r"[^a-z0-9]+")


def norm_text(value: Any) -> str:
    return _NORM_RE.sub("", str(value or "").lower())


@dataclass
class ResumeKB:
    """
    Fact-ID knowledge base built from the full structured store.

    The store keeps the canonical section shapes (used for composition);
    the facts index + grounding blob make hallucination checks a cheap lookup.
    """

    store: dict[str, Any]
    facts: dict[str, Fact] = field(default_factory=dict)
    grounding_blob: str = ""

    @property
    def header(self) -> dict[str, Any]:
        return self.store.get("header") or {}

    def add_fact(self, fact_id: str, section: str, text: str, **meta: Any) -> None:
        text = str(text or "").strip()
        if not text:
            return
        self.facts[fact_id] = Fact(id=fact_id, section=section, text=text, meta=meta)

    def facts_for(self, section: str) -> list[Fact]:
        return [f for f in self.facts.values() if f.section == section]

    def role_identities(self) -> list[tuple[str, str, str]]:
        """(company, title, duration) for every role — never removal candidates."""
        out: list[tuple[str, str, str]] = []
        for role in self.store.get("experience") or []:
            if isinstance(role, dict):
                out.append(
                    (
                        str(role.get("company") or ""),
                        str(role.get("title") or ""),
                        str(role.get("duration") or ""),
                    )
                )
        return out

    def build_grounding_blob(self) -> None:
        parts = [f.text.lower() for f in self.facts.values()]
        header = self.header
        parts.extend(str(v).lower() for v in header.values() if v)
        self.grounding_blob = " ".join(parts)


@dataclass
class FormatSpec:
    """Layout contract from the target template. Source resume format is ignored."""

    metadata: dict[str, Any]
    section_order: list[str]
    labels: dict[str, str]
    target_pages: float

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> "FormatSpec":
        from app.models.format_schema import normalize_format_metadata

        metadata = normalize_format_metadata(metadata)
        order = [
            s
            for s in (metadata.get("section_order") or metadata.get("sections") or [])
            if str(s).strip() and str(s).lower() != "header"
        ]
        if not order:
            order = [
                "summary",
                "skills",
                "experience",
                "projects",
                "education",
                "certifications",
                "achievements",
                "languages",
            ]
        labels = metadata.get("section_labels") or metadata.get("field_mapping") or {}
        return cls(
            metadata=metadata,
            section_order=[str(s).lower() for s in order],
            labels={str(k).lower(): str(v) for k, v in dict(labels).items()},
            target_pages=float(getattr(settings, "RESUME_TARGET_PAGES", 3.5) or 3.5),
        )


@dataclass
class ContentPlan:
    """Which facts the Writer may use, already sized for the page target."""

    render_store: dict[str, Any]
    pages_before: float
    pages_after: float
    fitted: bool = False
    llm_condensed: bool = False
    selected_fact_ids: list[str] = field(default_factory=list)


@dataclass
class Draft:
    """One composed document version with its critique."""

    document: dict[str, Any]
    score: float
    findings: list[dict[str, str]] = field(default_factory=list)
    round_idx: int = 0
    label: str = "draft"


@dataclass
class PipelineState:
    """Blackboard passed between agents for a single request."""

    candidate_data: dict[str, Any]
    budgets: Budgets
    kb: ResumeKB | None = None
    spec: FormatSpec | None = None
    plan: ContentPlan | None = None
    drafts: list[Draft] = field(default_factory=list)

    @property
    def best(self) -> Draft | None:
        if not self.drafts:
            return None
        return max(self.drafts, key=lambda d: d.score)
