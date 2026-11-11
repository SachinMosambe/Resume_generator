from __future__ import annotations

from dataclasses import dataclass, field
import re


_EXP_HEAD = re.compile(
    r"(?im)^(professional\s+)?(experience|work history|employment|job history)\b"
)
_JOBISH = re.compile(
    r"(?i)\b(20\d{2}|present)\b|\([^)]{3,60}\)\s*\d{1,2}/\d{2,4}|\b(inc|llc|corp|ltd)\b"
)


@dataclass
class EmploymentEvidence:
    has_work_history: bool
    reasons: list[str] = field(default_factory=list)
    snippet_refs: list[str] = field(default_factory=list)


def detect_employment_evidence(source_text: str) -> EmploymentEvidence:
    lines = (source_text or "").splitlines()
    refs: list[str] = []
    reasons: list[str] = []
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if _EXP_HEAD.match(line):
            refs.append(f"line:{i}")
            reasons.append("experience_heading")
        elif line.startswith(("•", "-", "*")) and _JOBISH.search(line):
            refs.append(f"line:{i}")
            reasons.append("dated_or_employerish_bullet")
        elif _JOBISH.search(line) and len(line) < 120:
            refs.append(f"line:{i}")
            reasons.append("jobish_line")

    has = (
        "experience_heading" in reasons and len(refs) >= 2
    ) or reasons.count("dated_or_employerish_bullet") >= 3
    return EmploymentEvidence(
        has_work_history=has,
        reasons=sorted(set(reasons)),
        snippet_refs=refs[:20],
    )
