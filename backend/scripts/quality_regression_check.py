"""Quick regression checks for quality fixes (no Bedrock required)."""
from __future__ import annotations

from app.services.detailed_resume_parser import (
    _dedupe_experience_roles,
    _extract_bullet_list,
    _extract_name,
    _is_invalid_job_title,
    _split_skills_payload,
)
from app.services.resume_section_quality import _looks_like_bullet_as_title, _role_key
from app.services.tech_glossary import restore_tech_names


def main() -> None:
    assert _is_invalid_job_title(
        "Implemented Graph Neural Networks (GNNs) and scalable machine learning pipelines in Databricks"
    )
    assert not _is_invalid_job_title("Java Full-Stack Programmer")
    assert _looks_like_bullet_as_title(
        "Applied ITSCM and ITIL processes to diagnose and resolve incidents, collaborating with the team lead"
    )

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
    # Section finder needs a heading; wrap as full-ish text.
    certs = _extract_bullet_list(cert_blob, "certifications")
    joined = " | ".join(certs).lower()
    assert "table tennis" not in joined, certs
    assert "mentored" not in joined, certs
    assert any("natural language processing" in c.lower() for c in certs), certs

    name = _extract_name("HARKARAN SIDHU | C: | E:\nEmail: a@b.com\n")
    assert "Harkaran" in name or "HARKARAN" in name.upper(), name

    print("quality_regression_ok")


if __name__ == "__main__":
    main()
