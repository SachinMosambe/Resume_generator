"""Grounded line extraction: the model answers with line numbers; code copies and checks."""
from __future__ import annotations

from app.services import llm_line_extractor
from app.services.llm_line_extractor import (
    apply_line_extraction,
    extract_experience,
    lines_to_bullets,
)

RESUME = "\n".join(
    [
        "Jane Candidate",  # 1
        "jane@example.com",  # 2
        "Where I have worked",  # 3  (heading the rule parser does not know)
        "Acme Corp",  # 4
        "(Senior Engineer) 01/2018 - Present",  # 5
        "• Built the billing platform used by",  # 6
        "every customer in the region.",  # 7
        "• Cut deploy time to ten minutes.",  # 8
        "Globex",  # 9
        "(Engineer) 06/2015 - 12/2017",  # 10
        "• Maintained the order system.",  # 11
        "Volunteered at the food bank.",  # 12  (no role claims it)
        "Education",  # 13
        "B.S. Computer Science, State University",  # 14
    ]
)

SECTIONS = {"sections": [{"line": 1, "type": "header"}, {"line": 3, "type": "experience"}, {"line": 13, "type": "education"}]}


def _role(title, company, dates, header, content, **extra):
    return {
        "title": title,
        "company": company,
        "dates": dates,
        "location": None,
        "header_lines": header,
        "content": content,
        **extra,
    }


def fake_client(roles_payload):
    def call(system_prompt, user_prompt):
        if "label the sections" in system_prompt:
            return SECTIONS
        return roles_payload

    return call


GOOD_ROLES = {
    "roles": [
        _role({"line": 5, "text": "Senior Engineer"}, {"line": 4, "text": "Acme Corp"},
              {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]]),
        _role({"line": 10, "text": "Engineer"}, {"line": 9, "text": "Globex"},
              {"line": 10, "text": "06/2015 - 12/2017"}, [9, 10], [[11, 11]]),
    ]
}


def test_roles_are_copied_from_cited_lines():
    result = extract_experience(RESUME, fake_client(GOOD_ROLES))

    assert [(r["title"], r["company"], r["duration"]) for r in result.roles] == [
        ("Senior Engineer", "Acme Corp", "01/2018 - Present"),
        ("Engineer", "Globex", "06/2015 - 12/2017"),
    ]
    # Wrapped bullet rejoined; text is the source's, not the model's.
    assert result.roles[0]["description"] == [
        "Built the billing platform used by every customer in the region.",
        "Cut deploy time to ten minutes.",
    ]


def test_lines_go_to_the_job_whose_header_is_above_them():
    result = extract_experience(RESUME, fake_client(GOOD_ROLES))

    # The model's content range for Globex stopped at line 11; line 12 still sits under it.
    assert result.roles[1]["description"] == ["Maintained the order system.", "Volunteered at the food bank."]
    assert result.unassigned == []
    assert result.claimed_lines == result.experience_lines


def test_line_above_the_first_job_header_is_kept_as_unassigned():
    text = RESUME.replace("Where I have worked\n", "Where I have worked\nSelected consulting work across retail clients\n")
    sections = {"sections": [{"line": 1, "type": "header"}, {"line": 3, "type": "experience"}, {"line": 14, "type": "education"}]}
    roles = {"roles": [_role({"line": 6, "text": "Senior Engineer"}, {"line": 5, "text": "Acme Corp"}, None, [5, 6], [])]}

    def call(system_prompt, user_prompt):
        return sections if "label the sections" in system_prompt else roles

    result = extract_experience(text, call)

    assert result.unassigned == ["Selected consulting work across retail clients"]


def test_label_lines_are_structure_not_bullets():
    text = "Experience\nAcme Corp | Engineer | 2019 - Present\nResponsibilities:\n• Built the billing platform."
    sections = {"sections": [{"line": 1, "type": "experience"}]}
    roles = {"roles": [_role({"line": 2, "text": "Engineer"}, {"line": 2, "text": "Acme Corp"},
                             {"line": 2, "text": "2019 - Present"}, [2], [])]}

    def call(system_prompt, user_prompt):
        return sections if "label the sections" in system_prompt else roles

    result = extract_experience(text, call)

    assert result.roles[0]["description"] == ["Built the billing platform."]
    assert result.unassigned == []


def test_invented_text_is_rejected_field_by_field():
    payload = {
        "roles": [
            _role({"line": 5, "text": "Principal Architect"},  # not on line 5
                  {"line": 4, "text": "Acme Corp"}, {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]]),
        ]
    }
    result = extract_experience(RESUME, fake_client(payload))

    assert result.roles[0]["title"] == ""
    assert result.roles[0]["company"] == "Acme Corp"
    assert result.rejected_fields == 1


def test_out_of_range_line_is_rejected():
    payload = {"roles": [_role(None, {"line": 99, "text": "Acme Corp"}, None, [], [[6, 8]])]}
    result = extract_experience(RESUME, fake_client(payload))

    assert result.roles == []
    assert result.rejected_fields == 1
    assert len(result.unassigned) >= 2  # its lines were not lost


def test_a_line_belongs_to_one_role_only():
    payload = {
        "roles": [
            GOOD_ROLES["roles"][0],
            _role({"line": 10, "text": "Engineer"}, {"line": 9, "text": "Globex"}, None, [9, 10], [[6, 11]]),
        ]
    }
    result = extract_experience(RESUME, fake_client(payload))

    # Globex's model range [6, 11] overlapped Acme; position decides instead.
    assert result.roles[0]["description"] == [
        "Built the billing platform used by every customer in the region.",
        "Cut deploy time to ten minutes.",
    ]
    assert result.roles[1]["description"] == ["Maintained the order system.", "Volunteered at the food bank."]


def test_rule_parse_kept_when_model_fails():
    parsed = {"experience": [{"title": "X", "company": "Y", "duration": "2019", "description": []}], "parse_meta": {}}

    def broken(system_prompt, user_prompt):
        raise TimeoutError("bedrock down")

    out = apply_line_extraction(RESUME, parsed, client=broken)

    assert out["experience"] == parsed["experience"]
    assert out["parse_meta"]["line_extract"]["used"] is False


def test_model_roles_used_when_rule_parse_found_none():
    parsed = {"experience": [], "parse_meta": {}}
    out = apply_line_extraction(RESUME, parsed, client=fake_client(GOOD_ROLES))

    assert out["parse_meta"]["line_extract"]["used"] is True
    assert [r["company"] for r in out["experience"]] == ["Acme Corp", "Globex"]
    assert "unassigned_experience_bullets" not in out


def test_apply_uses_non_lumped_llm_role_when_rule_has_zero_and_coverage_is_weak(monkeypatch):
    text = "\n".join([
        "Experience",
        "Selected client engagements",
        "Cloud transformation program",
        "Senior Engineer",
        "• Built the billing platform.",
    ])
    sections = {"sections": [{"line": 1, "type": "experience"}]}
    roles = {"roles": [_role({"line": 4, "text": "Senior Engineer"}, None, None, [4], [[5, 5]])]}

    def call(system_prompt, user_prompt):
        return sections if "label the sections" in system_prompt else roles

    monkeypatch.setattr(llm_line_extractor, "_experience_coverage", lambda *_args: 0.5)
    out = apply_line_extraction(text, {"experience": [], "parse_meta": {}}, client=call)

    assert out["parse_meta"]["line_extract"]["gate_passed"] is False
    assert out["parse_meta"]["line_extract"]["used"] is True
    assert [role["title"] for role in out["experience"]] == ["Senior Engineer"]


def test_dates_copied_into_title_and_company_are_removed():
    text = "Experience\nTechnical Project Manager (Jul’ 14 – Present)\nInfosys – Rosemead Jul. ’14 to\nPresent\n• Led delivery."
    sections = {"sections": [{"line": 1, "type": "experience"}]}
    roles = {"roles": [_role({"line": 2, "text": "Technical Project Manager (Jul’ 14 – Present)"},
                             {"line": 3, "text": "Infosys – Rosemead Jul. ’14 to"},
                             {"line": 3, "text": "Jul. ’14 to"}, [2, 3, 4], [[5, 5]])]}

    def call(system_prompt, user_prompt):
        return sections if "label the sections" in system_prompt else roles

    role = extract_experience(text, call).roles[0]

    assert role["title"] == "Technical Project Manager"
    assert role["company"] == "Infosys – Rosemead"
    assert role["duration"] == "Jul. ’14 to Present"  # end date read from the next line


def test_title_that_repeats_the_company_is_blanked():
    payload = {"roles": [_role({"line": 4, "text": "Acme Corp"}, {"line": 4, "text": "Acme Corp"},
                               {"line": 5, "text": "01/2018 - Present"}, [4, 5], [[6, 8]])]}
    role = extract_experience(RESUME, fake_client(payload)).roles[0]

    assert role["title"] == ""
    assert role["company"] == "Acme Corp"


def test_lumped_result_does_not_replace_a_good_rule_parse():
    lumped = {"roles": [_role({"line": 5, "text": "Senior Engineer"}, {"line": 4, "text": "Acme Corp"},
                              None, [4, 5], [[6, 12]])]}
    rule_roles = [
        {"title": "Senior Engineer", "company": "Acme Corp", "duration": "01/2018 - Present",
         "description": ["Built the billing platform used by every customer in the region.",
                         "Cut deploy time to ten minutes."]},
        {"title": "Engineer", "company": "Globex", "duration": "06/2015 - 12/2017",
         "description": ["Maintained the order system.", "Volunteered at the food bank."]},
    ]
    out = apply_line_extraction(RESUME, {"experience": rule_roles, "parse_meta": {}}, client=fake_client(lumped))

    assert out["experience"] == rule_roles
    assert out["parse_meta"]["line_extract"]["lumped"] is True


def test_lines_the_rule_parse_placed_elsewhere_are_not_reassigned():
    parsed = {
        "experience": [],
        "additional_sections": [{"title": "Volunteering", "lines": ["Volunteered at the food bank."]}],
        "parse_meta": {},
    }
    out = apply_line_extraction(RESUME, parsed, client=fake_client(GOOD_ROLES))

    assert "unassigned_experience_bullets" not in out
    assert out["parse_meta"]["line_extract"]["llm_coverage"] == 1.0


def test_missed_job_is_retried_with_the_dated_line_named():
    # First read merges Globex into Acme; the gate sees line 10's date range outside any
    # heading and retries, naming that line.
    merged = {"roles": [GOOD_ROLES["roles"][0]]}
    prompts: list[str] = []

    def call(system_prompt, user_prompt):
        if "label the sections" in system_prompt:
            return SECTIONS
        prompts.append(user_prompt)
        return GOOD_ROLES if "NOTE: lines 10" in user_prompt else merged

    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)
    info = out["parse_meta"]["line_extract"]

    assert len(prompts) == 2
    assert info["attempts"] == 2 and info["gate_passed"] is True
    assert [r["company"] for r in out["experience"]] == ["Acme Corp", "Globex"]


def test_clean_read_is_not_retried():
    calls: list[str] = []

    def call(system_prompt, user_prompt):
        calls.append(system_prompt[:20])
        return SECTIONS if "label the sections" in system_prompt else GOOD_ROLES

    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)

    assert len(calls) == 2  # one section map + one role chunk
    assert out["parse_meta"]["line_extract"]["attempts"] == 1


def test_better_attempt_is_kept_when_retry_is_worse():
    good_then_bad = iter([{"roles": [GOOD_ROLES["roles"][0]]}, {"roles": []}])

    def call(system_prompt, user_prompt):
        return SECTIONS if "label the sections" in system_prompt else next(good_then_bad)

    out = apply_line_extraction(RESUME, {"experience": [], "parse_meta": {}}, client=call)

    assert out["parse_meta"]["line_extract"]["attempts"] == 2
    assert [r["company"] for r in out["experience"]] == ["Acme Corp"]


def test_lone_bullet_glyph_starts_a_new_bullet():
    assert lines_to_bullets(["• First item", "•", "Second item", "wraps here"]) == [
        "First item",
        "Second item wraps here",
    ]
