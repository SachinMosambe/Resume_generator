"""Phase 4: immutable accepted canonical resume + template contracts.

Formatting the same accepted resume into another template must not require
reparsing with Gemma.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings

CANONICAL_SCHEMA_VERSION = 1
TEMPLATE_CONTRACT_VERSION = "template_contract@1"

# Supported built-in template contracts (static content vs candidate content).
TEMPLATE_CONTRACTS: dict[str, dict[str, Any]] = {
    "aptino": {
        "version": "aptino@1",
        "supported_sections": [
            "summary",
            "skills",
            "experience",
            "projects",
            "education",
            "certifications",
            "achievements",
            "languages",
        ],
        "repeatable_blocks": ["experience", "projects", "education"],
        "numbering": "bullets",
        "headers_footers": {"candidate_contact": False, "company_branding": True},
        "pagination": {"overflow": "continue_pages", "force_source_page_count": False},
        "unsupported_sections": {"action": "additional_or_review"},
        "static_vs_candidate": {
            "static": ["company_footer", "logos"],
            "candidate": ["header.name", "sections"],
        },
    },
    "capgemini": {
        "version": "capgemini@1",
        "supported_sections": [
            "summary",
            "skills",
            "experience",
            "projects",
            "education",
            "certifications",
        ],
        "repeatable_blocks": ["experience", "projects", "education"],
        "numbering": "bullets",
        "headers_footers": {"candidate_contact": False, "company_branding": True},
        "pagination": {"overflow": "continue_pages", "force_source_page_count": False},
        "unsupported_sections": {"action": "additional_or_review"},
        "static_vs_candidate": {
            "static": ["company_footer", "logos"],
            "candidate": ["header.name", "sections"],
        },
    },
    "suresh": {
        "version": "suresh@1",
        "supported_sections": [
            "summary",
            "skills",
            "experience",
            "education",
            "certifications",
        ],
        "repeatable_blocks": ["experience", "education"],
        "numbering": "bullets",
        "headers_footers": {"candidate_contact": False, "company_branding": True},
        "pagination": {"overflow": "continue_pages", "force_source_page_count": False},
        "unsupported_sections": {"action": "additional_or_review"},
        "static_vs_candidate": {
            "static": ["company_footer"],
            "candidate": ["header.name", "sections"],
        },
    },
}


@dataclass
class CanonicalResume:
    revision: str
    schema_version: int
    source_revision: str
    store: dict[str, Any]
    unresolved_issues: list[dict[str, Any]] = field(default_factory=list)
    human_corrections: list[dict[str, Any]] = field(default_factory=list)
    ordering: list[str] = field(default_factory=list)
    created_at: float = 0.0
    prompt_version: str = ""
    parser_version: str = "structured_resume_store@1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalResume:
        return cls(
            revision=str(data.get("revision") or ""),
            schema_version=int(data.get("schema_version") or CANONICAL_SCHEMA_VERSION),
            source_revision=str(data.get("source_revision") or ""),
            store=dict(data.get("store") or {}),
            unresolved_issues=list(data.get("unresolved_issues") or []),
            human_corrections=list(data.get("human_corrections") or []),
            ordering=list(data.get("ordering") or []),
            created_at=float(data.get("created_at") or 0.0),
            prompt_version=str(data.get("prompt_version") or ""),
            parser_version=str(data.get("parser_version") or "structured_resume_store@1"),
        )


def _revision_id(source_revision: str, store: dict[str, Any], corrections: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {"source_revision": source_revision, "store": store, "corrections": corrections},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def accept_canonical_resume(
    store: dict[str, Any],
    *,
    source_revision: str,
    unresolved_issues: list[dict[str, Any]] | None = None,
    human_corrections: list[dict[str, Any]] | None = None,
    prompt_version: str = "",
) -> CanonicalResume:
    """Freeze an accepted content revision (immutable once created)."""
    corrections = list(human_corrections or [])
    frozen_store = json.loads(json.dumps(store, ensure_ascii=False, default=str))
    ordering = [
        "header",
        "summary",
        "skills",
        "experience",
        "projects",
        "education",
        "certifications",
        "achievements",
        "languages",
        "additional_sections",
    ]
    rev = _revision_id(source_revision, frozen_store, corrections)
    return CanonicalResume(
        revision=rev,
        schema_version=CANONICAL_SCHEMA_VERSION,
        source_revision=source_revision,
        store=frozen_store,
        unresolved_issues=list(unresolved_issues or []),
        human_corrections=corrections,
        ordering=ordering,
        created_at=time.time(),
        prompt_version=prompt_version,
    )


def apply_human_correction(
    canonical: CanonicalResume,
    correction: dict[str, Any],
) -> CanonicalResume:
    """Corrections create a new revision (never mutate the prior one)."""
    new_store = json.loads(json.dumps(canonical.store, ensure_ascii=False, default=str))
    path = str(correction.get("path") or "")
    value = correction.get("value")
    if path.startswith("experience.") and isinstance(value, dict):
        # experience.<idx>.field
        parts = path.split(".")
        if len(parts) >= 2 and parts[1].isdigit():
            idx = int(parts[1])
            roles = list(new_store.get("experience") or [])
            if 0 <= idx < len(roles) and isinstance(roles[idx], dict):
                roles[idx] = {**roles[idx], **value}
                new_store["experience"] = roles
    corrections = [
        *canonical.human_corrections,
        {**correction, "applied_at": time.time(), "from_revision": canonical.revision},
    ]
    return accept_canonical_resume(
        new_store,
        source_revision=canonical.source_revision,
        unresolved_issues=list(canonical.unresolved_issues),
        human_corrections=corrections,
        prompt_version=canonical.prompt_version,
    )


def get_template_contract(template_key: str) -> dict[str, Any]:
    key = (template_key or "aptino").strip().lower()
    if key not in TEMPLATE_CONTRACTS:
        return {
            "version": f"unknown@0",
            "template_key": key,
            "validated": False,
            "requires_validation_before_accept": True,
            "supported_sections": list(TEMPLATE_CONTRACTS["aptino"]["supported_sections"]),
            "pagination": {"overflow": "continue_pages", "force_source_page_count": False},
            "note": "Unknown uploaded template requires validation before automatic acceptance.",
        }
    return {**TEMPLATE_CONTRACTS[key], "validated": True, "template_key": key}


def persist_canonical(canonical: CanonicalResume, *, tenant_id: str) -> Path:
    settings = get_settings()
    root = Path(settings.UPLOAD_DIR) / "canonical" / _safe(tenant_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{canonical.revision}.json"
    path.write_text(json.dumps(canonical.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_canonical(revision: str, *, tenant_id: str) -> CanonicalResume | None:
    settings = get_settings()
    path = Path(settings.UPLOAD_DIR) / "canonical" / _safe(tenant_id) / f"{revision}.json"
    if not path.is_file():
        return None
    return CanonicalResume.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _safe(value: str) -> str:
    return re_sub_safe(value)


def re_sub_safe(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "tenant")[:80]
