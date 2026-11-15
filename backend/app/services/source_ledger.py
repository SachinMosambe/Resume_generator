"""Versioned source ledger: provenance for every extracted content item.

Unknown content defaults to unresolved (not excluded). Exclusions must carry an
auditable reason and provenance. Narrow normalization is whitespace / line-wrap
only — punctuation, dates, and numbers are preserved.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.source_blocks import SourceBlock, _BULLET_PREFIXES

LEDGER_SCHEMA_VERSION = 1
EXTRACTOR_LEDGER_VERSION = "source_ledger@1"

DISPOSITION_REQUIRED = "required"
DISPOSITION_EXCLUDED = "excluded_with_reason"
DISPOSITION_UNRESOLVED = "unresolved"

_WS_RE = re.compile(r"[ \t\f\v]+")
_NEWLINE_RE = re.compile(r"[\r\n]+")


def normalize_for_match(text: str) -> str:
    """Collapse whitespace and line wraps only; keep punctuation, dates, numbers."""
    if not text:
        return ""
    collapsed = _NEWLINE_RE.sub(" ", text)
    collapsed = _WS_RE.sub(" ", collapsed)
    return collapsed.strip()


@dataclass
class SourceItem:
    id: str
    raw_text: str
    normalized_text: str
    location: dict[str, Any]
    extraction_method: str
    uncertainty: float = 0.0
    disposition: str = DISPOSITION_UNRESOLVED
    reason: str | None = None
    provenance: str | None = None
    parent_id: str | None = None
    span: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.span is not None:
            data["span"] = list(self.span)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceItem:
        span = data.get("span")
        return cls(
            id=str(data["id"]),
            raw_text=str(data.get("raw_text") or ""),
            normalized_text=str(data.get("normalized_text") or ""),
            location=dict(data.get("location") or {}),
            extraction_method=str(data.get("extraction_method") or ""),
            uncertainty=float(data.get("uncertainty") or 0.0),
            disposition=str(data.get("disposition") or DISPOSITION_UNRESOLVED),
            reason=data.get("reason"),
            provenance=data.get("provenance"),
            parent_id=data.get("parent_id"),
            span=tuple(span) if isinstance(span, (list, tuple)) and len(span) == 2 else None,
        )


@dataclass
class SourceLedger:
    source_revision: str
    schema_version: int = LEDGER_SCHEMA_VERSION
    file_hash: str = ""
    extractor_version: str = ""
    items: list[SourceItem] = field(default_factory=list)
    unsupported_elements: list[dict[str, Any]] = field(default_factory=list)

    def item_by_id(self, item_id: str) -> SourceItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "schema_version": self.schema_version,
            "file_hash": self.file_hash,
            "extractor_version": self.extractor_version,
            "items": [i.to_dict() for i in self.items],
            "unsupported_elements": list(self.unsupported_elements),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceLedger:
        return cls(
            source_revision=str(data.get("source_revision") or ""),
            schema_version=int(data.get("schema_version") or LEDGER_SCHEMA_VERSION),
            file_hash=str(data.get("file_hash") or ""),
            extractor_version=str(data.get("extractor_version") or ""),
            items=[SourceItem.from_dict(i) for i in (data.get("items") or []) if isinstance(i, dict)],
            unsupported_elements=[
                e for e in (data.get("unsupported_elements") or []) if isinstance(e, dict)
            ],
        )


def _block_display_text(block: SourceBlock) -> str:
    text = (block.text or "").strip()
    if not text:
        return ""
    if block.is_list and not text.startswith(_BULLET_PREFIXES):
        return f"• {text}"
    return text


def _location_from_block(block: SourceBlock) -> dict[str, Any]:
    loc: dict[str, Any] = {"origin": block.origin}
    if block.page is not None:
        loc["page"] = block.page
    if block.bbox is not None:
        loc["bbox"] = list(block.bbox)
    if block.style:
        loc["style"] = block.style
    if block.is_list:
        loc["is_list"] = True
    if block.links:
        loc["links"] = list(block.links)
    return loc


def build_ledger_from_blocks(
    blocks: list[SourceBlock],
    *,
    file_hash: str,
    extractor_version: str,
    extraction_method: str = "native",
    uncertainty: float = 0.0,
    unsupported_elements: list[dict[str, Any]] | None = None,
) -> SourceLedger:
    """Build a versioned ledger. New items default to unresolved."""
    items: list[SourceItem] = []
    for block in blocks:
        raw = _block_display_text(block)
        if not raw and not block.links:
            continue
        if not raw and block.links:
            raw = block.links[0]
        items.append(
            SourceItem(
                id=block.id,
                raw_text=raw,
                normalized_text=normalize_for_match(raw),
                location=_location_from_block(block),
                extraction_method=extraction_method,
                uncertainty=float(uncertainty),
                disposition=DISPOSITION_UNRESOLVED,
            )
        )
    revision = f"{file_hash}:{extractor_version}:{EXTRACTOR_LEDGER_VERSION}"
    return SourceLedger(
        source_revision=revision,
        file_hash=file_hash,
        extractor_version=extractor_version,
        items=items,
        unsupported_elements=list(unsupported_elements or []),
    )


def exclude_item(
    ledger: SourceLedger,
    item_id: str,
    *,
    reason: str,
    provenance: str,
) -> SourceItem:
    item = ledger.item_by_id(item_id)
    item.disposition = DISPOSITION_EXCLUDED
    item.reason = reason
    item.provenance = provenance
    return item


def mark_required(ledger: SourceLedger, item_id: str, *, provenance: str | None = None) -> SourceItem:
    item = ledger.item_by_id(item_id)
    item.disposition = DISPOSITION_REQUIRED
    if provenance:
        item.provenance = provenance
    return item


def split_span(
    ledger: SourceLedger,
    parent_id: str,
    *,
    start: int,
    end: int,
    new_id: str,
) -> SourceItem:
    """Create a child span item; parent raw_text is unchanged."""
    parent = ledger.item_by_id(parent_id)
    if start < 0 or end > len(parent.raw_text) or start >= end:
        raise ValueError(f"invalid span [{start}:{end}] on {parent_id}")
    raw = parent.raw_text[start:end]
    child = SourceItem(
        id=new_id,
        raw_text=raw,
        normalized_text=normalize_for_match(raw),
        location=dict(parent.location),
        extraction_method=parent.extraction_method,
        uncertainty=parent.uncertainty,
        disposition=DISPOSITION_UNRESOLVED,
        parent_id=parent_id,
        span=(start, end),
        provenance=f"span_of:{parent_id}",
    )
    ledger.items.append(child)
    return child
