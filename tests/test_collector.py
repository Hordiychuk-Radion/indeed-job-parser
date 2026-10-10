import pandas as pd

from indeed_job_parser.collector import collect_indeed
from indeed_job_parser.config import SearchConfig


def config() -> SearchConfig:
    return SearchConfig(
        country="Czech Republic",
        country_code="CZ",
        location="Prague",
        queries=("QA Engineer", "Data Quality Analyst"),
        results_per_query=7,
        days_old=10,
        distance_km=80,
        remote_only=False,
        job_type="fulltime",
    )


def test_collects_each_query_independently_with_expected_jobspy_parameters():
    calls = []

    def fake_scrape(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{"id": kwargs["search_term"], "title": kwargs["search_term"]}])

    rows, errors = collect_indeed(config(), scrape_fn=fake_scrape)

    assert errors == []
    assert len(rows) == 2
    assert [call["search_term"] for call in calls] == ["QA Engineer", "Data Quality Analyst"]
    assert all(call["site_name"] == "indeed" for call in calls)
    assert all(call["country_indeed"] == "Czech Republic" for call in calls)
    assert all(call["location"] == "Prague" for call in calls)
    assert all(call["distance"] == 50 for call in calls)  # JobSpy expects miles; config stores kilometres
    assert all(call["hours_old"] == 240 for call in calls)


def test_preserves_successful_query_when_another_query_fails():
    def fake_scrape(**kwargs):
        if kwargs["search_term"] == "QA Engineer":
            raise RuntimeError("rate limited")
        return pd.DataFrame([{"id": "ok", "title": "Data Quality Analyst"}])

    rows, errors = collect_indeed(config(), scrape_fn=fake_scrape)

    assert len(rows) == 1
    assert errors == ["QA Engineer: RuntimeError: rate limited"]
