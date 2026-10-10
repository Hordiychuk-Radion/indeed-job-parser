from indeed_job_parser.eligibility import evaluate_job


def row(title: str, description: str = "") -> dict:
    return {"title": title, "description": description}


def test_rejects_explicit_requirement_above_five_years():
    decision = evaluate_job(row("QA Automation Engineer", "At least 6 years of experience are required."), 5)
    assert decision.status == "rejected"
    assert decision.reason == "experience_above_limit"
    assert decision.required_years == 6


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


def test_middle_title_is_eligible_without_explicit_years():
    decision = evaluate_job(row("Middle Test Automation Engineer"), 5)
    assert decision.status == "eligible"
    assert decision.reason == "middle_level_title"


def test_czech_medior_marker_in_description_is_eligible():
    decision = evaluate_job(row("Tester / QA Engineer", "Hledáme mediorního API Testera."), 5)
    assert decision.status == "eligible"
    assert decision.reason == "middle_level_description"


def test_excludes_junior_lead_and_irrelevant_titles():
    assert evaluate_job(row("Junior QA Engineer"), 5).reason == "excluded_level"
    assert evaluate_job(row("Lead QA Engineer"), 5).reason == "excluded_level"
    assert evaluate_job(row("Senior Backend Engineer", "Data quality matters."), 5).reason == "irrelevant_title"
