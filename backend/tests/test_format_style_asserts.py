"""Style asserts for the Capgemini / Suresh / Aptino client formats on clean golden fixtures.

Only manifest fixtures flagged ``style_subset`` are used: they parse cleanly, so any
style deviation here is a rendering problem rather than a parsing one.
"""

import io
import json
import logging
import re
from pathlib import Path

import pytest
import structlog
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.models.candidate import Candidate
from app.models.client_format import ClientFormat
from app.models.format_schema import normalize_format_metadata
from app.services.aptino_template import build_aptino_client_format
from app.services.docx_skeleton_service import render_from_docx_skeleton
from app.services.format_extraction_service import FormatExtractionService
from app.services.resume_generation_service import ResumeGenerationService
import app.services.resume_generation_service as rgs

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL))

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
FORMAT_DIR = Path(__file__).resolve().parents[2] / "test" / "format"
TEMPLATES = {
    "capgemini": FORMAT_DIR / "Capgemini-Format.docx",
    "suresh": FORMAT_DIR / "Suresh Duvvada.docx",
}

# What each client format must produce, independent of the candidate.
EXPECTED = {
    "capgemini": {
        "name_align": WD_ALIGN_PARAGRAPH.RIGHT,
        "font_family": "Avenir 45",
        "order": ["summary", "skills", "experience", "projects", "education"],
        "labels": {
            "summary": "Professional Summary",
            "skills": "Skills Profile",
            "experience": "Professional Experience",
            "projects": "Summary of Projects",
            "education": "Education",
        },
    },
    "suresh": {
        "name_align": WD_ALIGN_PARAGRAPH.CENTER,
        "font_family": "Arial",
        "order": ["summary", "skills", "education", "experience", "projects"],
        "labels": {
            "summary": "Professional Summary",
            "skills": "Skill Set Overview",
            "education": "Educational Details",
            "experience": "Work Experience",
            "projects": "Projects",
        },
    },
    "aptino": {
        "name_align": WD_ALIGN_PARAGRAPH.LEFT,
        "font_family": "Arial",
        "order": ["summary", "skills", "education", "experience", "projects"],
        "labels": {
            "summary": "Professional Summary",
            "skills": "Skill Set Overview",
            "education": "Educational Details",
            "experience": "Work Experience",
            "projects": "Projects",
        },
    },
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
def client_formats() -> dict[str, ClientFormat]:
    formats = {"aptino": build_aptino_client_format("Aptino")}
    extractor = FormatExtractionService()
    for key, path in TEMPLATES.items():
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


def _source_text(fixture: dict) -> str:
    return (GOLDEN / fixture["source"]).read_text(encoding="utf-8")


def _generate(fixture: dict, client_format: ClientFormat) -> bytes:
    text = _source_text(fixture)
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


# ---------------------------------------------------------------- assert helpers


def _paragraphs(data: bytes) -> list:
    return [p for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def heading_positions(data: bytes, fmt: str) -> dict[str, int]:
    """Paragraph index of each section heading, found by the format's own label."""
    paras = _paragraphs(data)
    found: dict[str, int] = {}
    for section, label in EXPECTED[fmt]["labels"].items():
        for idx, para in enumerate(paras):
            if _norm(para.text) == _norm(label):
                found[section] = idx
                break
    return found


def section_text(data: bytes, fmt: str, section: str) -> str:
    """Text between a section heading and the next heading of any section."""
    paras = _paragraphs(data)
    positions = heading_positions(data, fmt)
    start = positions[section]
    later = [pos for pos in positions.values() if pos > start]
    end = min(later) if later else len(paras)
    return "\n".join(p.text for p in paras[start + 1 : end])


def assert_name_align(data: bytes, fmt: str, expected_name: str) -> None:
    first = _paragraphs(data)[0]
    assert first.text.strip() == expected_name
    assert first.alignment == EXPECTED[fmt]["name_align"], (fmt, first.alignment)


def assert_font_family(data: bytes, fmt: str) -> None:
    wanted = EXPECTED[fmt]["font_family"]
    named = [run.font.name for p in _paragraphs(data) for run in p.runs if run.text.strip() and run.font.name]
    assert named, "no explicit run fonts found"
    assert set(named) == {wanted}, (fmt, set(named))


def assert_section_order(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
    positions = heading_positions(data, fmt)
    assert present <= set(positions) <= present | optional, (fmt, sorted(positions), sorted(present))
    ordered = [s for s in EXPECTED[fmt]["order"] if s in positions]
    assert sorted(positions, key=positions.get) == ordered


def assert_labels(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
    body = {_norm(p.text) for p in _paragraphs(data)}
    for section in present:
        assert _norm(EXPECTED[fmt]["labels"][section]) in body, (fmt, section)
    for section, label in EXPECTED[fmt]["labels"].items():
        if section not in present | optional:
            assert _norm(label) not in body, f"{fmt}: unexpected empty heading {label!r}"


def expected_sections(fixture: dict) -> set[str]:
    """Sections the source actually backs, read from its own headings (never invented)."""
    headings = {
        "summary": r"summary|profile|objective",
        "skills": r"skills?|technical skills",
        "education": r"education",
        "experience": r"(?:work |professional )?experience",
        "projects": r"projects?",
    }
    lines = [ln.strip() for ln in _source_text(fixture).splitlines()]
    return {
        section
        for section, pattern in headings.items()
        if any(re.fullmatch(pattern, ln, re.I) for ln in lines)
    }

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
    experience = _norm(section_text(data, fmt, "experience"))
    assert fixture["expected_roles"], fixture_id
    for role in fixture["expected_roles"]:
        assert _norm(role["company"]) in experience, (fmt, role["company"])
        assert _norm(role["title"]) in experience, (fmt, role["title"])
        for token in role.get("dates_contains", []):
            assert _norm(token) in experience, (fmt, token)
        for bullet in role.get("bullet_substrings", []):
            assert _norm(bullet) in experience, (fmt, bullet)
    if "education" in expected_sections(fixture):
        assert "example state college" in _norm(section_text(data, fmt, "education"))


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
