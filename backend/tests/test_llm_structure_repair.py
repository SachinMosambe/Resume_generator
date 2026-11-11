"""Optional LLM structure repair: all LLM calls are stubbed."""
from __future__ import annotations

import copy

from app.core.config import Settings
from app.services import llm_structure_repair as lsr
from app.services.llm_structure_repair import is_repair_eligible, maybe_repair_parse
from app.services.parse_confidence import score_parse

SOURCE = """Jane Doe
EXPERIENCE
Senior Engineer
Acme Inc 2020 - Present
• Built the billing pipeline for enterprise clients.
• Reduced deploy time by 40 percent.
Developer
Beta LLC 2017 - 2019
• Maintained the legacy reporting service.
EDUCATION
B.S. Computer Science
"""


def _weak_parse(**over):
    data = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S. Computer Science"}]}
    data.update(over)
    data["parse_meta"] = score_parse(data, SOURCE)
    return data


def _good_repair():
    return {
        "experience": [
            {
                "title": "Senior Engineer",
                "company": "Acme Inc",
                "location": "",
                "duration": "2020 - Present",
                "description": [
                    "Built the billing pipeline for enterprise clients.",
                    "Reduced deploy time by 40 percent.",
                ],
            },
            {
                "title": "Developer",
                "company": "Beta LLC",
                "location": "",
                "duration": "2017 - 2019",
                "description": ["Maintained the legacy reporting service."],
            },
        ]
    }


def _stub(payload, calls=None):
    def client(system_prompt, user_prompt):
        if calls is not None:
            calls.append(1)
        return payload

    return client


def test_accepts_schema_valid_source_backed_repair():
    parsed = _weak_parse()
    assert is_repair_eligible(SOURCE, parsed)
    calls: list[int] = []
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair(), calls))
    assert calls == [1]
    assert out["parse_meta"]["llm_repaired"] is True
    assert [r["company"] for r in out["experience"]] == ["Acme Inc", "Beta LLC"]
    assert out["experience"][1]["description"] == ["Maintained the legacy reporting service."]
    assert out["parse_meta"]["confidence"] > parsed["parse_meta"]["confidence"]
    assert out["name"] == "Jane Doe" and out["education"] == parsed["education"]
    assert parsed["experience"] == [] and parsed["parse_meta"]["llm_repaired"] is False


def test_accepts_json_string_response_and_clears_placed_unassigned_bullets():
    parsed = _weak_parse(unassigned_experience_bullets=["Reduced deploy time by 40 percent."])
    import json

    out = maybe_repair_parse(SOURCE, parsed, client=_stub(json.dumps(_good_repair())))
    assert out["parse_meta"]["llm_repaired"] is True
    assert "unassigned_experience_bullets" not in out


def test_rejects_fabricated_employer():
    bad = _good_repair()
    bad["experience"][0]["company"] = "Globex Corporation"
    parsed = _weak_parse()
    before = copy.deepcopy(parsed)
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out == before
    assert out["parse_meta"]["llm_repaired"] is False


def test_rejects_fabricated_bullet_title_and_date():
    for mutate in (
        lambda r: r["experience"][0]["description"].append("Led a team of 50 engineers."),
        lambda r: r["experience"][0].update(title="Chief Technology Officer"),
        lambda r: r["experience"][0].update(duration="2010 - 2012"),
    ):
        bad = _good_repair()
        mutate(bad)
        parsed = _weak_parse()
        out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
        assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False


def test_rejects_bullet_wrong_employer():
    bad = _good_repair()
    # Real bullet from the source, but it belongs under Beta LLC, not Acme Inc.
    bad["experience"][0]["description"].append("Maintained the legacy reporting service.")
    bad["experience"][1]["description"] = []
    parsed = _weak_parse()
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out["experience"] == []
    assert out["parse_meta"]["llm_repaired"] is False


def test_rejects_when_existing_verified_facts_dropped():
    parsed = _weak_parse(
        experience=[
            {
                "title": "",
                "company": "Acme Inc",
                "description": ["Built the billing pipeline for enterprise clients."],
            },
            {"title": "", "company": "Beta LLC", "description": []},
        ]
    )
    assert is_repair_eligible(SOURCE, parsed)
    bad = _good_repair()
    bad["experience"][0]["description"] = ["Reduced deploy time by 40 percent."]
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out["parse_meta"]["llm_repaired"] is False
    assert out["experience"][0]["description"] == ["Built the billing pipeline for enterprise clients."]
    # Keeping everything verified, and resolving the titles, is accepted.
    ok = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair()))
    assert ok["parse_meta"]["llm_repaired"] is True
    assert [r["title"] for r in ok["experience"]] == ["Senior Engineer", "Developer"]


def test_rejects_schema_invalid_output():
    for payload in ({"experience": "nope"}, {"experience": [{"company": 5}]}, "not json", None, {}):
        parsed = _weak_parse()
        out = maybe_repair_parse(SOURCE, parsed, client=_stub(payload))
        assert out is parsed


def test_unavailable_client_keeps_deterministic():
    def boom(system_prompt, user_prompt):
        raise TimeoutError("bedrock down")

    parsed = _weak_parse()
    before = copy.deepcopy(parsed)
    out = maybe_repair_parse(SOURCE, parsed, client=boom)
    assert out is parsed and out == before
    assert out["parse_meta"]["llm_repaired"] is False


def test_default_client_failure_keeps_deterministic(monkeypatch):
    import app.agents.tools.llm_client as llm_client

    def fail(*args, **kwargs):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(llm_client, "llm_call_json_with_metrics", fail)
    parsed = _weak_parse()
    assert maybe_repair_parse(SOURCE, parsed) is parsed


def test_education_only_not_eligible():
    src = "Jane Doe\nEDUCATION\nB.S. Computer Science, State University 2016\n"
    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
    parsed["parse_meta"] = score_parse(parsed, src)
    assert not is_repair_eligible(src, parsed)
    calls: list[int] = []
    out = maybe_repair_parse(src, parsed, client=_stub(_good_repair(), calls))
    assert out is parsed and calls == []


def test_healthy_parse_not_eligible():
    parsed = _weak_parse(experience=_good_repair()["experience"])
    parsed["parse_meta"] = score_parse(parsed, SOURCE)
    assert parsed["parse_meta"]["confidence"] == 1.0
    assert not is_repair_eligible(SOURCE, parsed)


def test_unresolved_titles_eligible():
    roles = [
        {"title": "", "company": "Acme Inc", "description": []},
        {"title": "", "company": "Beta LLC", "description": []},
    ]
    parsed = _weak_parse(experience=roles)
    assert "source_backed_titles_unresolved" in parsed["parse_meta"]["reasons"]
    assert is_repair_eligible(SOURCE, parsed)


def test_already_repaired_not_repeated():
    parsed = _weak_parse()
    once = maybe_repair_parse(SOURCE, parsed, client=_stub(_good_repair()))
    calls: list[int] = []
    again = maybe_repair_parse(SOURCE, once, client=_stub(_good_repair(), calls))
    assert again is once and calls == []


def test_flag_defaults_on_for_accuracy():
    assert Settings.model_fields["RESUME_LLM_PARSE_FALLBACK"].default is True


def test_generation_service_skips_repair_when_flag_off(monkeypatch):
    from types import SimpleNamespace

    from app.services import resume_generation_service as svc

    called = []
    monkeypatch.setattr(lsr, "maybe_repair_parse", lambda *a, **k: called.append(1))
    monkeypatch.setattr(svc.settings, "RESUME_LLM_PARSE_FALLBACK", False)
    candidate = SimpleNamespace(
        id="c1", extracted_data={"raw_text": SOURCE}, resume_path=None, name="Jane Doe"
    )
    try:
        svc.ResumeGenerationService()._get_detailed_resume_data(candidate)
    except Exception:
        pass  # downstream merge needs a full Candidate; only the repair call matters here
    assert called == []


def test_generation_service_calls_repair_once_when_flag_on(monkeypatch):
    from types import SimpleNamespace

    from app.services import resume_generation_service as svc

    calls = []

    def fake(source, parsed, **kwargs):
        calls.append(source)
        return parsed

    monkeypatch.setattr(lsr, "maybe_repair_parse", fake)
    monkeypatch.setattr(svc.settings, "RESUME_LLM_PARSE_FALLBACK", True)
    candidate = SimpleNamespace(
        id="c1", extracted_data={"raw_text": SOURCE}, resume_path=None, name="Jane Doe"
    )
    try:
        svc.ResumeGenerationService()._get_detailed_resume_data(candidate)
    except Exception:
        pass
    assert len(calls) == 1


def test_rejects_invented_range_from_other_roles_years():
    # "2017" belongs to Beta LLC and "Present" to Acme Inc; "2017 - Present" never appears together.
    bad = _good_repair()
    bad["experience"][1]["duration"] = "2017 - Present"
    parsed = _weak_parse()
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False


def test_accepts_contiguous_duration_with_different_punctuation():
    good = _good_repair()
    good["experience"][0]["duration"] = "2020 – Present"
    out = maybe_repair_parse(SOURCE, _weak_parse(), client=_stub(good))
    assert out["parse_meta"]["llm_repaired"] is True


def test_survival_keeps_verified_duration_location_technologies():
    parsed = _weak_parse(
        experience=[
            {
                "title": "",
                "company": "Acme Inc",
                "location": "Remote",
                "duration": "2020 - Present",
                "technologies": ["Python", "AWS"],
                "description": ["Built the billing pipeline for enterprise clients."],
            },
            {"title": "", "company": "Beta LLC", "duration": "2017 - 2019", "description": []},
        ]
    )
    assert is_repair_eligible(SOURCE, parsed)
    repair = _good_repair()  # omits location / technologies; "Remote" is not even in the source
    repair["experience"][0]["duration"] = ""
    repair["experience"][1]["duration"] = ""
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(repair))
    assert out["parse_meta"]["llm_repaired"] is True
    acme, beta = out["experience"]
    assert acme["title"] == "Senior Engineer"
    assert acme["duration"] == "2020 - Present"
    assert acme["location"] == "Remote"
    assert acme["technologies"] == ["Python", "AWS"]
    assert beta["duration"] == "2017 - 2019"
    assert beta["technologies"] == []


def test_repair_cannot_replace_verified_duration_or_location_with_other_roles_values():
    source = """Jane Doe
EXPERIENCE
Senior Engineer
Acme Inc | Remote | 2020 - Present
• Built the billing pipeline for enterprise clients.
Developer
Beta LLC | New York | 2017 - 2019
• Maintained the legacy reporting service.
"""
    parsed = _weak_parse(
        experience=[
            {
                "title": "",
                "company": "Acme Inc",
                "location": "Remote",
                "duration": "2020 - Present",
                "description": ["Built the billing pipeline for enterprise clients."],
            },
            {
                "title": "",
                "company": "Beta LLC",
                "location": "New York",
                "duration": "2017 - 2019",
                "description": ["Maintained the legacy reporting service."],
            },
        ]
    )
    parsed["parse_meta"] = score_parse(parsed, source)
    repair = {
        "experience": [
            {
                "title": "Senior Engineer",
                "company": "Acme Inc",
                "location": "New York",
                "duration": "2017 - 2019",
                "description": ["Built the billing pipeline for enterprise clients."],
            },
            {
                "title": "Developer",
                "company": "Beta LLC",
                "location": "New York",
                "duration": "2017 - 2019",
                "description": ["Maintained the legacy reporting service."],
            },
        ]
    }

    out = maybe_repair_parse(source, parsed, client=_stub(repair))

    assert out["experience"][0]["duration"] == "2020 - Present"
    assert out["experience"][0]["location"] == "Remote"


MENTION_SOURCE = """Jane Doe
EXPERIENCE
Senior Engineer
Acme Inc 2020 - Present
• Migrated services away from Beta LLC infrastructure.
• Reduced deploy time by 40 percent.
Developer
Beta LLC 2017 - 2019
• Maintained the legacy reporting service.
EDUCATION
B.S. Computer Science
"""


def _mention_repair():
    return {
        "experience": [
            {
                "title": "Senior Engineer",
                "company": "Acme Inc",
                "duration": "2020 - Present",
                "description": [
                    "Migrated services away from Beta LLC infrastructure.",
                    "Reduced deploy time by 40 percent.",
                ],
            },
            {
                "title": "Developer",
                "company": "Beta LLC",
                "duration": "2017 - 2019",
                "description": ["Maintained the legacy reporting service."],
            },
        ]
    }


def test_company_mentioned_in_other_roles_bullet_does_not_split_block():
    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
    parsed["parse_meta"] = score_parse(parsed, MENTION_SOURCE)
    out = maybe_repair_parse(MENTION_SOURCE, parsed, client=_stub(_mention_repair()))
    assert out["parse_meta"]["llm_repaired"] is True
    assert out["experience"][0]["description"][1] == "Reduced deploy time by 40 percent."


def test_rejects_bullet_under_employer_only_mentioned_in_another_bullet():
    bad = _mention_repair()
    # Acme's second bullet sits after the "Beta LLC" mention inside Acme's own bullet;
    # it must not be treated as Beta LLC's block.
    moved = bad["experience"][0]["description"].pop()
    bad["experience"][1]["description"].append(moved)
    parsed = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
    parsed["parse_meta"] = score_parse(parsed, MENTION_SOURCE)
    out = maybe_repair_parse(MENTION_SOURCE, parsed, client=_stub(bad))
    assert out["experience"] == [] and out["parse_meta"]["llm_repaired"] is False


# ---------------------------------------------------------------------------
# Hybrid accuracy upgrades: broader eligibility + stronger source checks
# ---------------------------------------------------------------------------

def _healthy_with_meta(confidence, reasons):
    parsed = _weak_parse(experience=_good_repair()["experience"])
    parsed["parse_meta"] = {"confidence": confidence, "reasons": list(reasons)}
    return parsed


def test_eligible_at_confidence_065_with_work_history():
    assert lsr.ELIGIBILITY_CONFIDENCE == 0.70
    assert is_repair_eligible(SOURCE, _healthy_with_meta(0.65, []))


def test_not_eligible_at_or_above_threshold_without_reasons():
    assert not is_repair_eligible(SOURCE, _healthy_with_meta(0.70, []))
    assert not is_repair_eligible(SOURCE, _healthy_with_meta(0.9, []))


def test_ambiguous_role_assignment_reason_is_eligible():
    assert is_repair_eligible(SOURCE, _healthy_with_meta(0.80, ["ambiguous_role_assignment"]))


def test_role_identity_garbled_reason_is_eligible_with_roles():
    assert is_repair_eligible(SOURCE, _healthy_with_meta(0.80, ["role_identity_garbled"]))


def test_expected_experience_missing_reason_needs_work_evidence():
    parsed = _weak_parse()
    parsed["parse_meta"] = {"confidence": 0.9, "reasons": ["expected_experience_missing"]}
    assert is_repair_eligible(SOURCE, parsed)
    src = "Jane Doe\nEDUCATION\nB.S. Computer Science, State University 2016\n"
    edu = {"name": "Jane Doe", "experience": [], "education": [{"degree": "B.S."}]}
    edu["parse_meta"] = {"confidence": 0.9, "reasons": ["expected_experience_missing"]}
    assert not is_repair_eligible(src, edu)


def test_reason_based_eligibility_still_skips_already_repaired():
    parsed = _healthy_with_meta(0.80, ["ambiguous_role_assignment"])
    parsed["parse_meta"]["llm_repaired"] = True
    assert not is_repair_eligible(SOURCE, parsed)


def test_rejects_paraphrased_bullet_sharing_a_few_words():
    for fake in (
        "Built the billing pipeline for large enterprise customers worldwide.",
        "Built the billing pipeline for enterprise clients and mentored five junior engineers.",
        "Cut deployment time substantially across the platform.",
    ):
        bad = _good_repair()
        bad["experience"][0]["description"][0] = fake
        parsed = _weak_parse()
        out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
        assert out is parsed and out["parse_meta"]["llm_repaired"] is False


def test_rejects_company_matching_only_when_letters_are_collapsed():
    bad = _good_repair()
    bad["experience"][0]["company"] = "Ac meInc"  # alnum-collapsed "acmeinc" is in the source
    parsed = _weak_parse()
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out is parsed and out["parse_meta"]["llm_repaired"] is False


def test_rejects_title_words_not_contiguous_in_source():
    bad = _good_repair()
    bad["experience"][0]["title"] = "Engineer Senior"
    parsed = _weak_parse()
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out is parsed and out["parse_meta"]["llm_repaired"] is False


def test_rejects_one_or_two_char_single_token_company():
    bad = _good_repair()
    bad["experience"][1]["company"] = "Be"  # substring of "Beta" but 2-char junk
    parsed = _weak_parse()
    out = maybe_repair_parse(SOURCE, parsed, client=_stub(bad))
    assert out is parsed and out["parse_meta"]["llm_repaired"] is False


def test_system_prompt_demands_verbatim_copy():
    prompt = lsr._SYSTEM_PROMPT.lower()
    assert "verbatim" in prompt and "paraphrase" in prompt and "invent" in prompt
