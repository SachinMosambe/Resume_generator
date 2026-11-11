from app.services.source_evidence import detect_employment_evidence


DICE = open(
    __file__.replace(
        "test_source_evidence.py", "fixtures/golden/cases/dice_wrapper.txt"
    ),
    encoding="utf-8",
).read()
EDU = open(
    __file__.replace(
        "test_source_evidence.py", "fixtures/golden/cases/education_only.txt"
    ),
    encoding="utf-8",
).read()
BULLET = open(
    __file__.replace(
        "test_source_evidence.py", "fixtures/golden/cases/bullet_only.txt"
    ),
    encoding="utf-8",
).read()


def test_dice_and_bullet_sources_flag_work_history():
    assert detect_employment_evidence(DICE).has_work_history is True
    assert detect_employment_evidence(BULLET).has_work_history is True


def test_education_only_has_no_work_history():
    assert detect_employment_evidence(EDU).has_work_history is False


def test_employment_type_metadata_has_no_work_history():
    source = "Employment Type\nFull-time\nEducation\nBS Computer Science 2018\n"

    assert detect_employment_evidence(source).has_work_history is False
