"""
Format Agent — target template metadata into a FormatSpec.

The template contributes layout only (section order, labels, branding lives in
the render step); candidate body content never comes from the template, and the
source resume's own format is ignored entirely.
"""
from __future__ import annotations

from typing import Any

from app.core.logging import logger

from app.agent_pipeline.state import FormatSpec


def build_format_spec(format_metadata: dict[str, Any] | None) -> FormatSpec:
    spec = FormatSpec.from_metadata(format_metadata)
    logger.info(
        "agent_format_spec_built",
        sections=spec.section_order,
        labels=len(spec.labels),
        target_pages=spec.target_pages,
    )
    return spec
