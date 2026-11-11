"""Style asserts for the Capgemini / Suresh / Aptino client formats on clean golden fixtures.

Only manifest fixtures flagged ``style_subset`` are used: they parse cleanly, so any
style deviation here is a rendering problem rather than a parsing one.
"""

import io
import json
import logging
from pathlib import Path

import pytest
import structlog
from docx import Document

from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.models.format_schema import normalize_format_metadata
from app.services.aptino_template import build_aptino_client_format
from app.services.docx_skeleton_service import render_from_docx_skeleton
from app.services.format_extraction_service import FormatExtractionService
from app.services.resume_generation_service import ResumeGenerationService
import app.services.resume_generation_service as rgs

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

from tests.fixtures.golden.style_checks import (  # noqa: E402
    GOLDEN,
    assert_content_same,
    assert_font_family,
    assert_labels,
    assert_name_align,
    assert_section_order,
    expected_sections,
    heading_positions,
    norm as _norm,
    paragraphs as _paragraphs,
    section_text,
    source_text,
)
from tests.fixtures.golden.synthetic_formats import build_synthetic_capgemini_docx  # noqa: E402

FORMAT_DIR = Path(__file__).resolve().parents[2] / "test" / "format"
TEMPLATES = {
    "capgemini": FORMAT_DIR / "Capgemini-Format.docx",
    "suresh": FORMAT_DIR / "Suresh Duvvada.docx",
}


def _style_fixtures() -> list[dict]:
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    return [f for f in manifest["fixtures"] if f.get("style_subset")]


STYLE_FIXTURES = _style_fixtures()
FIXTURE_IDS = [f["id"] for f in STYLE_FIXTURES]


@pytest.fixture(scope="module", autouse=True)
def _offline_pipeline(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("RESUME_LLM_CONDENSE", "false")
    mp.setenv("RESUME_AGENT_PIPELINE", "false")
    mp.setenv("RESUME_LLM_POLISH", "false")
    mp.setattr(rgs, "upload_bytes_to_key", lambda **kwargs: None)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def client_formats(tmp_path_factory) -> dict[str, ClientFormat]:
    formats = {"aptino": build_aptino_client_format("Aptino")}
    extractor = FormatExtractionService()
    for key, path in TEMPLATES.items():
        if not path.exists() and key == "capgemini":
            # The real Capgemini template holds a real candidate's resume and is never
            # committed; fall back to the anonymized synthetic style contract.
            path = tmp_path_factory.mktemp("synthetic_formats") / "Capgemini-Format.docx"
            path.write_bytes(build_synthetic_capgemini_docx())
        if not path.exists():
            continue
        meta = normalize_format_metadata(extractor.extract(path.name, path.read_bytes()))
        formats[key] = ClientFormat(
            client_id=key,
            format_template_path=f"upload://{path.name}",
            format_metadata=meta,
            template_bytes_path=str(path),
        )
    return formats


def _generate(fixture: dict, client_format: ClientFormat) -> bytes:
    text = source_text(fixture)
    candidate = Candidate(
        name="Candidate",
        resume_path="fixture.txt",
        extracted_data={"raw_text": text, "resume_text": text, "extraction_meta": {}},
    )
    return ResumeGenerationService().generate(candidate, client_format)


@pytest.fixture(scope="module")
def generated(client_formats):
    cache: dict[tuple[str, str], bytes] = {}

    def get(fixture_id: str, fmt: str) -> bytes:
        key = (fixture_id, fmt)
        if fmt not in client_formats:
            pytest.skip(f"client format template missing: {TEMPLATES[fmt]}")
        if key not in cache:
            fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
            cache[key] = _generate(fixture, client_formats[fmt])
        return cache[key]

    return get


# ------------------------------------------------------------------------ tests


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_capgemini_name_right_avenir(generated, fixture_id):
    fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
    data = generated(fixture_id, "capgemini")
    assert_name_align(data, "capgemini", fixture["expected_name"])
    assert_font_family(data, "capgemini")


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_suresh_name_center_arial(generated, fixture_id):
    fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
    data = generated(fixture_id, "suresh")
    assert_name_align(data, "suresh", fixture["expected_name"])
    assert_font_family(data, "suresh")


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_aptino_name_left_arial(generated, fixture_id):
    fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
    data = generated(fixture_id, "aptino")
    assert_name_align(data, "aptino", fixture["expected_name"])
    assert_font_family(data, "aptino")


@pytest.mark.parametrize("fmt", ["capgemini", "suresh", "aptino"])
@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_section_order_and_labels(generated, fixture_id, fmt):
    fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
    data = generated(fixture_id, fmt)
    present = expected_sections(fixture)
    # The generator may add a generic summary when the source has none; that is the only
    # tolerated extra heading. Projects is never tolerated without source projects.
    assert_section_order(data, fmt, present, optional={"summary"})
    assert_labels(data, fmt, present, optional={"summary"})


@pytest.mark.parametrize("fmt", ["capgemini", "suresh", "aptino"])
@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_content_same_expectations_all_formats(generated, fixture_id, fmt):
    """Same source facts land under the format's own experience heading, in every format."""
    fixture = next(f for f in STYLE_FIXTURES if f["id"] == fixture_id)
    data = generated(fixture_id, fmt)
    assert_content_same(data, fmt, fixture)


@pytest.mark.parametrize("fmt", ["capgemini", "suresh", "aptino"])
def test_project_content_lands_under_projects_heading(generated, fmt):
    data = generated("clean_with_projects", fmt)
    projects = _norm(section_text(data, fmt, "projects"))
    assert "billing service migration" in projects
    assert "moved invoices onto the new ledger" in projects
    assert "billing service migration" not in _norm(section_text(data, fmt, "experience"))


def test_capgemini_hides_empty_projects(generated):
    """No source-backed projects: no 'Summary of Projects' heading and no invented project."""
    data = generated("clean_without_projects", "capgemini")
    texts = [_norm(p.text) for p in _paragraphs(data)]
    assert _norm("Summary of Projects") not in texts
    assert "projects" not in texts
    assert_section_order(data, "capgemini", {"summary", "skills", "experience", "education"})


def test_capgemini_skeleton_drops_heading_of_empty_projects_section():
    """The renderer itself never emits a heading with nothing under it."""
    template = TEMPLATES["capgemini"]
    if not template.exists():
        pytest.skip(f"client format template missing: {template}")
    metadata = normalize_format_metadata(
        FormatExtractionService().extract(template.name, template.read_bytes())
    )
    document = {
        "header": {"name": "Alex Example"},
        "sections": [
            {"type": "bullets", "title": "Professional Summary", "content": ["Ships platform work."]},
            {
                "type": "experience",
                "title": "Professional Experience",
                "content": [
                    {"company": "ExampleCorp", "title": "Senior Engineer", "duration": "2020 - Present",
                     "description": ["Shipped the billing service."]}
                ],
            },
            {"type": "projects", "title": "Summary of Projects", "content": []},
            {"type": "education", "title": "Education", "content": [{"degree": "BS", "institution": "State College"}]},
        ],
    }
    rendered = render_from_docx_skeleton(template, document, metadata)
    assert rendered is not None
    texts = [p.text.strip() for p in Document(io.BytesIO(rendered)).paragraphs if p.text.strip()]
    assert "Summary of Projects" not in texts
    assert "Professional Experience" in texts and "Education" in texts
    # Project content in the source still renders under the heading.
    document["sections"][2]["content"] = [{"title": "Billing", "description": ["Moved invoices."]}]
    rendered = render_from_docx_skeleton(template, document, metadata)
    texts = [p.text.strip() for p in Document(io.BytesIO(rendered)).paragraphs if p.text.strip()]
    assert "Summary of Projects" in texts
