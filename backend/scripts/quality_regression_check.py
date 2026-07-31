"""Quick regression checks for quality fixes (no Bedrock required)."""
from __future__ import annotations

import re

from app.services.detailed_resume_parser import (
    _DATE_PATTERN,
    _dedupe_experience_roles,
    _extract_bullet_list,
    _extract_education,
    _extract_experience,
    _extract_name,
    _is_invalid_job_title,
    _parse_job_header_line,
    _split_skills_payload,
)
from app.services.resume_section_quality import _looks_like_bullet_as_title, _role_key
from app.services.tech_glossary import restore_tech_names


def main() -> None:
    assert _is_invalid_job_title(
        "Implemented Graph Neural Networks (GNNs) and scalable machine learning pipelines in Databricks"
    )
    assert not _is_invalid_job_title("Java Full-Stack Programmer")
    assert _is_invalid_job_title("across squads.")
    assert _looks_like_bullet_as_title(
        "Applied ITSCM and ITIL processes to diagnose and resolve incidents, collaborating with the team lead"
    )
    assert _looks_like_bullet_as_title("across squads.")

    roles = _dedupe_experience_roles(
        [
            {
                "company": "American International Group(AIG)",
                "title": "",
                "duration": "February 2018 to March 2018",
                "description": ["a"],
            },
            {
                "company": "American International Group(AIG)",
                "title": "Full-Stack Software Engineer",
                "duration": "February 2018 to March 2018",
                "description": ["a", "b", "c"],
            },
            {
                "company": "Microland Ltd., Gurugram",
                "title": "",
                "duration": "April 2016 to August 2016",
                "description": ["x"],
            },
            {
                "company": "Microland Ltd., Gurugram",
                "title": "Information Technology Project Analyst",
                "duration": "April 2016 to August 2016",
                "description": ["x", "y"],
            },
        ]
    )
    assert len(roles) == 2, roles
    assert roles[0]["title"]
    assert roles[1]["title"]

    assert _role_key("AIG Inc", "Aug 2018 - Mar 2019") == _role_key("AIG", "August 2018 to March 2019")

    text = restore_tech_names("multi-model routing across Groq, OpenRouter, and AWS AWS AWS Bedrock.")
    assert "AWS AWS" not in text, text
    assert "AWS Bedrock" in text, text
    text2 = restore_tech_names("integrated with bedrock and Spring AI")
    assert "AWS Bedrock" in text2, text2
    spaced = restore_tech_names(
        "Mule Soft, Spring Web Flux, You tube, Rx JS, g RPC, Io T, 5 G, Angular JS, "
        "HTML 5, CSS 3, Service Now, DB 2, J 2 EE, K 8 s, Open Shift, Web Sphere"
    )
    for good in (
        "MuleSoft",
        "WebFlux",
        "YouTube",
        "RxJS",
        "gRPC",
        "IoT",
        "5G",
        "AngularJS",
        "HTML5",
        "CSS3",
        "ServiceNow",
        "DB2",
        "J2EE",
        "K8s",
        "OpenShift",
        "WebSphere",
    ):
        assert good in spaced, spaced

    wrap_exp = """PROFESSIONAL EXPERIENCE
Verizon Communications January 2021 to September 2022
Irving, TX
Technology Lead| IVAPP Platform & IOT Development Project
Built responsive micro-frontend applications using Angular.
Vanguard August 2019 to January 2021
Malvern, PA
Technology Lead| Vanguard Participant Experience Project
Architected Spring Boot microservices.
Adnig Technologies - Rai-Power, Gurugram June 2013 to September 2014
Haryana, India
Jr. Java Back-End Engineer | Rai-Power In-House Project | Java payment gateway
Environment: Java, J2EE, Spring, Hibernate, DB2
"""
    exp2 = _extract_experience(wrap_exp)
    verizon = next(r for r in exp2 if "Verizon" in str(r.get("company") or ""))
    assert "Technology Lead" in str(verizon.get("title") or ""), verizon
    adnig = next(r for r in exp2 if "Adnig" in str(r.get("company") or ""))
    assert "Java" in str(adnig.get("title") or ""), adnig
    assert not any(str(b).lower().startswith("environment:") for b in (adnig.get("description") or []))

    parts = _split_skills_payload("AWS (EC2, S3, Bedrock), Docker, LangSmith")
    assert parts[0].startswith("AWS ("), parts

    cert_blob = """CERTIFICATIONS
Machine Learning Specialization (Deep Learning.AI)
Natural Language Processing
Specialization (Deep Learning.AI)
Led 200-participant conference as Core Committee Member at IIT Kharagpur
Mentored 60+ students as Teaching Assistant
Doubles Championship in Table Tennis at Kalpana Chawla Trophy, GCOEA (2019)
"""
    certs = _extract_bullet_list(cert_blob, "certifications")
    joined = " | ".join(certs).lower()
    assert "table tennis" not in joined, certs
    assert "mentored" not in joined, certs
    assert any(
        "natural language processing" in c.lower() and "specialization" in c.lower() for c in certs
    ), certs

    name = _extract_name("HARKARAN SIDHU | C: | E:\nEmail: a@b.com\n")
    assert "Harkaran" in name or "HARKARAN" in name.upper(), name

    dm = _DATE_PATTERN.search("Staff Engineer — AI/ML | Nagarro India July 2025 – Present")
    assert dm
    parsed = _parse_job_header_line("Staff Engineer — AI/ML | Nagarro India July 2025 – Present", dm)
    assert "Staff Engineer" in parsed["title"], parsed
    assert "Nagarro" in parsed["company"], parsed

    edu_text = """EDUCATION
Master of Technology(M.Tech) in Infrastructure Design Management|CGPA:9.09/10 Aug 2022—May 2024
Indian Institute of Technology(IIT) Kharagpur
Bachelor of Technology(B.Tech) in Civil Engineering|CGPA:8.16/10 Aug 2017—May 2021
Government College of Engineering Amravati
"""
    edu = _extract_education(edu_text)
    assert len(edu) >= 2, edu
    assert any("Kharagpur" in str(e.get("institution") or "") for e in edu), edu
    assert any("Amravati" in str(e.get("institution") or "") for e in edu), edu
    assert any("Government College of Engineering" in str(e.get("institution") or "") for e in edu), edu

    mashed_edu = """EDUCATION
Bachelorof Technology(B.Tech) in Civil Engineering|CGPA:8.16/10 Aug 2017—May 2021
Government Collegeof Engineering Amravati
Masterof Technology(M.Tech) in Infrastructure Design Management|CGPA:9.09/10 Aug 2022—May 2024
Indian Instituteof Technology(IIT) Kharagpur
"""
    mashed = _extract_education(mashed_edu)
    assert any("Amravati" in str(e.get("institution") or "") for e in mashed), mashed
    assert any("Kharagpur" in str(e.get("institution") or "") for e in mashed), mashed

    # Achievements must keep "Award" / "leadership" wording — cert bleed strip
    # must not chop them mid-phrase.
    achiev_text = """ACHIEVEMENTS
• A-Team Award, Nagarro — Recognized 3x for exceptional performance and measurable team contributions.
• Cheer Board Nominations, Nagarro — Acknowledged 6x for innovative AI ideas and outstanding individual impact.
• NAGP (Nagarro Accelerated Growth Program) — Designated top performer demonstrating exceptional leadership and business impact.
"""
    achievs = _extract_bullet_list(achiev_text, "achievements")
    assert any("A-Team Award" in a and "Recognized 3x" in a for a in achievs), achievs
    assert any("leadership and business impact" in a for a in achievs), achievs
    assert all(not a.rstrip().endswith("exceptional") for a in achievs), achievs

    wrap_exp = """PROFESSIONAL EXPERIENCE
Staff Engineer — AI/ML | Nagarro India July 2025 – Present
• Mentor 8+ junior and mid-level engineers on ML best practices
across squads.
Associate Staff Engineer — AI/ML | Nagarro India Jan 2024 – July 2025
• Built an NLP-driven document classification system.
"""
    exp = _extract_experience(wrap_exp)
    assert all("across squads" not in str(r.get("title") or "").lower() for r in exp), exp
    assert any("across squads" in " ".join(r.get("description") or []).lower() for r in exp), exp

    # Silence unused import warning in some linters.
    assert re is not None

    # --- FormatSchema + format validator gates (no Bedrock) ---
    from app.models.format_schema import normalize_format_metadata, parse_hex_rgb
    from app.services.aptino_template import get_aptino_default_metadata
    from app.services.format_validator import (
        document_section_types,
        has_critical_findings,
        validate_format_document,
    )
    from app.agent_pipeline.state import FormatSpec

    aptino = get_aptino_default_metadata()
    assert isinstance(aptino.get("section_order"), list)
    assert all(isinstance(s, str) and not str(s).isdigit() for s in aptino["section_order"]), aptino[
        "section_order"
    ]
    assert aptino["styling"]["font_family"]
    assert aptino["styling"]["color_text"].startswith("#")
    assert aptino.get("completeness_contract")

    normalized = normalize_format_metadata(
        {
            "sections": ["summary", "experience", "skills"],
            "section_order": [0, 1, 2],  # legacy indices must be ignored
            "styling": {"font_family": "Arial", "font_size_body": 11, "color_text": "112233"},
            "source_type": "docx",
        }
    )
    assert normalized["section_order"] == ["summary", "experience", "skills"], normalized["section_order"]
    assert normalized["styling"]["color_text"] == "#112233"
    assert parse_hex_rgb("#FF5050") == (255, 80, 80)

    good_doc = {
        "header": {"name": "Jane Doe", "contact": ["jane@example.com"]},
        "sections": [
            {"type": "summary", "title": "PROFESSIONAL SUMMARY", "content": "Leader."},
            {"type": "skills", "title": "SKILL SET OVERVIEW", "content": {"Languages": ["Python"]}},
            {
                "type": "education",
                "title": "EDUCATIONAL DETAILS",
                "content": [{"degree": "BS", "institution": "State U", "year": "2019"}],
            },
            {
                "type": "experience",
                "title": "WORK EXPERIENCE",
                "content": [{"company": "Acme", "title": "Engineer", "duration": "2020-2024"}],
            },
        ],
    }
    findings_ok = validate_format_document(good_doc, FormatSpec.from_metadata(aptino))
    assert not has_critical_findings(findings_ok), findings_ok
    assert document_section_types(good_doc)[:2] == ["summary", "skills"]

    bad_order = {
        "header": {"name": "Jane Doe", "contact": ["a@b.c"]},
        "sections": [
            {"type": "experience", "title": "EXPERIENCE", "content": [{"company": "Acme"}]},
            {"type": "summary", "title": "SUMMARY", "content": "x"},
            {"type": "skills", "title": "SKILLS", "content": ["Python"]},
            {"type": "education", "title": "EDUCATION", "content": [{"degree": "BS"}]},
        ],
    }
    findings_bad = validate_format_document(bad_order, FormatSpec.from_metadata(aptino))
    assert has_critical_findings(findings_bad), findings_bad

    # Baseline: Aptino metadata must keep required sections contract for regression.
    required = set(aptino.get("completeness_contract") or [])
    assert {"summary", "skills", "experience", "education"} <= required

    # --- Content preservation: page-fit must keep unique tech/info root ---
    from app.services.resume_page_fitter import _select_bullets, fit_store_to_pages
    from app.services.resume_llm_condense import _backfill_bullets, _merge_condensed, _role_lost_too_much_detail

    unique_bullets = [
        "Implemented GraphQL federation across order and inventory services.",
        "Led migration of MuleSoft Anypoint APIs to AWS EKS with Terraform.",
        "Mentored junior engineers on code reviews and delivery practices.",
        "Improved sprint predictability through refined estimation workshops.",
        "Collaborated with product managers on roadmap prioritization.",
        "Documented runbooks for on-call incident response.",
        "Participated in weekly architecture sync with platform teams.",
        "Supported QA with regression planning for release trains.",
    ]
    selected = _select_bullets(unique_bullets, quota=4)
    selected_blob = " ".join(selected).lower()
    assert "mulesoft" in selected_blob and "graphql" in selected_blob, selected

    long_store = {
        "summary": "Senior engineer with deep platform experience across APIs, cloud, and delivery. "
        * 8,
        "skills_by_category": {"Cloud": ["AWS", "EKS", "Terraform", "MuleSoft"]},
        "skills": ["AWS", "EKS", "Terraform", "MuleSoft"],
        "experience": [
            {
                "company": f"Company {i}",
                "title": "Senior Engineer",
                "duration": f"202{i}-01 to 202{i}-12",
                "description": unique_bullets + [f"Delivered feature set {j} for platform reliability." for j in range(8)],
                "technologies": ["AWS", "MuleSoft", "Terraform"],
            }
            for i in range(5)
        ],
        "education": [{"degree": "BS CS", "institution": "State University", "year": "2015"}],
        "projects": [],
        "certifications": [],
        "achievements": [],
    }
    fitted = fit_store_to_pages(long_store, target_pages=3.5)
    assert len(fitted.get("experience") or []) == 5
    kept_bullets = sum(len(r.get("description") or []) for r in fitted["experience"])
    assert kept_bullets >= 25, kept_bullets
    fitted_blob = " ".join(
        " ".join(r.get("description") or []) for r in fitted["experience"]
    ).lower()
    assert "mulesoft" in fitted_blob, fitted_blob[:500]

    # Merge must reject over-summarized LLM roles and restore source density.
    source_role = {
        "company": "Acme",
        "title": "Engineer",
        "duration": "2020-2024",
        "description": unique_bullets[:6],
        "technologies": ["MuleSoft", "GraphQL", "AWS"],
    }
    thin_llm = {
        "summary": "Engineer with cloud experience across APIs and delivery platforms.",
        "experience": [
            {
                "company": "Acme",
                "title": "Engineer",
                "duration": "2020-2024",
                "description": ["Worked on cloud APIs and mentoring."],
                "technologies": ["AWS"],
            }
        ],
        "skills_by_category": {},
        "education": [],
    }
    assert _role_lost_too_much_detail(unique_bullets[:6], thin_llm["experience"][0]["description"])
    merged = _merge_condensed({"experience": [source_role], "summary": "x" * 200, "skills_by_category": {}}, thin_llm)
    assert merged is not None
    assert len(merged["experience"][0]["description"]) >= 4, merged["experience"][0]["description"]
    assert "mulesoft" in " ".join(merged["experience"][0]["description"]).lower()

    backfilled = _backfill_bullets(
        ["Led migration of MuleSoft Anypoint APIs to AWS EKS with Terraform."],
        unique_bullets[:5],
        max_bullets=5,
    )
    assert len(backfilled) >= 4, backfilled

    print("quality_regression_ok")


if __name__ == "__main__":
    main()
