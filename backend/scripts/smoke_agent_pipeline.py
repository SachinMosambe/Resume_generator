"""
Smoke test for the multi-agent pipeline (no LLM required).

Run with RESUME_LLM_CONDENSE=false so every stage exercises its deterministic
path. Builds a synthetic ~20-page resume, runs the orchestrator directly, then
the full flag-gated service through DOCX rendering.

    python scripts/smoke_agent_pipeline.py
"""
from __future__ import annotations

import os
import sys
import uuid

os.environ.setdefault("RESUME_LLM_CONDENSE", "false")
os.environ.setdefault("RESUME_AGENT_PIPELINE", "true")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

COMPANIES = [
    ("Acme Corp", "Senior Software Engineer", "Jan 2021 - Present"),
    ("Globex Inc", "Software Engineer", "Mar 2018 - Dec 2020"),
    ("Initech LLC", "Backend Developer", "Jun 2016 - Feb 2018"),
    ("Umbrella Systems", "Java Developer", "Aug 2014 - May 2016"),
    ("Stark Industries", "Junior Developer", "Jul 2012 - Jul 2014"),
    ("Wayne Enterprises", "Intern Developer", "Jan 2012 - Jun 2012"),
]

BULLET_TEMPLATES = [
    "Developed microservices handling {n}k requests per day using Java and Spring Boot for the payments platform.",
    "Optimized PostgreSQL queries reducing report latency by {n}% across the analytics dashboard.",
    "Led a team of {n} engineers delivering the customer onboarding module ahead of schedule.",
    "Implemented CI/CD pipelines with Jenkins and Docker cutting release time by {n} hours.",
    "Designed REST APIs consumed by {n} internal services with strict backward compatibility.",
    "Migrated legacy monolith modules to AWS reducing infrastructure cost by {n}%.",
    "Built Kafka consumers processing {n} million events daily with exactly-once semantics.",
    "Automated regression suites in Python increasing coverage to {n}%.",
    "Architected caching layer with Redis improving p95 response time by {n}%.",
    "Mentored {n} junior developers on code review practices and system design.",
    "Delivered React dashboards visualizing {n} operational metrics for support teams.",
    "Configured Kubernetes autoscaling policies sustaining {n}x seasonal traffic spikes.",
]


def synthetic_candidate_data() -> dict:
    experience = []
    for idx, (company, title, duration) in enumerate(COMPANIES):
        bullets = [
            template.format(n=10 + idx * 3 + j)
            for j, template in enumerate(BULLET_TEMPLATES)
        ]
        experience.append(
            {
                "company": company,
                "title": title,
                "duration": duration,
                "location": "Remote",
                "description": bullets,
                "technologies": ["Java", "Spring Boot", "AWS", "PostgreSQL", "Kafka"],
            }
        )
    raw_text = "\n\n".join(
        f"{c} — {t} ({d})\n" + "\n".join(f"• {b}" for b in e["description"])
        for e, (c, t, d) in zip(experience, COMPANIES)
    )
    return {
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "phone": "+1 555 010 1234",
        "location": "Austin, TX",
        "job_role": "Senior Software Engineer",
        "client_name": "SmokeTest",
        "summary": (
            "Senior software engineer with 12+ years of experience building distributed "
            "backend systems on Java, Spring Boot, and AWS. Proven record of leading teams, "
            "optimizing high-throughput data pipelines, and delivering resilient microservices. "
            "Strong focus on observability, automation, and mentoring."
        ),
        "skills": ["Java", "Spring Boot", "AWS", "PostgreSQL", "Kafka", "Docker", "Kubernetes", "Redis", "Python", "React"],
        "skills_by_category": {
            "Languages": ["Java", "Python", "SQL", "TypeScript"],
            "Frameworks": ["Spring Boot", "React", "Hibernate"],
            "Cloud & DevOps": ["AWS", "Docker", "Kubernetes", "Jenkins"],
            "Data": ["PostgreSQL", "Kafka", "Redis"],
        },
        "experience": experience,
        "education": [
            {"degree": "Master of Science in Computer Science", "institution": "University of Texas at Austin", "year": "2012"},
            {"degree": "Bachelor of Technology in Information Technology", "institution": "Delhi Technological University", "year": "2010"},
        ],
        "certifications": ["AWS Certified Solutions Architect - Associate", "Oracle Certified Professional Java SE"],
        "projects": [],
        "achievements": [],
        "languages": ["English", "Hindi"],
        "raw_resume_text": raw_text,
    }


def main() -> int:
    from app.agent_pipeline.orchestrator import run_pipeline
    from app.services.resume_page_fitter import estimate_pages

    data = synthetic_candidate_data()

    document, state = run_pipeline(data, format_metadata=None)

    assert state.kb is not None and state.plan is not None
    pages_before = state.plan.pages_before
    pages_after = state.plan.pages_after
    print(f"KB facts: {len(state.kb.facts)}")
    print(f"Pages: {pages_before:.2f} -> {pages_after:.2f} (target {state.spec.target_pages})")
    print(f"Drafts: {len(state.drafts)}, best score: {state.best.score}")

    assert pages_before > state.spec.target_pages + 0.5, "synthetic resume should be oversized"
    assert pages_after <= pages_before, "fit must not grow the resume"

    sections = document.get("sections") or []
    exp_sections = [s for s in sections if "experience" in str(s.get("title", "")).lower()]
    assert exp_sections, "experience section missing"
    doc_companies = " ".join(
        str(r.get("company") or "") for r in exp_sections[0].get("content") or []
    )
    for company, _, _ in COMPANIES:
        assert company in doc_companies, f"role dropped: {company}"
    print(f"All {len(COMPANIES)} role identities preserved.")

    # Full service path: agent pipeline -> reliability -> DOCX bytes.
    from app.models.candidate import Candidate
    from app.services.aptino_template import build_aptino_client_format
    from app.agent_pipeline import AgentResumeGenerationService

    candidate = Candidate(
        name=data["name"],
        job_role=data["job_role"],
        client_name="SmokeTest",
        recruiter_id=uuid.uuid4(),
        email=data["email"],
        phone=data["phone"],
        location=data["location"],
        extracted_data={
            "raw_text": data["raw_resume_text"],
            "resume_text": data["raw_resume_text"],
            "education": data["education"],
            "skills": data["skills"],
            "summary": data["summary"],
        },
    )
    client_format = build_aptino_client_format("SmokeTest")
    docx_bytes = AgentResumeGenerationService().generate(candidate, client_format)
    assert docx_bytes[:2] == b"PK", "DOCX output is not a valid zip container"
    print(f"DOCX rendered: {len(docx_bytes)} bytes")
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
