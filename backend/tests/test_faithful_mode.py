from app.services.structured_resume_store import (
    build_structured_resume,
    expand_to_bullets,
    normalize_education_entries,
)
from tests.fixtures.build_fixtures import LONG_ROLES


def test_store_keeps_every_bullet():
    bullets = [f"Delivered outcome number {i} for the platform team." for i in range(35)]
    store = build_structured_resume(
        {"experience": [{"company": "Acme", "title": "Engineer", "duration": "2019 - 2021", "description": bullets}]}
    )
    assert len(store["experience"][0]["description"]) == 35


def test_short_bullets_are_not_dropped():
    assert expand_to_bullets(["Team lead", "On-call"]) == ["Team lead", "On-call"]


def test_education_keeps_all_details():
    rows = normalize_education_entries(
        [
            {
                "degree": "B.S. Physics",
                "institution": "Tech University",
                "year": "2014",
                "details": ["Honours", "Minor in Mathematics", "Dean's list 2012", "Thesis on optics"],
            }
        ]
    )
    assert len(rows[0]["details"]) == 4


def test_faithful_generation_does_not_summarize(fixtures, monkeypatch):
    from app.services import resume_generation_service as rgs
    from app.services.detailed_resume_parser import parse_resume_detailed
    from app.services.pdf_parser import extract_text_from_document

    called = {"fit": False, "llm": False}

    def fake_fit(store):
        called["fit"] = True
        return store

    def fake_llm(store, **_):
        called["llm"] = True
        return None

    monkeypatch.setattr(rgs, "moderate_summarize_store", fake_fit)
    monkeypatch.setattr(rgs, "polish_store_for_readability", fake_llm)
    text = extract_text_from_document(str(fixtures["long_resume"]))
    candidate_data = {"raw_resume_text": text, **parse_resume_detailed(None, text)}
    doc = rgs.ResumeGenerationService()._generate_professional_document(candidate_data, {})
    assert called == {"fit": False, "llm": False}
    exp = next(s for s in doc["sections"] if s.get("type") == "experience")
    assert len(exp["content"]) == len(LONG_ROLES)
    assert sum(len(r.get("description") or []) for r in exp["content"]) == sum(n for *_, n in LONG_ROLES)
