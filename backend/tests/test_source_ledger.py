"""Source ledger: provenance, dispositions, narrow normalization."""

from __future__ import annotations

from app.services.source_blocks import SourceBlock
from app.services.source_ledger import (
    DISPOSITION_EXCLUDED,
    DISPOSITION_REQUIRED,
    DISPOSITION_UNRESOLVED,
    LEDGER_SCHEMA_VERSION,
    build_ledger_from_blocks,
    exclude_item,
    normalize_for_match,
    split_span,
)


def test_normalize_for_match_collapses_whitespace_only():
    assert normalize_for_match("  Shipped\nthe\tonboarding  ") == "Shipped the onboarding"
    # Meaningful punctuation / numbers / dates must survive.
    assert normalize_for_match("Cut cost by 35%.") == "Cut cost by 35%."
    assert normalize_for_match("Jan 2020 – Present") == "Jan 2020 – Present"


def test_build_ledger_assigns_stable_ids_and_defaults_unresolved():
    blocks = [
        SourceBlock("b00001", "Acme Corp — Engineer — 2020-2022", "body", page=1),
        SourceBlock("b00002", "• Shipped the onboarding checklist.", "body", page=1, is_list=True),
    ]
    ledger = build_ledger_from_blocks(
        blocks,
        file_hash="abc123",
        extractor_version="docx_reader@1",
        extraction_method="docx_native",
    )
    assert ledger.schema_version == LEDGER_SCHEMA_VERSION
    assert ledger.source_revision.startswith("abc123:")
    assert [i.id for i in ledger.items] == ["b00001", "b00002"]
    assert all(i.disposition == DISPOSITION_UNRESOLVED for i in ledger.items)
    assert ledger.items[0].raw_text == "Acme Corp — Engineer — 2020-2022"
    assert ledger.items[0].location["origin"] == "body"
    assert ledger.items[0].location["page"] == 1
    assert ledger.items[0].extraction_method == "docx_native"
    assert ledger.items[1].raw_text.startswith("•") or "onboarding" in ledger.items[1].raw_text


def test_unknown_content_stays_unresolved_not_excluded():
    blocks = [SourceBlock("b00001", "Volunteer Board Member, 2019", "body")]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    assert ledger.items[0].disposition == DISPOSITION_UNRESOLVED
    assert ledger.items[0].reason is None


def test_exclusion_is_auditable():
    blocks = [
        SourceBlock("b00001", "Page 3 of 12", "footer", page=3),
        SourceBlock("b00002", "Built the billing API.", "body", page=3),
    ]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    exclude_item(
        ledger,
        "b00001",
        reason="repeated_page_furniture",
        provenance="policy:page_number_footer",
    )
    excluded = ledger.item_by_id("b00001")
    assert excluded.disposition == DISPOSITION_EXCLUDED
    assert excluded.reason == "repeated_page_furniture"
    assert excluded.provenance == "policy:page_number_footer"
    assert ledger.item_by_id("b00002").disposition == DISPOSITION_UNRESOLVED


def test_mark_required_and_span_split_preserves_original():
    blocks = [SourceBlock("b00001", "Acme Corp — Engineer — 2020-2022", "body")]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    span = split_span(ledger, "b00001", start=0, end=9, new_id="b00001.s0")
    assert span.raw_text == "Acme Corp"
    assert span.parent_id == "b00001"
    assert ledger.item_by_id("b00001").raw_text == "Acme Corp — Engineer — 2020-2022"
    ledger.item_by_id("b00001").disposition = DISPOSITION_REQUIRED
    assert ledger.item_by_id("b00001").disposition == DISPOSITION_REQUIRED


def test_ledger_round_trip_dict():
    blocks = [SourceBlock("b00001", "Hello", "header")]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    data = ledger.to_dict()
    restored = type(ledger).from_dict(data)
    assert restored.source_revision == ledger.source_revision
    assert restored.items[0].raw_text == "Hello"
    assert restored.items[0].id == "b00001"
