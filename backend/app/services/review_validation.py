"""Phase 5: separated validation checks and actionable review issues.

Does not weaken existing integrity thresholds. Adds parallel diagnostics and
maps outcomes to passed / needs_review / failed compatibly.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.output_integrity import IntegrityReport
from app.services.render_manifest import ManifestIssue, RenderManifest, verify_render_manifest
from app.services.source_ledger import DISPOSITION_REQUIRED, DISPOSITION_UNRESOLVED, SourceLedger


@dataclass
class ReviewIssue:
    issue_type: str
    source_ids: list[str]
    source_location: dict[str, Any] | None
    owner: str | None
    output_location: str | None
    reason: str
    suggested_action: str
    stage: str  # extraction | grouping | manifest | renderer | layout | integrity

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationBundle:
    extraction_ok: bool = True
    required_coverage_ok: bool = True
    role_ownership_ok: bool = True
    no_unsupported_additions: bool = True
    duplicate_occurrences_ok: bool = True
    layout_ok: bool = True  # automated layout is advisory only
    issues: list[ReviewIssue] = field(default_factory=list)
    outcome: str = "passed"  # passed | needs_review | failed
    review_draft: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "extraction_ok": self.extraction_ok,
            "required_coverage_ok": self.required_coverage_ok,
            "role_ownership_ok": self.role_ownership_ok,
            "no_unsupported_additions": self.no_unsupported_additions,
            "duplicate_occurrences_ok": self.duplicate_occurrences_ok,
            "layout_ok": self.layout_ok,
            "outcome": self.outcome,
            "review_draft": self.review_draft,
            "issues": [i.to_dict() for i in self.issues[:100]],
        }


def check_extraction_completeness(meta: dict[str, Any] | None) -> list[ReviewIssue]:
    meta = meta or {}
    issues: list[ReviewIssue] = []
    if meta.get("truncated"):
        issues.append(
            ReviewIssue(
                "extraction_truncated",
                [],
                None,
                None,
                None,
                "Extraction was truncated (char/page budget).",
                "Re-run full extraction; do not treat as complete intake",
                "extraction",
            )
        )
    if meta.get("ocr_missing_pages"):
        issues.append(
            ReviewIssue(
                "ocr_missing_pages",
                [],
                {"pages": meta.get("ocr_missing_pages")},
                None,
                None,
                "Some scanned pages could not be OCR'd.",
                "Enable OCR or upload a text-based source",
                "extraction",
            )
        )
    adapter = meta.get("extraction_adapter") or {}
    if adapter.get("status") in {"failed", "unsupported"}:
        issues.append(
            ReviewIssue(
                "extraction_failed",
                [],
                None,
                None,
                None,
                f"Extraction status={adapter.get('status')} reason={((adapter.get('diagnostics') or {}).get('reason'))}",
                "Fix source file or conversion/OCR environment",
                "extraction",
            )
        )
    return issues


def check_required_coverage(ledger: SourceLedger | None, manifest: RenderManifest | None) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    if ledger is None:
        return issues
    required = [i for i in ledger.items if i.disposition == DISPOSITION_REQUIRED]
    unresolved = [i for i in ledger.items if i.disposition == DISPOSITION_UNRESOLVED]
    if unresolved:
        issues.append(
            ReviewIssue(
                "unresolved_source",
                [i.id for i in unresolved[:50]],
                None,
                None,
                None,
                f"{len(unresolved)} source item(s) remain unresolved.",
                "Assign ownership or exclude with auditable reason",
                "grouping",
            )
        )
    if manifest is not None:
        covered = {sid for e in manifest.entries for sid in e.source_span_ids}
        missing_dest = [i.id for i in required if i.id not in covered]
        if missing_dest:
            issues.append(
                ReviewIssue(
                    "required_without_destination",
                    missing_dest[:50],
                    None,
                    None,
                    None,
                    "Required source spans have no render destination.",
                    "Repair manifest/renderer mapping",
                    "manifest",
                )
            )
    return issues


def check_role_ownership(manifest_issues: list[ManifestIssue]) -> list[ReviewIssue]:
    out: list[ReviewIssue] = []
    for mi in manifest_issues:
        if mi.issue_type == "missing_owner_occurrence":
            out.append(
                ReviewIssue(
                    "role_ownership",
                    list(mi.source_ids),
                    None,
                    mi.owner,
                    mi.output_location,
                    mi.reason,
                    mi.suggested_action,
                    "grouping",
                )
            )
    return out


def check_unsupported_additions(integrity: IntegrityReport | None) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    if integrity is None:
        return issues
    for w in integrity.warnings or []:
        if not isinstance(w, dict):
            continue
        code = str(w.get("code") or "")
        if code in {"unsupported_addition", "invented_content", "template_sample_leak"}:
            issues.append(
                ReviewIssue(
                    code or "unsupported_addition",
                    [],
                    None,
                    None,
                    None,
                    str(w.get("message") or code),
                    "Remove unsupported additions; never invent candidate facts",
                    "integrity",
                )
            )
    return issues


def check_duplicate_occurrences(manifest_issues: list[ManifestIssue]) -> list[ReviewIssue]:
    return [
        ReviewIssue(
            "duplicate_occurrence",
            list(mi.source_ids),
            None,
            mi.owner,
            mi.output_location,
            mi.reason,
            mi.suggested_action,
            "renderer",
        )
        for mi in manifest_issues
        if mi.issue_type == "missing_owner_occurrence"
    ]


def build_validation_bundle(
    *,
    extraction_meta: dict[str, Any] | None,
    ledger: SourceLedger | None,
    manifest: RenderManifest | None,
    docx_bytes: bytes | None,
    integrity: IntegrityReport | None,
) -> ValidationBundle:
    bundle = ValidationBundle()
    issues: list[ReviewIssue] = []
    issues.extend(check_extraction_completeness(extraction_meta))

    manifest_issues: list[ManifestIssue] = []
    if manifest is not None and docx_bytes:
        manifest_issues = verify_render_manifest(docx_bytes, manifest)

    issues.extend(check_required_coverage(ledger, manifest))
    ownership = check_role_ownership(manifest_issues)
    issues.extend(ownership)
    issues.extend(check_unsupported_additions(integrity))
    dupes = check_duplicate_occurrences(manifest_issues)
    issues.extend(dupes)
    for mi in manifest_issues:
        if mi.issue_type == "missing_required_text":
            issues.append(
                ReviewIssue(
                    "missing_output",
                    list(mi.source_ids),
                    None,
                    mi.owner,
                    mi.output_location,
                    mi.reason,
                    "Repair manifest/renderer; never append under an arbitrary role",
                    "renderer",
                )
            )

    bundle.issues = issues
    bundle.extraction_ok = not any(i.stage == "extraction" for i in issues)
    bundle.required_coverage_ok = not any(
        i.issue_type in {"unresolved_source", "required_without_destination", "missing_output"} for i in issues
    )
    bundle.role_ownership_ok = not ownership
    bundle.no_unsupported_additions = not any(i.stage == "integrity" and "addition" in i.issue_type for i in issues)
    bundle.duplicate_occurrences_ok = not dupes
    # Automated layout checks are advisory; unresolved visual issues → review, not claimed flawless.
    bundle.layout_ok = True

    if integrity is not None and integrity.status == "failed":
        bundle.outcome = "failed"
    elif issues or (integrity is not None and integrity.status == "needs_review"):
        bundle.outcome = "needs_review"
        bundle.review_draft = True
    else:
        bundle.outcome = "passed"
    return bundle


def merge_outcome_with_integrity(
    integrity: IntegrityReport | None, bundle: ValidationBundle
) -> IntegrityReport | None:
    """Map bundle outcome onto existing IntegrityReport without loosening checks."""
    if integrity is None:
        return None
    if bundle.outcome == "failed" and integrity.status != "failed":
        from app.services.output_integrity import IntegrityReport as IR

        warnings = list(integrity.warnings)
        warnings.append(
            {
                "severity": "blocking",
                "code": "validation_bundle_failed",
                "message": "Wave-2 validation bundle marked this output failed.",
            }
        )
        return IR("failed", dict(integrity.checks), warnings)
    if bundle.outcome == "needs_review" and integrity.status == "passed":
        from app.services.output_integrity import IntegrityReport as IR

        warnings = list(integrity.warnings)
        warnings.append(
            {
                "severity": "blocking",
                "code": "validation_bundle_review",
                "message": f"{len(bundle.issues)} wave-2 validation issue(s) need review.",
            }
        )
        if bundle.review_draft:
            warnings.append(
                {
                    "severity": "info",
                    "code": "review_draft",
                    "message": "Review draft — not represented as verified.",
                }
            )
        return IR("needs_review", dict(integrity.checks), warnings)
    return integrity
