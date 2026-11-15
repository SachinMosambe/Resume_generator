"""Render manifest: required spans must appear under the correct owner in DOCX."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from app.services.render_manifest import (
    RenderManifestEntry,
    build_render_manifest,
    verify_render_manifest,
)
from app.services.source_blocks import SourceBlock
from app.services.source_ledger import (
    DISPOSITION_REQUIRED,
    DISPOSITION_UNRESOLVED,
    build_ledger_from_blocks,
    mark_required,
)


def _docx_with_text(paragraphs: list[str]) -> bytes:
    doc = Document()
    for line in paragraphs:
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_resolve_ledger_marks_unresolved_when_text_in_unassigned():
    blocks = [
        SourceBlock("b00001", "Acme Corp", "body"),
        SourceBlock("b00002", "• Shipped the onboarding checklist for new analysts in 2021.", "body", is_list=True),
        SourceBlock("b00003", "Volunteer Board Member at Civic Org", "body"),
    ]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    mark_required(ledger, "b00001", provenance="role:role_1:company")
    store = {
        "experience": [{"company": "Acme Corp", "title": "Engineer", "description": [], "role_id": "r1",
                        "source_ids": {"company": ["b00001"]}}],
        "unassigned_experience_bullets": [
            "Shipped the onboarding checklist for new analysts in 2021.",
            "Volunteer Board Member at Civic Org",
        ],
    }
    from app.services.render_manifest import resolve_ledger_against_store

    n = resolve_ledger_against_store(store, ledger)
    assert n >= 2
    assert ledger.item_by_id("b00002").disposition == DISPOSITION_REQUIRED
    assert ledger.item_by_id("b00003").disposition == DISPOSITION_REQUIRED
    manifest = build_render_manifest(store, ledger)
    assert "b00002" not in manifest.unresolved_ids
    assert "b00003" not in manifest.unresolved_ids


def test_build_manifest_requires_destination_for_required_spans():

    blocks = [
        SourceBlock("b00001", "Acme Corp", "body"),
        SourceBlock("b00002", "• Shipped the onboarding checklist for new analysts.", "body", is_list=True),
        SourceBlock(
            "b00003",
            "Volunteer Board Member coordinating weekend community mentoring sessions downtown.",
            "body",
        ),
    ]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    mark_required(ledger, "b00001", provenance="role:role_1:company")
    mark_required(ledger, "b00002", provenance="role:role_1:bullet")
    # b00003 stays unresolved (long fact-bearing line not placed in the store)

    store = {
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "duration": "2020-2022",
                "description": ["Shipped the onboarding checklist for new analysts."],
                "source_ids": {"company": ["b00001"], "bullets": ["b00002"]},
                "role_id": "role_1",
            }
        ]
    }
    manifest = build_render_manifest(store, ledger)
    ids = {e.source_span_ids[0] for e in manifest.entries if e.source_span_ids}
    assert "b00001" in ids
    assert "b00002" in ids
    assert any(i.disposition == DISPOSITION_UNRESOLVED for i in ledger.items if i.id == "b00003")
    assert "b00003" in manifest.unresolved_required_or_blocking_ids or manifest.unresolved_ids


def test_verify_detects_missing_required_occurrence():
    blocks = [
        SourceBlock("b00001", "Acme Corp", "body"),
        SourceBlock("b00002", "Shipped the onboarding checklist for new analysts.", "body"),
    ]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    mark_required(ledger, "b00001")
    mark_required(ledger, "b00002")
    store = {
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "description": ["Shipped the onboarding checklist for new analysts."],
                "source_ids": {"company": ["b00001"], "bullets": ["b00002"]},
                "role_id": "role_1",
            }
        ]
    }
    manifest = build_render_manifest(store, ledger)
    # Output has company but drops the bullet
    docx_bytes = _docx_with_text(["Acme Corp", "Engineer", "Closed the monthly books."])
    issues = verify_render_manifest(docx_bytes, manifest)
    assert any(i.issue_type == "missing_required_text" and "onboarding" in i.reason.lower() for i in issues)


def test_verify_checks_duplicate_bullet_per_owner():
    """Same bullet text under two jobs must be verified per occurrence, not global substring."""
    blocks = [
        SourceBlock("b00001", "Acme Corp", "body"),
        SourceBlock("b00002", "Owned the ledger service.", "body"),
        SourceBlock("b00003", "Globex Inc", "body"),
        SourceBlock("b00004", "Owned the ledger service.", "body"),
    ]
    ledger = build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")
    for i in ("b00001", "b00002", "b00003", "b00004"):
        mark_required(ledger, i)
    store = {
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Engineer",
                "description": ["Owned the ledger service."],
                "source_ids": {"company": ["b00001"], "bullets": ["b00002"]},
                "role_id": "role_1",
            },
            {
                "company": "Globex Inc",
                "title": "Lead",
                "description": ["Owned the ledger service."],
                "source_ids": {"company": ["b00003"], "bullets": ["b00004"]},
                "role_id": "role_2",
            },
        ]
    }
    manifest = build_render_manifest(store, ledger)
    # Only one occurrence of the shared bullet text → second owner missing
    docx_bytes = _docx_with_text(
        [
            "Acme Corp",
            "Engineer",
            "Owned the ledger service.",
            "Globex Inc",
            "Lead",
        ]
    )
    issues = verify_render_manifest(docx_bytes, manifest)
    assert any(
        i.issue_type == "missing_owner_occurrence" and i.owner == "role:role_2"
        for i in issues
    )


def test_intentional_repeat_has_reason():
    entry = RenderManifestEntry(
        source_span_ids=["b00001"],
        owner="template:footer",
        target_section="footer",
        output_element="page_number",
        expected_text="Page",
        repeat_reason="template_page_furniture",
    )
    assert entry.repeat_reason == "template_page_furniture"
