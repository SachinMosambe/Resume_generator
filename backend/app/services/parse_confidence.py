"""Parse confidence scored against independent source evidence (no resume text is logged)."""
from __future__ import annotations

from typing import Any

from app.services.source_evidence import detect_employment_evidence

_TECH_NAMES = {"react native", "react native."}


def score_parse(data: dict[str, Any], source_text: str) -> dict[str, Any]:
    evidence = detect_employment_evidence(source_text)
    roles = [r for r in (data.get("experience") or []) if isinstance(r, dict)]
    unassigned = data.get("unassigned_experience_bullets") or []
    reasons: list[str] = []
    empty_titles = sum(1 for r in roles if not (r.get("title") or "").strip())
    name = (data.get("name") or "").strip()
    confidence = 1.0
    if evidence.has_work_history and not roles and not unassigned:
        reasons.append("expected_experience_missing")
        confidence -= 0.5
    elif evidence.has_work_history and not roles:
        reasons.append("ambiguous_role_assignment")
        confidence -= 0.35
    if roles and empty_titles / max(1, len(roles)) >= 0.5:
        reasons.append("source_backed_titles_unresolved")
        confidence -= 0.25
    if not name or name.lower() in _TECH_NAMES:
        reasons.append("identity_ambiguous")
        confidence -= 0.2
    confidence = max(0.0, min(1.0, confidence))
    return {
        "confidence": confidence,
        "reasons": reasons,
        "llm_repaired": False,
        "employment_evidence": {
            "has_work_history": evidence.has_work_history,
            "reasons": evidence.reasons,
        },
    }
