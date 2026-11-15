"""Render manifest: map required source spans to output destinations and verify DOCX.

Verification reopens the actual DOCX and checks visible text + structural position.
Renderer-maintained flags are not sufficient. Duplicate bullet text under two roles
is checked per owner occurrence.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from io import BytesIO
from typing import Any

from app.services.source_ledger import (
    DISPOSITION_REQUIRED,
    DISPOSITION_UNRESOLVED,
    SourceLedger,
    mark_required,
    normalize_for_match,
)


@dataclass
class RenderManifestEntry:
    source_span_ids: list[str]
    owner: str
    target_section: str
    output_element: str
    expected_text: str
    repeat_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ManifestIssue:
    issue_type: str
    source_ids: list[str]
    owner: str | None
    output_location: str | None
    reason: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderManifest:
    entries: list[RenderManifestEntry] = field(default_factory=list)
    unresolved_ids: list[str] = field(default_factory=list)
    # Alias used by tests / callers that treat unresolved content as blocking review.
    unresolved_required_or_blocking_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "unresolved_ids": list(self.unresolved_ids),
            "unresolved_required_or_blocking_ids": list(self.unresolved_required_or_blocking_ids),
        }


def _store_text_corpus(store: dict[str, Any]) -> str:
    parts: list[str] = []
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        for key in ("company", "title", "duration", "location"):
            if role.get(key):
                parts.append(str(role.get(key)))
        for bullet in role.get("description") or role.get("bullets") or []:
            parts.append(str(bullet))
    for bullet in store.get("unassigned_experience_bullets") or []:
        parts.append(str(bullet))
    for cert in store.get("certifications") or []:
        parts.append(str(cert))
    return normalize_for_match("\n".join(parts))


def _match_ledger_ids(ledger: SourceLedger, text: str, *, min_len: int = 24) -> list[str]:
    """Return ledger item ids whose normalized text matches ``text`` (exact or containment)."""
    needle = _strip_bullet_prefix(normalize_for_match(text))
    if len(needle) < min_len:
        return []
    hits: list[str] = []
    for item in ledger.items:
        hay = _strip_bullet_prefix(item.normalized_text or normalize_for_match(item.raw_text))
        if not hay or len(hay) < 12:
            continue
        if needle == hay or needle in hay or hay in needle:
            hits.append(item.id)
    return hits


_BULLET_STRIP = tuple("•-*–—▪◦")


def _strip_bullet_prefix(text: str) -> str:
    t = (text or "").strip()
    while t and t[0] in _BULLET_STRIP:
        t = t[1:].lstrip()
    return t


def resolve_ledger_against_store(store: dict[str, Any], ledger: SourceLedger) -> int:
    """Mark ledger items required when their text already lives in the store.

    Stitch / unassigned paths copy source wording into the store without source_ids;
    without this bridge those items stay ``unresolved`` and trip ``source_unresolved``
    even though the content is destined for the DOCX.
    """
    corpus = _store_text_corpus(store)
    if not corpus:
        return 0
    resolved = 0
    for item in ledger.items:
        if item.disposition != DISPOSITION_UNRESOLVED:
            continue
        hay = _strip_bullet_prefix(item.normalized_text or normalize_for_match(item.raw_text))
        if len(hay) < 24:
            continue
        if hay in corpus or hay in _strip_bullet_prefix(corpus):
            mark_required(ledger, item.id, provenance="store_text_match")
            resolved += 1
    return resolved


def build_render_manifest(store: dict[str, Any], ledger: SourceLedger) -> RenderManifest:
    """Build destinations for store fields that carry source_ids; list unresolved ledger items."""
    resolve_ledger_against_store(store, ledger)
    entries: list[RenderManifestEntry] = []
    for role in store.get("experience") or []:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("role_id") or role.get("company") or "role")
        owner = f"role:{role_id}"
        source_ids = role.get("source_ids") if isinstance(role.get("source_ids"), dict) else {}
        company_ids = list(source_ids.get("company") or [])
        title_ids = list(source_ids.get("title") or [])
        date_ids = list(source_ids.get("dates") or source_ids.get("date") or [])
        bullet_ids = list(source_ids.get("bullets") or [])

        if company_ids or role.get("company"):
            if not company_ids and role.get("company"):
                company_ids = _match_ledger_ids(ledger, str(role.get("company")), min_len=8)
            entries.append(
                RenderManifestEntry(
                    source_span_ids=company_ids,
                    owner=owner,
                    target_section="experience",
                    output_element="company",
                    expected_text=str(role.get("company") or _ledger_text(ledger, company_ids)),
                )
            )
        if title_ids or role.get("title"):
            if not title_ids and role.get("title"):
                title_ids = _match_ledger_ids(ledger, str(role.get("title")), min_len=8)
            entries.append(
                RenderManifestEntry(
                    source_span_ids=title_ids,
                    owner=owner,
                    target_section="experience",
                    output_element="title",
                    expected_text=str(role.get("title") or _ledger_text(ledger, title_ids)),
                )
            )
        if date_ids or role.get("duration"):
            entries.append(
                RenderManifestEntry(
                    source_span_ids=date_ids,
                    owner=owner,
                    target_section="experience",
                    output_element="dates",
                    expected_text=str(role.get("duration") or _ledger_text(ledger, date_ids)),
                )
            )
        bullets = role.get("description") or role.get("bullets") or []
        if isinstance(bullets, str):
            bullets = [bullets]
        for idx, bullet in enumerate(bullets):
            sid = [bullet_ids[idx]] if idx < len(bullet_ids) else []
            if not sid and bullet:
                sid = _match_ledger_ids(ledger, str(bullet))
            entries.append(
                RenderManifestEntry(
                    source_span_ids=sid,
                    owner=owner,
                    target_section="experience",
                    output_element=f"bullet:{idx}",
                    expected_text=str(bullet or _ledger_text(ledger, sid)),
                )
            )

    for idx, cert in enumerate(store.get("certifications") or []):
        text = str(cert or "").strip()
        if not text:
            continue
        entries.append(
            RenderManifestEntry(
                source_span_ids=_match_ledger_ids(ledger, text),
                owner="section:certifications",
                target_section="certifications",
                output_element=f"cert:{idx}",
                expected_text=text,
            )
        )

    for idx, bullet in enumerate(store.get("unassigned_experience_bullets") or []):
        text = str(bullet or "").strip()
        if not text:
            continue
        entries.append(
            RenderManifestEntry(
                source_span_ids=_match_ledger_ids(ledger, text),
                owner="section:unassigned",
                target_section="experience",
                output_element=f"unassigned:{idx}",
                expected_text=text,
            )
        )

    covered_ids = {sid for e in entries for sid in e.source_span_ids}
    entry_hay = normalize_for_match("\n".join(e.expected_text for e in entries if e.expected_text))
    # Unresolved items whose text is already covered by a destination are not blocking.
    # Short chrome (months, labels, 1–2 word tokens) stays unresolved for audit but must
    # not fail production fidelity — only fact-bearing unresolved spans are blocking.
    unresolved: list[str] = []
    required_missing_dest: list[str] = []
    for item in ledger.items:
        if item.id in covered_ids:
            continue
        text = _strip_bullet_prefix(item.normalized_text or normalize_for_match(item.raw_text))
        text_covered = bool(text) and len(text) >= 12 and text in entry_hay
        fact_bearing = len(text) >= 40 or bool(re.search(r"\d", text)) or text.lstrip().startswith(
            ("•", "-", "*")
        )
        if item.disposition == DISPOSITION_UNRESOLVED and not text_covered and fact_bearing:
            unresolved.append(item.id)
        elif item.disposition == DISPOSITION_REQUIRED and not text_covered:
            required_missing_dest.append(item.id)
    blocking = list(dict.fromkeys([*unresolved, *required_missing_dest]))
    return RenderManifest(
        entries=entries,
        unresolved_ids=unresolved,
        unresolved_required_or_blocking_ids=blocking,
    )


def _ledger_text(ledger: SourceLedger, ids: list[str]) -> str:
    parts = []
    for item_id in ids:
        try:
            parts.append(ledger.item_by_id(item_id).raw_text)
        except KeyError:
            continue
    return " ".join(parts)


def _docx_paragraphs(docx_bytes: bytes) -> list[str]:
    from docx import Document

    doc = Document(BytesIO(docx_bytes))
    return [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]


def _owner_regions(paragraphs: list[str], owners_in_order: list[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """Map owner -> [start, end) paragraph index range using company needles."""
    regions: dict[str, tuple[int, int]] = {}
    starts: list[tuple[str, int]] = []
    for owner, company in owners_in_order:
        needle = normalize_for_match(company)
        if not needle:
            continue
        for i, para in enumerate(paragraphs):
            if needle in normalize_for_match(para):
                # Prefer first unused occurrence
                if any(s == i for _, s in starts):
                    continue
                starts.append((owner, i))
                break
    starts.sort(key=lambda x: x[1])
    for idx, (owner, start) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else len(paragraphs)
        regions[owner] = (start, end)
    return regions


def verify_render_manifest(docx_bytes: bytes, manifest: RenderManifest) -> list[ManifestIssue]:
    paragraphs = _docx_paragraphs(docx_bytes)
    hay_all = normalize_for_match("\n".join(paragraphs))
    issues: list[ManifestIssue] = []

    owners: list[tuple[str, str]] = []
    seen_owners: set[str] = set()
    for entry in manifest.entries:
        if entry.owner in seen_owners:
            continue
        if entry.output_element == "company" and entry.expected_text:
            owners.append((entry.owner, entry.expected_text))
            seen_owners.add(entry.owner)
    regions = _owner_regions(paragraphs, owners)

    # Count expected bullet texts per owner for multi-occurrence checks.
    for entry in manifest.entries:
        expected = normalize_for_match(entry.expected_text)
        if not expected:
            continue
        if entry.owner.startswith("role:") and entry.output_element.startswith("bullet"):
            region = regions.get(entry.owner)
            if region is None:
                issues.append(
                    ManifestIssue(
                        issue_type="missing_owner_occurrence",
                        source_ids=list(entry.source_span_ids),
                        owner=entry.owner,
                        output_location=None,
                        reason=f"No output region found for {entry.owner}; expected bullet: {entry.expected_text}",
                        suggested_action="Review role ownership and renderer section mapping",
                    )
                )
                continue
            start, end = region
            region_hay = normalize_for_match("\n".join(paragraphs[start:end]))
            if expected not in region_hay:
                if expected not in hay_all:
                    issues.append(
                        ManifestIssue(
                            issue_type="missing_required_text",
                            source_ids=list(entry.source_span_ids),
                            owner=entry.owner,
                            output_location=f"paragraphs[{start}:{end}]",
                            reason=f"Required text missing from DOCX: {entry.expected_text}",
                            suggested_action="Repair manifest destination or renderer omission",
                        )
                    )
                else:
                    issues.append(
                        ManifestIssue(
                            issue_type="missing_owner_occurrence",
                            source_ids=list(entry.source_span_ids),
                            owner=entry.owner,
                            output_location=f"paragraphs[{start}:{end}]",
                            reason=f"Required bullet not found under {entry.owner}: {entry.expected_text}",
                            suggested_action="Repair grouping or renderer for this role; do not append under another role",
                        )
                    )
            continue

        if expected not in hay_all:
            issues.append(
                ManifestIssue(
                    issue_type="missing_required_text",
                    source_ids=list(entry.source_span_ids),
                    owner=entry.owner,
                    output_location=None,
                    reason=f"Required text missing from DOCX: {entry.expected_text}",
                    suggested_action="Repair manifest destination or renderer omission",
                )
            )

    return issues
