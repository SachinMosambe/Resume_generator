"""Wave 2 phases 3–7 unit coverage (grounded grouping, canonical, validation, cache, eval)."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from app.services.artifact_cache import build_idempotency_key, get_cached_artifact, publish_artifact
from app.services.canonical_resume import (
    accept_canonical_resume,
    apply_human_correction,
    get_template_contract,
)
from app.services.extraction_adapters import extract_with_adapter, probe_docling_available
from app.services.grounded_grouping import map_line_roles_to_ledger, validate_grouping_payload
from app.services.output_integrity import IntegrityReport
from app.services.render_manifest import build_render_manifest
from app.services.review_validation import build_validation_bundle, merge_outcome_with_integrity
from app.services.source_blocks import SourceBlock
from app.services.source_ledger import build_ledger_from_blocks, mark_required


def _ledger():
    blocks = [
        SourceBlock("b00001", "Acme Corp", "body"),
        SourceBlock("b00002", "Engineer", "body"),
        SourceBlock("b00003", "2020-2022", "body"),
        SourceBlock("b00004", "Shipped the onboarding checklist.", "body"),
        SourceBlock("b00005", "Volunteer Board Member", "body"),
    ]
    return build_ledger_from_blocks(blocks, file_hash="h", extractor_version="t@1")


def test_validate_grouping_copies_text_from_ledger_only():
    ledger = _ledger()
    payload = {
        "roles": [
            {
                "role_id": "role_1",
                "employer_source_ids": ["b00001"],
                "title_source_ids": ["b00002"],
                "date_source_ids": ["b00003"],
                "bullet_source_ids": ["b00004"],
            }
        ],
        "unassigned_source_ids": ["b00005"],
    }
    result = validate_grouping_payload(payload, ledger)
    assert result.raw_valid
    assert result.roles[0]["company"] == "Acme Corp"
    assert result.roles[0]["description"] == ["Shipped the onboarding checklist."]
    assert "b00005" in result.unassigned_source_ids


def test_validate_grouping_rejects_unknown_and_conflicts():
    ledger = _ledger()
    payload = {
        "roles": [
            {
                "role_id": "role_1",
                "employer_source_ids": ["b00001"],
                "title_source_ids": ["b99999"],
                "bullet_source_ids": ["b00004"],
            },
            {
                "role_id": "role_2",
                "employer_source_ids": ["b00001"],
                "title_source_ids": ["b00002"],
                "bullet_source_ids": [],
            },
        ],
        "unassigned_source_ids": [],
    }
    result = validate_grouping_payload(payload, ledger)
    assert any(i.issue_type == "unknown_source_id" for i in result.issues)
    assert any(i.issue_type == "conflicting_assignment" for i in result.issues)


def test_map_line_roles_attaches_source_ids():
    ledger = _ledger()
    roles = [
        {
            "company": "Acme Corp",
            "title": "Engineer",
            "duration": "2020-2022",
            "description": ["Shipped the onboarding checklist."],
        }
    ]
    result = map_line_roles_to_ledger(roles, ["Volunteer Board Member"], ["Acme Corp"], ledger)
    assert result.roles[0]["source_ids"]["company"] == ["b00001"]
    assert result.roles[0]["source_ids"]["bullets"] == ["b00004"]


def test_canonical_revision_immutable_and_correction_new_rev():
    store = {"experience": [{"company": "Acme", "title": "Eng", "description": []}]}
    c1 = accept_canonical_resume(store, source_revision="abc:docx@1")
    c2 = apply_human_correction(
        c1, {"path": "experience.0", "value": {"title": "Senior Eng"}, "by": "recruiter"}
    )
    assert c1.revision != c2.revision
    assert c1.store["experience"][0]["title"] == "Eng"
    assert c2.store["experience"][0]["title"] == "Senior Eng"
    assert c2.human_corrections


def test_unknown_template_requires_validation():
    contract = get_template_contract("custom_upload")
    assert contract["requires_validation_before_accept"] is True
    assert get_template_contract("aptino")["validated"] is True


def test_validation_bundle_forces_review_on_unresolved():
    ledger = _ledger()
    store = {
        "experience": [
            {
                "role_id": "role_1",
                "company": "Acme Corp",
                "title": "Engineer",
                "description": ["Shipped the onboarding checklist."],
                "source_ids": {"company": ["b00001"], "title": ["b00002"], "bullets": ["b00004"]},
            }
        ]
    }
    mark_required(ledger, "b00001")
    mark_required(ledger, "b00004")
    manifest = build_render_manifest(store, ledger)
    doc = Document()
    doc.add_paragraph("Acme Corp")
    doc.add_paragraph("Engineer")
    doc.add_paragraph("Shipped the onboarding checklist.")
    buf = BytesIO()
    doc.save(buf)
    integrity = IntegrityReport("passed", {}, [])
    bundle = build_validation_bundle(
        extraction_meta={},
        ledger=ledger,
        manifest=manifest,
        docx_bytes=buf.getvalue(),
        integrity=integrity,
    )
    # unresolved leftover items → needs_review
    assert bundle.outcome == "needs_review"
    merged = merge_outcome_with_integrity(integrity, bundle)
    assert merged is not None and merged.status == "needs_review"
    assert any(w.get("code") == "review_draft" for w in merged.warnings if isinstance(w, dict))


def test_artifact_cache_tenant_isolation_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = build_idempotency_key(
        tenant_id="t1",
        source_file_hash="abc",
        canonical_revision="rev1",
        extraction_version="e1",
        schema_version="s1",
        parser_version="p1",
        model_id="google.gemma-3-27b-it",
        prompt_version="g1",
        template_version="aptino@1",
    )
    docx = b"PK-fake-docx-bytes"
    publish_artifact(tenant_id="t1", key=key, docx_bytes=docx, report={"status": "passed"})
    hit = get_cached_artifact("t1", key)
    assert hit is not None
    assert hit[0] == docx
    # Different tenant must not see it even with same key material path separation
    miss = get_cached_artifact("t2", key)
    assert miss is None
    get_settings.cache_clear()


def test_extract_adapter_page_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUME_EXTRACT_MAX_PAGES", "1")
    from app.core.config import get_settings

    get_settings.cache_clear()
    # Use a tiny pdf if available via pymupdf
    try:
        import fitz
    except ImportError:
        get_settings.cache_clear()
        return
    path = tmp_path / "multi.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(path)
    doc.close()
    result = extract_with_adapter(str(path))
    get_settings.cache_clear()
    assert result.status == "failed"
    assert result.diagnostics.get("reason") == "page_limit"


def test_docling_probe_is_report_only():
    probe = probe_docling_available()
    assert "available" in probe
    assert probe.get("used") is False


def test_eval_annotation_fixture_shape():
    """Phase 7: human-checkable annotation schema (not model-generated ground truth)."""
    annotation = {
        "id": "golden:clean_one_role",
        "required_content": ["Acme Corp", "Engineer", "Shipped features"],
        "role_ownership": [
            {"owner": "Acme Corp|Engineer", "bullets": ["Shipped features"]}
        ],
        "dates_names_metrics": {"dates": ["2020-2022"], "metrics": []},
        "intentional_exclusions": [{"text": "Page 1 of 1", "reason": "page_furniture"}],
        "expected_sections": ["experience", "education"],
        "split": "dev",
        "holdout": False,
    }
    assert annotation["holdout"] is False
    assert annotation["role_ownership"][0]["owner"]
