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
