import pytest

from indeed_job_parser.eligibility import evaluate_job, extract_required_years


def row(title: str, description: str = "") -> dict:
    return {"title": title, "description": description}


def test_rejects_explicit_requirement_above_five_years():
    decision = evaluate_job(row("QA Automation Engineer", "At least 6 years of experience are required."), 5)
    assert decision.status == "rejected"
    assert decision.reason == "experience_above_limit"
    assert decision.required_years == 6


def test_extracts_markdown_escaped_plus_in_experience_requirement():
    assert extract_required_years(r"Experience: 7\+ years of professional experience.") == 7


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("Vous disposez de 5 ans minimum d’expérience.", 5),
        ("Minimum 6 ans d'expérience professionnelle.", 6),
        ("Mindestens 6 Jahre Berufserfahrung erforderlich.", 6),
        ("Mínimo 7 años de experiencia profesional.", 7),
        ("Almeno 4 anni di esperienza professionale.", 4),
        ("Mínimo de 3 anos de experiência profissional.", 3),
        ("Minimum 6 lat doświadczenia zawodowego.", 6),
    ],
)
def test_extracts_localized_experience_requirements(description: str, expected: int):
    assert extract_required_years(description) == expected


def test_rejects_senior_title_without_explicit_years():
    decision = evaluate_job(row("Senior QA Engineer"), 5)
    assert decision.status == "rejected"
    assert decision.reason == "senior_without_eligible_experience"


def test_accepts_senior_title_when_requirement_is_five_years():
    decision = evaluate_job(row("Senior QA Engineer", "Requires 5+ years of experience in automation."), 5)
    assert decision.status == "eligible"
    assert decision.required_years == 5


def test_plain_qa_without_experience_is_unknown():
    decision = evaluate_job(row("QA Engineer"), 5)
    assert decision.status == "unknown"
    assert decision.reason == "experience_not_stated"


def test_accepts_role_selected_by_configured_title_pattern():
    decision = evaluate_job(
        row("Senior Data Engineer", "Requires 4 years of experience."),
        5,
        include_title_patterns=("Data Engineer",),
        exclude_title_patterns=("Lead", "Manager"),
    )

    assert decision.status == "eligible"
    assert decision.required_years == 4


def test_middle_title_is_eligible_without_explicit_years():
    decision = evaluate_job(row("Middle Test Automation Engineer"), 5)
    assert decision.status == "eligible"
    assert decision.reason == "middle_level_title"


def test_middle_only_filter_rejects_other_seniority_levels():
    middle = evaluate_job(
        row("Middle Data Engineer"),
        5,
        include_title_patterns=("Data Engineer",),
        exclude_title_patterns=("Lead", "Manager"),
        allowed_seniority=("middle",),
    )
    senior = evaluate_job(
        row("Senior Data Engineer", "Requires 4 years of experience."),
        5,
        include_title_patterns=("Data Engineer",),
        exclude_title_patterns=("Lead", "Manager"),
        allowed_seniority=("middle",),
    )
    unspecified = evaluate_job(
        row("Data Engineer", "Requires 3 years of experience."),
        5,
        include_title_patterns=("Data Engineer",),
        exclude_title_patterns=("Lead", "Manager"),
        allowed_seniority=("middle",),
    )

    assert middle.status == "eligible"
    assert senior.reason == "seniority_not_allowed"
    assert unspecified.reason == "seniority_not_allowed"


def test_czech_medior_marker_in_description_is_eligible():
    decision = evaluate_job(row("Tester / QA Engineer", "Hledáme mediorního API Testera."), 5)
    assert decision.status == "eligible"
    assert decision.reason == "middle_level_description"


def test_excludes_junior_lead_and_irrelevant_titles():
    assert evaluate_job(row("Junior QA Engineer"), 5).reason == "excluded_level"
    assert evaluate_job(row("Lead QA Engineer"), 5).reason == "excluded_level"
    assert evaluate_job(row("Senior Backend Engineer", "Data quality matters."), 5).reason == "irrelevant_title"
