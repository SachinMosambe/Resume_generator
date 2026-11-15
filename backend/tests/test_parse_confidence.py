from app.services.parse_confidence import score_parse


def test_missing_experience_with_evidence_lowers_confidence():
    src = "EXPERIENCE\nAcme Inc 2020 - Present\n• did things\n"
    meta = score_parse({"name": "A B", "experience": []}, src)
    assert "expected_experience_missing" in meta["reasons"]
    assert meta["confidence"] <= 0.5
    assert meta["llm_repaired"] is False


def test_unassigned_bullets_flag_ambiguity_not_missing():
    src = "EXPERIENCE\nAcme Inc 2020 - Present\n• did things\n"
    meta = score_parse({"name": "A B", "experience": [], "unassigned_experience_bullets": ["did things"]}, src)
    assert "ambiguous_role_assignment" in meta["reasons"]
    assert "expected_experience_missing" not in meta["reasons"]


def test_no_evidence_no_penalty():
    meta = score_parse({"name": "A B", "experience": []}, "EDUCATION\nB.S. X\n")
    assert meta["reasons"] == []
    assert meta["confidence"] == 1.0


def test_tech_name_flags_identity():
    meta = score_parse({"name": "React Native.", "experience": []}, "SKILLS\nPython\n")
    assert "identity_ambiguous" in meta["reasons"]


def test_empty_titles_flagged():
    data = {"name": "A B", "experience": [{"title": "", "company": "X"}, {"title": "", "company": "Y"}]}
    meta = score_parse(data, "EXPERIENCE\nX 2020 - 2021\nY 2019 - 2020\n")
    assert "source_backed_titles_unresolved" in meta["reasons"]


def test_structured_store_carries_parse_meta_and_unassigned_bullets():
    from app.services.structured_resume_store import apply_store_to_candidate_data, build_structured_resume

    data = {
        "name": "A B",
        "experience": [],
        "unassigned_experience_bullets": ["Shipped the checklist in 2021."],
        "parse_meta": {"confidence": 0.65, "reasons": ["ambiguous_role_assignment"], "llm_repaired": False},
    }
    store = build_structured_resume(data)
    assert store["experience"] == []
    assert store["unassigned_experience_bullets"] == ["Shipped the checklist in 2021."]
    assert store["parse_meta"]["reasons"] == ["ambiguous_role_assignment"]
    merged = apply_store_to_candidate_data({}, store)
    assert merged["parse_meta"]["confidence"] == 0.65
    assert merged["unassigned_experience_bullets"] == ["Shipped the checklist in 2021."]


def test_garbled_role_identity_and_overlap_are_flagged():
    src = "EXPERIENCE\nAcme 2020 - Present\n• did things\n"
    date_company = {"name": "A B", "experience": [{"company": "2021 – Present", "title": "Analyst"}]}
    assert "role_identity_garbled" in score_parse(date_company, src)["reasons"]
    same = {"name": "A B", "experience": [{"company": "Analyst", "title": "Analyst"}]}
    assert "role_identity_garbled" in score_parse(same, src)["reasons"]
    ok = {"name": "A B", "experience": [{"company": "Litware", "title": "Analyst", "duration": "2020 – 2021"}]}
    assert "role_identity_garbled" not in score_parse(ok, src)["reasons"]
    overlap = {
        "name": "A B",
        "experience": [
            {"company": "Litware", "title": "A", "duration": "Jan 2020 – Present"},
            {"company": "Fabrikam", "title": "D", "duration": "Jun 2021 – Dec 2022"},
        ],
    }
    assert "overlapping_role_dates" in score_parse(overlap, src)["reasons"]
    sequential = {
        "name": "A B",
        "experience": [
            {"company": "Litware", "title": "A", "duration": "Jan 2020 – Dec 2020"},
            {"company": "Fabrikam", "title": "D", "duration": "Jan 2021 – Dec 2022"},
        ],
    }
    assert "overlapping_role_dates" not in score_parse(sequential, src)["reasons"]


def test_unassigned_bullets_alongside_roles_flag_ambiguity():
    src = "EXPERIENCE\nAcme Inc 2020 - Present\n• did things\n"
    data = {"name": "A B", "experience": [{"company": "Acme", "title": "X"}], "unassigned_experience_bullets": ["b"]}
    assert "ambiguous_role_assignment" in score_parse(data, src)["reasons"]
from app.services.structured_resume_store import (
    UNASSIGNED_ROLE_TITLE,
    attach_unassigned_experience,
    document_from_store,
)


def test_unassigned_bullets_render_under_review_placeholder_role():
    store = {
        "header": {"name": "A B"},
        "experience": [{"company": "Acme", "title": "Analyst", "duration": "2020", "description": ["x y z w"]}],
        "unassigned_experience_bullets": ["Closed the monthly books."],
    }
    doc = attach_unassigned_experience(document_from_store(store, {}), store, {})
    exp = next(s for s in doc["sections"] if s["type"] == "experience")
    assert [r["title"] for r in exp["content"]] == ["Analyst", UNASSIGNED_ROLE_TITLE]
    assert exp["content"][-1]["company"] == "" and exp["content"][-1]["description"] == ["Closed the monthly books."]
    attach_unassigned_experience(doc, store, {})  # idempotent (same bullets)
    assert len(exp["content"]) == 2
    store_more = {**store, "unassigned_experience_bullets": ["Closed the monthly books.", "Filed Q3 taxes."]}
    attach_unassigned_experience(doc, store_more, {})  # refresh bullets on existing placeholder
    assert exp["content"][-1]["description"] == ["Closed the monthly books.", "Filed Q3 taxes."]
    assert len(exp["content"]) == 2


def test_unassigned_bullets_create_experience_section_when_no_roles():
    store = {"header": {"name": "A B"}, "experience": [], "unassigned_experience_bullets": ["Closed the books."]}
    doc = attach_unassigned_experience(document_from_store(store, {}), store, {})
    exp = [s for s in doc["sections"] if s["type"] == "experience"]
    assert len(exp) == 1 and exp[0]["content"][0]["description"] == ["Closed the books."]
    clean = attach_unassigned_experience(document_from_store({"header": {}}, {}), {"header": {}}, {})
    assert not [s for s in clean["sections"] if s["type"] == "experience"]
