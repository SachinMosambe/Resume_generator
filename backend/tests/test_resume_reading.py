"""Regressions for profile-cover sheets, numeric dates, and header columns."""

from app.services.detailed_resume_parser import parse_resume_detailed
from app.services.pdf_parser import extract_text_from_document


DICE_LIKE = """
Eugene Berezin
Summary
Previous
Preferred
Location
Desired Work
Settings
Willing to Relocate
Employment Type
Total Experience
Education
Profile Source
Profile Downloaded
Ios Developer
Seattle, WA
10 years
Masters @ Moscow State Pedagogical University.
Dice

AI Solutions and Adoption Engineer
SUMMARY
Engineer with 12 years in tech who works AI-first and has driven adoption inside engineering teams at large companies.
WHAT I BRING
• AI-native workflow: daily agentic coding tools used as core infrastructure for the engineering team.
EXPERIENCE
Software Engineer — AI Tooling | Amazon — Seattle, WA Dec 2025 – Present
• Built an onboarding tool that cut new-engineer setup from days to hours.
TECHNICAL SKILLS
• Languages and data: Python, Swift, SQL
EDUCATION & CREDENTIALS
MS, Psychology — Moscow State Pedagogical University
Licensed Hypnotherapist and certified coach with formal training in facilitation.
"""

NUMERIC_DATES = """
Leif Harrison
13408 70th Dr. SE
Snohomish, WA 98296
Senior/Staff Software Engineer
leif.harrison@example.com
Summary
Senior software developer with over 15 years of experience developing mobile applications for retail and finance teams.
• Technologies: SwiftUI, UIKit, GraphQL
• Languages: Swift, Objective-C
Job History
LTM / LTIMindtree 5/2025 - present
Shake Shack - Staff Software Engineer (iOS)
• Mentoring other team members and sharing knowledge of iOS development and best practices.
Future State Consulting 7/2022 - 12/2024
Walmart - Staff Software Engineer (iOS)
• Implementation of application enhancements, including development, unit testing, and release support.
T-Mobile 12/2018 - 6/2022
Senior Software Engineer (iOS)
• Built shared frameworks used by retail mobile applications across the store network.
Deloitte Digital 01/2012 - 12/2018
Studio Lead
ConEd devices for the field team.
•
(Swift)
Education
Western Washington University
06/1994 - Bachelor of Science, Computer Science
Edmonds Community College
01/1991 - Associate of Arts and Sciences
"""


def test_profile_cover_does_not_replace_the_real_summary():
    data = parse_resume_detailed(None, DICE_LIKE)
    summary = data["summary"]
    assert "12 years" in summary
    assert "agentic coding" in summary
    assert "Willing to Relocate" not in summary
    assert "Profile Source" not in summary
    bullets = " ".join(b for role in data["experience"] for b in role["description"])
    assert "onboarding tool" in bullets
    assert "Python, Swift" not in bullets
    assert any("Moscow State" in (edu.get("institution") or "") for edu in data["education"])


def test_numeric_dates_keep_every_role_and_education():
    data = parse_resume_detailed(None, NUMERIC_DATES)
    companies = [role["company"] for role in data["experience"]]
    assert any("LTIMindtree" in company for company in companies)
    assert any("Future State" in company for company in companies)
    assert any("T-Mobile" in company for company in companies)
    assert any("Deloitte" in company for company in companies)
    assert all("5/" not in company for company in companies)
    dates = " ".join(role["duration"] for role in data["experience"])
    assert "2025" in dates and "2012" in dates and "2018" in dates
    joined = " ".join(b for role in data["experience"] for b in role["description"])
    assert "Mentoring other team members" in joined
    assert "(Swift)" in joined
    assert "Objective-C" not in joined
    assert data["languages"] == ["Swift", "Objective-C"]
    assert "SwiftUI" in data["skills"]
    assert data["headline"] == "Senior/Staff Software Engineer"
    assert "70th Dr" not in data["summary"]
    assert "15 years" in data["summary"]
    bachelor = next(edu for edu in data["education"] if "Bachelor" in edu["degree"])
    associate = next(edu for edu in data["education"] if "Associate" in edu["degree"])
    assert bachelor["degree"].startswith("Bachelor")
    assert "Western Washington" in bachelor["institution"]
    assert "1994" in bachelor["year"]
    assert "Edmonds" in associate["institution"]
    assert "1991" in associate["year"]


def test_line_break_hyphen_is_rejoined():
    text = """
Jordan Rivera
Experience
Engineer | Acme Jan 2020 - Dec 2022
• Served as primary developer maintaining/en-hancing Aperture plugins for the photo team.
• Degree note: NACES-evaluated credentials and a well-defined delivery process for the team.
Education
B.S. Computer Science, State University, 2015
"""
    data = parse_resume_detailed(None, text)
    bullets = " ".join(data["experience"][0]["description"])
    assert "enhancing" in bullets
    assert "en-hancing" not in bullets
    assert "NACES-evaluated" in bullets
    assert "well-defined" in bullets


def test_label_value_cover_is_read_by_row(tmp_path):
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    rows = [
        ("Previous", "Nurse"),
        ("Preferred", "Engineer"),
        ("Location", "Seattle, WA"),
        ("Willing to Relocate", "No"),
        ("Employment Type", "Full-time"),
        ("Profile Source", "Board"),
    ]
    y = 80.0
    for left, right in rows:
        # Values sit on the next baseline, the way a profile sheet is drawn.
        page.insert_text((50, y), left, fontsize=11)
        page.insert_text((280, y + 9), right, fontsize=11)
        y += 22
    page.insert_text((50, y + 20), "Engineer with twelve years building production mobile software for hospitals.", fontsize=11)
    path = tmp_path / "cover.pdf"
    doc.save(path)
    doc.close()
    text = extract_text_from_document(str(path))
    assert text.index("Preferred") < text.index("Engineer") < text.index("Location")
    assert text.index("Employment Type") < text.index("Full-time") < text.index("Profile Source")


def test_header_contact_stays_above_the_summary(tmp_path):
    import pymupdf as fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((50, 72), "Leif Harrison", fontsize=12)
    page.insert_text((400, 72), "13408 70th Dr. SE", fontsize=10)
    page.insert_text((400, 88), "Snohomish, WA 98296", fontsize=10)
    page.insert_text((50, 104), "Senior Software Engineer", fontsize=11)
    page.insert_text((400, 104), "leif.harrison@example.com", fontsize=10)
    page.insert_text((50, 130), "Summary", fontsize=12)
    page.insert_text(
        (50, 150),
        "Senior software developer with fifteen years of experience building mobile applications.",
        fontsize=11,
    )
    path = tmp_path / "header.pdf"
    doc.save(path)
    doc.close()
    text = extract_text_from_document(str(path))
    assert text.index("13408") < text.index("Summary")
    assert text.index("example.com") < text.index("Summary")
    assert text.index("Summary") < text.index("fifteen years")
