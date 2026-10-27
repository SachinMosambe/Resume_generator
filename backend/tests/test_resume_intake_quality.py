"""Quality checks ported from the ATS resume pipeline."""

from __future__ import annotations

from app.services.detailed_resume_parser import parse_resume_detailed
from app.services.docx_layout import clean_education_title_dates
from app.services.pdf_parser import extract_text_from_document
from app.services.resume_generation_service import ResumeGenerationService


def test_header_contact_beats_reference_lines():
    text = """Jane Doe
jane.doe@example.com
(415) 555-0199

Experience
Engineer, Acme
2020 - Present
- Built internal platforms for the support team.

References
Hiring Manager bob.manager@other.com
(415) 555-0142
"""
    data = parse_resume_detailed(None, text)
    assert data["email"] == "jane.doe@example.com"
    assert "0199" in data["phone"]
    assert "0142" not in data["phone"]


def test_dedupe_drops_stubs_and_keeps_separate_tours():
    service = ResumeGenerationService()
    items = [
        {
            "company": "Nike",
            "title": "Engineer",
            "duration": "2018 - 2020",
            "description": ["Shipped the checkout service for retail teams."],
        },
        {
            "company": "Nike",
            "title": "Role",
            "duration": "2018 - 2020",
            "description": [],
        },
        {
            "company": "Nike (Remote)",
            "title": "Staff Engineer",
            "duration": "2021 - Present",
            "description": [
                "Led the platform migration for store services.",
                "Cut checkout latency for peak traffic.",
            ],
        },
        {"company": "", "title": "Role", "duration": "", "description": []},
    ]
    cleaned = service._dedupe_experience_items(items)
    titles = [item.get("title") for item in cleaned]
    assert titles == ["Engineer", "Staff Engineer"]


def test_education_heading_crumbs_are_removed():
    title, dates = clean_education_title_dates(
        "Education: B.S. Computer Science May",
        "Graduated May 2016",
    )
    assert title == "B.S. Computer Science"
    assert dates == "2016"


def test_education_date_ranges_keep_end_date():
    assert clean_education_title_dates("B.E.", "2016 – 2019")[1] == "2016 – 2019"
    assert clean_education_title_dates("M.Tech", "Aug 2022 — May 2024")[1] == "Aug 2022 — May 2024"
    assert clean_education_title_dates("B.S.", "2015-2018")[1] == "2015-2018"
    assert clean_education_title_dates("MBA", "May 2024")[1] == "May 2024"


def test_column_style_header_and_dotted_dates():
    text = """SCOTT SYMES
Senior iOS Engineer | Mobile Tech Lead
scott@symes.dev
(206) 751-5555
linkedin.com/in/scott-symes
Seattle, WA, USA

SUMMARY
Senior iOS engineer with 9+ years of mobile experience scaling mission-critical apps.

SKILLS
Languages & Frameworks: Swift, SwiftUI, UIKit

EXPERIENCE
Senior Software Engineer (iOS) Atlas Mobility Jul. 2024 - Aug. 2026
• Architected a native Swift offline-sync engine for hospital tracking.
Senior Software Engineer (iOS) Davidson Technology Jul. 2022 - Nov. 2023
• Led an iOS squad for the landing screen and core savings features.

EDUCATION
B.S. in Software Engineering (Computer Science)
RMIT University
B.E. in Aerospace Engineering
RMIT University
"""
    data = parse_resume_detailed(None, text)
    assert data["name"] == "Scott Symes"
    assert data["email"] == "scott@symes.dev"
    assert "751-5555" in data["phone"]
    assert "scott-symes" in data["linkedin"]
    assert "Swift" in data["skills"]
    assert "Languages" not in data["summary"]
    titles = [role.get("title") for role in data["experience"]]
    companies = [role.get("company") for role in data["experience"]]
    assert titles[0].startswith("Senior Software Engineer")
    assert "Atlas Mobility" in companies[0]
    assert "Jul" in data["experience"][0]["duration"]
    assert "Davidson" in companies[1]
    degrees = " ".join(item.get("degree") or "" for item in data["education"])
    assert "Software Engineering" in degrees
    assert "Aerospace" in degrees


def test_scott_symes_pdf_keeps_jobs_and_skills():
    from pathlib import Path

    pdf = Path(__file__).resolve().parents[2] / "test" / "resume" / "Scott-Symes-Resume-2026-10-12 (1).pdf"
    if not pdf.is_file():
        return
    text = extract_text_from_document(str(pdf))
    data = parse_resume_detailed(None, text)
    assert data["name"] == "Scott Symes"
    assert data["email"] == "scott@symes.dev"
    assert "751-5555" in data["phone"]
    assert "scott-symes" in (data.get("linkedin") or "")
    assert len(data["experience"]) >= 8
    assert all(role.get("title") and role.get("company") and role.get("duration") for role in data["experience"])
    skills = data["skills"]
    assert any(skill == "Swift" or skill.startswith("Swift") for skill in skills)
    assert "Codebases" not in skills
    assert any("Modular/Testable Codebases" in skill for skill in skills)
    assert any("GitHub Actions" in skill and "Bitrise" in skill for skill in skills)
    assert "mobile experience" in (data.get("summary") or "").lower()
    assert "languages & frameworks" not in (data.get("summary") or "").lower()
    degrees = " ".join(item.get("degree") or "" for item in data["education"])
    schools = " ".join(item.get("institution") or "" for item in data["education"])
    assert "Software Engineering" in degrees
    assert "Aerospace" in degrees
    assert "Diploma" in degrees
    assert "University of Melbourne" in schools
    assert "Spanish" not in schools


def test_html_resume_keeps_header_and_drops_style(tmp_path):
    path = tmp_path / "resume.html"
    path.write_text(
        "<html><style>.hidden { color: red }</style>"
        "<p>Ada Lovelace</p><p>ada@analytical.example</p></html>",
        encoding="utf-8",
    )
    text = extract_text_from_document(str(path))
    assert "Ada Lovelace" in text
    assert "ada@analytical.example" in text
    assert "hidden" not in text
