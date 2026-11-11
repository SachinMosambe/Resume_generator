"""Pytest-free style assertions for the Capgemini / Suresh / Aptino client formats.

Shared by ``tests/test_format_style_asserts.py`` and the ``--golden`` CI runner
(``scripts/corpus_quality_eval.py``), which cannot import pytest. Each ``assert_*``
helper raises ``AssertionError`` on a style deviation.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

GOLDEN = Path(__file__).resolve().parent

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


def source_text(fixture: dict) -> str:
    return (GOLDEN / fixture["source"]).read_text(encoding="utf-8")


def paragraphs(data: bytes) -> list:
    return [p for p in Document(io.BytesIO(data)).paragraphs if p.text.strip()]


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def heading_positions(data: bytes, fmt: str) -> dict[str, int]:
    """Paragraph index of each section heading, found by the format's own label."""
    paras = paragraphs(data)
    found: dict[str, int] = {}
    for section, label in EXPECTED[fmt]["labels"].items():
        for idx, para in enumerate(paras):
            if norm(para.text) == norm(label):
                found[section] = idx
                break
    return found


def section_text(data: bytes, fmt: str, section: str) -> str:
    """Text between a section heading and the next heading of any section."""
    paras = paragraphs(data)
    positions = heading_positions(data, fmt)
    start = positions[section]
    later = [pos for pos in positions.values() if pos > start]
    end = min(later) if later else len(paras)
    return "\n".join(p.text for p in paras[start + 1 : end])


def assert_name_align(data: bytes, fmt: str, expected_name: str) -> None:
    first = paragraphs(data)[0]
    assert first.text.strip() == expected_name, (fmt, first.text.strip())
    assert first.alignment == EXPECTED[fmt]["name_align"], (fmt, first.alignment)


def assert_font_family(data: bytes, fmt: str) -> None:
    wanted = EXPECTED[fmt]["font_family"]
    named = [run.font.name for p in paragraphs(data) for run in p.runs if run.text.strip() and run.font.name]
    assert named, "no explicit run fonts found"
    assert set(named) == {wanted}, (fmt, set(named))


def assert_section_order(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
    positions = heading_positions(data, fmt)
    assert present <= set(positions) <= present | optional, (fmt, sorted(positions), sorted(present))
    ordered = [s for s in EXPECTED[fmt]["order"] if s in positions]
    assert sorted(positions, key=positions.get) == ordered, (fmt, sorted(positions, key=positions.get))


def assert_labels(data: bytes, fmt: str, present: set[str], optional: set[str] = frozenset()) -> None:
    body = {norm(p.text) for p in paragraphs(data)}
    for section in present:
        assert norm(EXPECTED[fmt]["labels"][section]) in body, (fmt, section)
    for section, label in EXPECTED[fmt]["labels"].items():
        if section not in present | optional:
            assert norm(label) not in body, f"{fmt}: unexpected empty heading {label!r}"


def expected_sections(fixture: dict) -> set[str]:
    """Sections the source actually backs, read from its own headings (never invented)."""
    headings = {
        "summary": r"summary|profile|objective",
        "skills": r"skills?|technical skills",
        "education": r"education",
        "experience": r"(?:work |professional )?experience",
        "projects": r"projects?",
    }
    lines = [ln.strip() for ln in source_text(fixture).splitlines()]
    return {
        section
        for section, pattern in headings.items()
        if any(re.fullmatch(pattern, ln, re.I) for ln in lines)
    }


def assert_content_same(data: bytes, fmt: str, fixture: dict) -> None:
    """Same source facts land under the format's own experience heading, in every format."""
    experience = norm(section_text(data, fmt, "experience"))
    assert fixture["expected_roles"], fixture["id"]
    for role in fixture["expected_roles"]:
        assert norm(role["company"]) in experience, (fmt, role["company"])
        assert norm(role["title"]) in experience, (fmt, role["title"])
        for token in role.get("dates_contains", []):
            assert norm(token) in experience, (fmt, token)
        for bullet in role.get("bullet_substrings", []):
            assert norm(bullet) in experience, (fmt, bullet)
    if "education" in expected_sections(fixture):
        assert "example state college" in norm(section_text(data, fmt, "education"))


def check_style(data: bytes, fmt: str, fixture: dict) -> list[str]:
    """Run every per-fixture style assertion; return failure messages (empty = pass)."""
    failures: list[str] = []
    present = expected_sections(fixture)
    checks = (
        ("name_align", lambda: assert_name_align(data, fmt, fixture["expected_name"])),
        ("font_family", lambda: assert_font_family(data, fmt)),
        ("section_order", lambda: assert_section_order(data, fmt, present, optional={"summary"})),
        ("labels", lambda: assert_labels(data, fmt, present, optional={"summary"})),
        ("content", lambda: assert_content_same(data, fmt, fixture)),
    )
    for name, check in checks:
        try:
            check()
        except AssertionError as exc:
            failures.append(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a crashed assertion is still a style failure
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    return failures
