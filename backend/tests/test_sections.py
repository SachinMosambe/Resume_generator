from app.services.detailed_resume_parser import parse_resume_detailed
from app.services.pdf_parser import extract_text_from_document
from app.services.structured_resume_store import build_structured_resume, document_from_store


def _parse(fixtures, key):
    return parse_resume_detailed(None, extract_text_from_document(str(fixtures[key])))


def test_unknown_sections_preserved_and_not_absorbed(fixtures):
    data = _parse(fixtures, "unknown_sections")
    assert [s["title"] for s in data["additional_sections"]] == ["Publications", "Volunteering", "Patents"]
    roles = data["experience"]
    assert [(r["company"], r["title"]) for r in roles] == [("Initech", "Analyst")]
    bullets = " ".join(b for r in roles for b in r.get("description", []))
    assert "Streaming joins" not in bullets


def test_title_company_comma_headers(fixtures):
    roles = _parse(fixtures, "overlapping")["experience"]
    assert [(r["title"], r["company"]) for r in roles] == [
        ("Data Engineer", "Globex"),
        ("Part-time Instructor", "Umbrella Labs"),
        ("Analyst", "Initech"),
    ]


def test_title_with_level_number_keeps_company(fixtures):
    roles = _parse(fixtures, "long_resume")["experience"]
    assert (roles[0]["title"], roles[0]["company"]) == ("Engineer Level 0", "Company0 Ltd")
    assert len(roles) == 12


def test_promotions_comma_format_keep_all_titles(fixtures):
    roles = _parse(fixtures, "promotions")["experience"]
    assert {(r["company"], r["title"]) for r in roles} == {
        ("Acme Corp", "Software Engineer"),
        ("Acme Corp", "Senior Software Engineer"),
        ("Acme Corp", "Staff Engineer"),
    }


def test_promotions_under_one_employer_header():
    text = """Jordan Rivera
Experience
Acme Corp
Staff Engineer  Jul 2021 - Present
- Led migration to event-driven payments.
Senior Software Engineer  Jan 2019 - Jun 2021
- Owned the ledger service.
Education
B.S. Physics, Tech University, 2014
"""
    roles = parse_resume_detailed(None, text)["experience"]
    assert [(r["company"], r["title"]) for r in roles] == [
        ("Acme Corp", "Staff Engineer"),
        ("Acme Corp", "Senior Software Engineer"),
    ]


def test_odd_headings(fixtures):
    data = _parse(fixtures, "odd_headings")
    assert [(r["title"], r["company"]) for r in data["experience"]] == [("Data Engineer", "Globex")]
    assert {"Kubernetes", "Terraform"} <= set(data["skills"])


def test_references_contact_not_assigned(fixtures):
    data = _parse(fixtures, "references")
    assert data["email"] == "jordan.rivera@example.com"
    assert "8877" not in data["phone"]
    assert [s["title"] for s in data["additional_sections"]] == ["References"]
    bullets = " ".join(b for r in data["experience"] for b in r.get("description", []))
    assert "pat.manager" not in bullets


def test_document_emits_all_sections_even_if_template_omits_them():
    store = build_structured_resume({
        "experience": [{"company": "Initech", "title": "Analyst", "duration": "2015 - 2019", "description": ["x y z"]}],
        "achievements": ["Employee of the year 2018"],
        "languages": ["Spanish"],
        "additional_sections": [{"title": "Publications", "lines": ["Rivera J. Streaming joins. 2022."]}],
    })
    doc = document_from_store(store, {"section_order": ["experience"]})
    titles = [s["title"] for s in doc["sections"]]
    assert "Achievements" in titles and "Languages" in titles and "Publications" in titles


def test_references_suppressed_by_default():
    store = build_structured_resume({
        "experience": [{"company": "Initech", "title": "Analyst", "duration": "2015 - 2019", "description": ["x y z"]}],
        "additional_sections": [{"title": "References", "lines": ["Pat Manager, pat.manager@example.org"]}],
    })
    doc = document_from_store(store, {})
    assert "References" not in [s["title"] for s in doc["sections"]]
    assert doc.get("suppressed_sections") == ["References"]
    doc = document_from_store(store, {"include_references": True})
    assert "References" in [s["title"] for s in doc["sections"]]
