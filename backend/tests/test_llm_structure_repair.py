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


def test_flag_defaults_off():
    assert Settings.model_fields["RESUME_LLM_PARSE_FALLBACK"].default is False
    assert lsr.settings.RESUME_LLM_PARSE_FALLBACK is False


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
