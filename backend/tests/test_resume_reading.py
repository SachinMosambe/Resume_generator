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
    assert "WHAT I BRING" not in summary
    assert "agentic coding" not in summary
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


UNLABELED_SUMMARY = """
DAVID BREIG
+1 312-305-9049
david.breig@example.com
about:blank
I am a planning and reporting professional with over 30 years of experience installing and configuring enterprise systems for finance teams.
Experience with installation and configuration of planning systems on Windows and UNIX environments for large customers.
PROJECT SUMMARIES
Independent Consultant Work – Oracle EPM (December 2020 to Present)
• Led an implementation of a planning solution for a construction company.
"""


def test_cover_sheet_headline_does_not_replace_the_real_summary():
    data = parse_resume_detailed(
        None,
        """
Eugene Berezin
Summary
Previous
Preferred
Location
Willing to Relocate
Employment Type
Profile Source
AI Solutions and Adoption Engineer for customer facing delivery
SUMMARY
Engineer with 12 years in tech who works AI-first and has driven adoption inside engineering teams at large companies.
EXPERIENCE
Software Engineer | Amazon Dec 2025 – Present
• Built an onboarding tool for the engineering team.
""",
    )
    summary = data["summary"]
    assert data["summary_from_section"] is True
    assert "12 years" in summary
    assert "Adoption Engineer" not in summary
    assert "onboarding tool" not in summary


def test_unlabeled_opening_prose_becomes_the_summary():
    data = parse_resume_detailed(None, UNLABELED_SUMMARY)
    summary = data["summary"]
    assert data["summary_from_section"] is False
    assert "30 years" in summary
    assert "UNIX" in summary
    assert "PROJECT SUMMARIES" not in summary
    assert "construction company" not in summary
    bullets = " ".join(b for role in data["experience"] for b in role["description"])
    assert "construction company" in bullets
    assert "30 years" not in bullets


def test_wrapped_summary_sentence_is_not_cut_at_a_colon():
    data = parse_resume_detailed(
        None,
        """
Ada Lovelace
SUMMARY
Engineer with 12 years in tech who works AI-first and has driven AI
adoption inside engineering teams at Amazon and T-Mobile: building internal tooling for the platform group.
EXPERIENCE
Engineer | Analytical Engines Jan 2020 - Dec 2022
• Built a calculation engine for the finance team.
""",
    )
    assert "building internal tooling" in data["summary"]
    assert "calculation engine" not in data["summary"]


def test_role_line_without_a_summary_stays_empty():
    data = parse_resume_detailed(
        None,
        """
Ada Lovelace
Staff Engineer
Experience
Engineer | Analytical Engines Jan 2020 - Dec 2022
• Built a calculation engine for the finance team.
""",
    )
    assert data["summary"] == ""
    assert data["headline"] == "Staff Engineer"
    assert "calculation engine" in " ".join(data["experience"][0]["description"])


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


DELIVERY_HISTORY = """
Brett Williams
PROFESSIONAL SUMMARY
A database engineer with 15 years of experience building highly available systems for global teams.
KEY STRONG SUITS
Cloud Platforms | AWS | Azure
DELIVERY & EXECUTION
RAYTHEON (RTX)    October 2023 - Present
SQL/Cloud Subject Matter Expert
• Blueprinted an org-wide replication standard for every business unit.
PITNEY BOWES INC.    June 2018 – October 2023
Sr. Database Admin
• Recovered systems after a ransomware attack with minimal data loss.
EDUCATION & CREDENTIALS
• Bachelor of Science in Computer Science (2013)
"""


def test_employment_block_is_not_copied_into_the_summary():
    """A nonstandard work heading must not land in the summary and again as experience."""
    data = parse_resume_detailed(None, DELIVERY_HISTORY)
    summary = data["summary"]
    assert "15 years" in summary
    assert "AWS" not in summary
    assert any("AWS" in skill for skill in data["skills"])
    assert "Blueprinted" not in summary
    assert "RAYTHEON" not in summary.upper()
    assert "ransomware" not in summary.lower()
    roles = data["experience"]
    assert [r["company"] for r in roles] == ["RAYTHEON (RTX)", "PITNEY BOWES INC."]
    assert all("DELIVERY" not in (r.get("title") or "").upper() for r in roles)
    bullets = " ".join(b for role in roles for b in role["description"])
    assert "Blueprinted" in bullets
    assert "ransomware" in bullets
    assert "15 years" not in bullets


def test_brett_delivery_history_is_not_repeated():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "test"
        / "resume"
        / "Brett M Williams Resumes (1).docx"
    )
    data = parse_resume_detailed(None, extract_text_from_document(str(path)))
    assert "Blueprinted" not in data["summary"]
    bullets = " ".join(b for role in data["experience"] for b in role["description"])
    assert bullets.lower().count("blueprinted") == 1
    assert all("DELIVERY" not in (role.get("title") or "").upper() for role in data["experience"])


CLIENT_BLOCKS = """
Ravi CH
PROFESSIONAL SUMMARY
NICE CXone Consultant with 10 years of hands-on experience building cloud contact center solutions for large enterprises.
WORK EXPERIENCE:
Client: CVS Health (Remote, USA)
Role: Sr. Nice CXone Developer
Duration: Nov 2022 – Present
• Designed and enhanced complex IVR call flows for the contact center.
Client: Nationwide – Columbus, OH, USA
Role: Genesys/Nice CXone Developer Duration: Oct 2019 – Oct 2022
• Led end-to-end implementation of Genesys Cloud CX for banking clients.
EDUCATION:
• Master of Science in Computer Science
Harrisburg University - May 2016
"""


def test_all_caps_project_name_stays_the_employer():
    data = parse_resume_detailed(
        None,
        """
Ada Lovelace
Professional Summary
Engineer with 12 years of experience building calculation systems for scientific teams.
Experience
PROJECT ALPHA
Engineer    Jan 2020 - Dec 2021
• Built a calculation engine for the finance team.
""",
    )
    role = data["experience"][0]
    assert role["company"] == "PROJECT ALPHA"
    assert role["title"] == "Engineer"
    assert "calculation engine" in role["description"][0]


def test_labeled_summary_does_not_take_later_sections():
    """A named summary stays in that section. Opening-prose fallback is not used."""
    data = parse_resume_detailed(
        None,
        """
Ravi CH
I am a planning professional with over 30 years of experience installing systems for finance teams across the country.
PROFESSIONAL SUMMARY
Results-Driven Engineering Leader
NICE CXone Consultant with 10 years of hands-on experience building contact center solutions for large enterprises.
Domain Strengths
Banking healthcare telecom and retail programs for enterprise contact centers worldwide.
WORK EXPERIENCE
Client: CVS Health (Remote, USA)
Role: Sr. Nice CXone Developer
Duration: Nov 2022 – Present
• Designed and enhanced complex IVR call flows for the contact center.
""",
    )
    summary = data["summary"]
    assert data["summary_from_section"] is True
    assert "Results-Driven" in summary
    assert "10 years" in summary
    assert "30 years" not in summary
    assert "Domain Strengths" not in summary
    assert "Banking healthcare" not in summary
    assert "Designed" not in summary
    assert data["experience"][0]["company"].startswith("CVS")


def test_tools_and_competencies_stay_out_of_the_summary():
    data = parse_resume_detailed(
        None,
        """
Ravi CH
PROFESSIONAL SUMMARY:
NICE CXone Consultant with 10 years of hands-on experience building and enhancing cloud contact center solutions for large enterprises.
Experienced in creating custom CXone reports and dashboards for business teams across banking and healthcare.
Technical Tools & Platforms
Cloud Contact Center (CCaaS): NICE CXone, Genesys Cloud CX
CORE COMPETENCIES:
• NICE CXone Development (Studio Scripting, Snippets, IVR Call Flows)
• CXone Reporting, Analytics & Custom Dashboard Development
• Contact Center Solutions (IVR, Routing, Omnichannel, WEM, Outbound)
• Cloud & Data Integration (AWS, Data Lakes, Webhooks)
• Cross-functional Collaboration & Technical Leadership
WORK EXPERIENCE:
Client: CVS Health (Remote, USA)
Role: Sr. Nice CXone Developer
Duration: Nov 2022 – Present
• Designed and enhanced complex IVR call flows for the contact center.
""",
    )
    summary = data["summary"]
    assert "10 years" in summary
    assert "dashboards" in summary
    assert "Technical Tools" not in summary
    assert "CCaaS" not in summary
    assert "Contact Center Solutions" not in summary
    skills = " ".join(data["skills"])
    assert "NICE CXone" in skills
    assert "Genesys Cloud CX" in skills
    assert "Contact Center Solutions (IVR, Routing, Omnichannel, WEM, Outbound)" in skills
    assert "CXone Reporting, Analytics & Custom Dashboard Development" in skills
    assert "Cloud & Data Integration (AWS, Data Lakes, Webhooks)" in skills
    assert "Cross-functional Collaboration & Technical Leadership" in skills
    assert "•" not in " ".join(data["skills_by_category"])
    assert data["experience"][0]["company"].startswith("CVS")


def test_specific_skill_categories_keep_their_source_names():
    from app.services.resume_generation_service import ResumeGenerationService

    service = ResumeGenerationService()
    assert service._normalize_skill_category("Cloud") == "Cloud & DevOps"
    assert service._normalize_skill_category("Programming") == "Programming Languages"
    assert service._normalize_skill_category("Programming Languages") == "Programming Languages"
    assert (
        service._normalize_skill_category("Cloud Contact Center (CCaaS)")
        == "Cloud Contact Center (CCaaS)"
    )
    assert service._normalize_skill_category("Programming & Data") == "Programming & Data"
    assert service._normalize_skill_category("Core Competencies") == "Core Competencies"


def test_ravi_summary_stays_narrative_and_competencies_stay_separate():
    from io import BytesIO
    from pathlib import Path

    from docx import Document

    from app.services.aptino_template import get_aptino_default_metadata
    from app.services.resume_generation_service import ResumeGenerationService

    path = Path(__file__).resolve().parents[2] / "test" / "resume" / "Ravi_NiceOneCXResume.docx"
    text = extract_text_from_document(str(path))
    parsed = parse_resume_detailed(str(path), text)
    summary = parsed["summary"]
    assert "10 years" in summary
    assert "Technical Tools" not in summary
    assert "CCaaS" not in summary
    assert "Contact Center Solutions" not in summary

    service = ResumeGenerationService()
    metadata = get_aptino_default_metadata()
    document = service._generate_professional_document(
        {"raw_resume_text": text, **parsed},
        metadata,
    )
    summary_section = next(
        section
        for section in document["sections"]
        if "summary" in str(section.get("title") or "").lower()
    )
    summary_bits = summary_section["content"]
    summary_text = " ".join(summary_bits) if isinstance(summary_bits, list) else str(summary_bits)
    assert "10 years" in summary_text
    assert "Technical Tools" not in summary_text
    assert "CCaaS" not in summary_text
    assert "Core Competencies" not in summary_text

    skills = next(section for section in document["sections"] if section.get("type") == "skills")
    grouped = skills["content"]
    assert "Cloud Contact Center (CCaaS)" in grouped
    assert "Programming & Data" in grouped
    assert "Cloud & DevOps" not in grouped
    competencies = grouped["Core Competencies"]
    assert len(competencies) >= 8
    assert any("Cloud & Data Integration" in item for item in competencies)

    rendered = Document(BytesIO(service._render_docx(document, metadata, [])))
    lines = [para.text.strip() for para in rendered.paragraphs if para.text.strip()]
    competency_heading = next(line for line in lines if line.startswith("Core Competencies"))
    assert "IVR Call Flows" not in competency_heading
    assert any("Cloud & Data Integration" in line and "Core Competencies" not in line for line in lines)
    assert any(line.startswith("Cloud Contact Center (CCaaS)") for line in lines)
    assert not any(line.startswith("Cloud & DevOps") for line in lines)


def test_client_role_duration_blocks_are_not_split():
    data = parse_resume_detailed(None, CLIENT_BLOCKS)
    roles = [(r["company"], r["title"], r["duration"]) for r in data["experience"]]
    assert roles == [
        ("CVS Health (Remote, USA)", "Sr. Nice CXone Developer", "Nov 2022 – Present"),
        ("Nationwide – Columbus, OH, USA", "Genesys/Nice CXone Developer", "Oct 2019 – Oct 2022"),
    ]
    assert "Designed" in data["experience"][0]["description"][0]
    assert "implementation" in data["experience"][1]["description"][0]


def test_wrapped_summary_keeps_the_closing_city():
    from app.services.docx_layout import summary_to_bullets

    text = (
        "Senior iOS Engineer with 9+ years of mobile experience scaling mission-critical apps "
        "to 8M+ daily check-ins and cutting development cycles by 40% through agentic AI workflows. "
        "Expert in offline-sync architecture, performance optimization (reducing load times by 7.5s), and\n"
        "and government digital services. U.S. Green Card holder based in\nSeattle."
    )
    joined = " ".join(summary_to_bullets(text))
    assert "and and" not in joined
    assert "based in Seattle" in joined
    assert "offline-sync architecture" in joined
    assert "cutting development cycles by 40%" in joined


def test_competency_with_a_comma_stays_one_skill():
    from app.services.resume_generation_service import ResumeGenerationService

    skills = ResumeGenerationService()._clean_skill_list(
        ["CXone Reporting, Analytics & Custom Dashboard Development", "Python, Java, SQL"]
    )
    assert "CXone Reporting, Analytics & Custom Dashboard Development" in skills
    assert "Python" in skills and "Java" in skills and "SQL" in skills


def test_same_employer_and_dates_stay_one_job_when_the_title_is_trimmed():
    from app.services.resume_generation_service import ResumeGenerationService

    full = (
        "Information Technology Project Analyst – Executive | "
        "Barclays Digital Asset Management System Support"
    )
    short = "Information Technology Project Analyst – Executive"
    bullets = ["Managed and resolved technical issues using ServiceNow."]
    items = [
        {
            "company": "Microland Ltd., Gurugram",
            "title": short,
            "duration": "April 2016 to August 2016",
            "description": bullets * 5,
        },
        {
            "company": "Microland Ltd., Gurugram",
            "title": full,
            "duration": "April 2016 to August 2016",
            "description": bullets * 4,
        },
    ]
    out = ResumeGenerationService()._dedupe_experience_items(items)
    assert len(out) == 1
    assert "Barclays" in out[0]["title"]


def test_role_title_with_a_project_name_is_not_a_bullet():
    from app.services.resume_section_quality import _looks_like_bullet_as_title

    assert not _looks_like_bullet_as_title(
        "Information Technology Project Analyst – Executive | "
        "Barclays Digital Asset Management System Support"
    )
    assert not _looks_like_bullet_as_title("Sr. Database Admin | Director of Cloud Engineering")


def test_a_long_achievement_is_not_split_into_extra_bullets():
    from app.services.structured_resume_store import expand_to_bullets

    bullet = (
        "Led enterprise-wide migration of legacy SQL databases to Azure SQL, modernizing the data infrastructure. "
        "Optimized performance and reduced operational costs by 35%. "
        "Developed automated migration scripts that processed 5,000+ databases with minimal downtime."
    )
    assert expand_to_bullets([bullet]) == [bullet]


def test_month_duration_stays_off_the_employer_name():
    data = parse_resume_detailed(
        None,
        """
WORK EXPERIENCE
PACE Bus (Arlington Heights, IL) - 12 Month Duration (Mar 2014 – Mar 2015)
Hyperion Planning Implementation with data sourced from Oracle ERP
• Gathered requirements for the planning model and trained the finance team.
""",
    )
    company = data["experience"][0]["company"]
    assert "PACE Bus" in company
    assert "Duration" not in company


def test_references_and_certificates_leave_education():
    data = parse_resume_detailed(
        None,
        """
EDUCATION
Bachelor of Science – Accounting
DePaul University
CERTIFICATIIONS
Hyperion Planning Implementation Certified
Hyperion Essbase Implementation Certified

EDUCATION & CREDENTIALS
• Bachelor of Science in Computer Science
State University
2013
MCSE Certification (pending renewal)
References available upon request. Please send an email – thanks!
""",
    )
    details = " ".join(
        str(item)
        for row in data["education"]
        for item in (row.get("details") or [])
    )
    assert "References available" not in details
    assert "Hyperion Planning Implementation Certified" not in details
    assert "Hyperion Planning Implementation Certified" in data["certifications"]
    assert "Hyperion Essbase Implementation Certified" in data["certifications"]
    degrees = " ".join(row.get("degree") or "" for row in data["education"])
    assert "()" not in degrees
    assert "•" not in degrees
