import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from indeed_job_parser.config import ConfigOverrides
from indeed_job_parser.pipeline import run_pipeline


def write_config(path: Path) -> None:
    path.write_text(
        '''
[search]
country = "Czech Republic"
country_code = "CZ"
location = "Prague"
queries = ["QA Engineer"]
results_per_query = 5
days_old = 14
distance_km = 50
remote_only = false

[filters]
max_experience_years = 5
include_unknown = true
min_salary = 60000
salary_currency = "CZK"
salary_period = "monthly"

[storage]
database_path = "data/jobs.db"
output_dir = "output"
'''
    )


def test_pipeline_persists_all_decisions_and_exports_selected_rows(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    def fake_scrape(**kwargs):
        frame = pd.DataFrame([
            {
                "id": "eligible",
                "site": "indeed",
                "title": "Middle QA Engineer",
                "company": "A",
                "location": "Prague",
                "job_url": "https://cz.indeed.com/viewjob?jk=eligible",
                "description": (
                    "Requirements\nPython is required.\n"
                    "Nice to have\nAWS is a plus.\n"
                    "Responsibilities\nImprove data quality with ETL pipelines."
                ),
                "min_amount": 70000,
                "max_amount": 90000,
                "currency": "CZK",
                "interval": "monthly",
            },
            {
                "id": "unknown",
                "site": "indeed",
                "title": "QA Engineer",
                "company": "B",
                "location": "Brno",
                "job_url": "https://cz.indeed.com/viewjob?jk=unknown",
                "description": "API testing",
            },
            {
                "id": "rejected",
                "site": "indeed",
                "title": "Senior QA Engineer",
                "company": "C",
                "location": "Prague",
                "job_url": "https://cz.indeed.com/viewjob?jk=rejected",
                "description": "Requires 8 years of experience.",
            },
            {
                "id": "wrong-period",
                "site": "indeed",
                "title": "Middle QA Engineer",
                "company": "D",
                "location": "Prague",
                "job_url": "https://cz.indeed.com/viewjob?jk=wrong-period",
                "description": "Automation testing",
                "min_amount": 40000,
                "max_amount": 50000,
                "currency": "CZK",
                "interval": "yearly",
            },
        ])
        frame["date_posted"] = "2026-10-10"
        return frame

    summary = run_pipeline(
        config_path, scrape_fn=fake_scrape, as_of=date(2026, 10, 19)
    )

    assert summary.rows_received == 4
    assert summary.rows_eligible == 1
    assert summary.rows_unknown == 1
    assert summary.rows_rejected == 2
    database = sqlite3.connect(tmp_path / "data/jobs.db")
    assert database.execute("SELECT count(*) FROM jobs").fetchone()[0] == 4
    assert database.execute("SELECT count(*) FROM job_observations").fetchone()[0] == 4
    assert database.execute(
        "SELECT count(*) FROM scope_jobs WHERE scope_key='country:CZ'"
    ).fetchone()[0] == 4
    assert database.execute(
        "SELECT count(*) FROM country_jobs WHERE scope_country_code='CZ'"
    ).fetchone()[0] == 4
    assert database.execute(
        "SELECT eligibility_reason FROM jobs WHERE source_job_id='wrong-period'"
    ).fetchone()[0] == "salary_period_mismatch"
    assert database.execute(
        "SELECT technology, requirement_type FROM job_technologies "
        "JOIN jobs ON jobs.id=job_technologies.job_id "
        "WHERE jobs.source_job_id='eligible' ORDER BY technology"
    ).fetchall() == [("AWS", "preferred"), ("Python", "required")]
    assert database.execute(
        "SELECT concept, requirement_type FROM job_concepts "
        "JOIN jobs ON jobs.id=job_concepts.job_id "
        "WHERE jobs.source_job_id='eligible' ORDER BY concept"
    ).fetchall() == [("Data Quality", "mentioned"), ("ETL/ELT", "mentioned")]
    database.close()
    selected = json.loads((tmp_path / "output/jobs-selected.json").read_text())
    assert [row["company"] for row in selected] == ["A", "B"]
    report = (tmp_path / "output/report.md").read_text()
    assert "[Middle QA Engineer](https://cz.indeed.com/viewjob?jk=eligible)" in report
    assert "eligible: 1" in report
    assert "unknown: 1" in report


def test_pipeline_uses_configured_role_patterns(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '''
[search]
country = "Germany"
country_code = "DE"
location = "Berlin"
queries = ["Data Engineer"]

[filters]
include_title_patterns = ["Data Engineer", "ETL Developer"]
exclude_title_patterns = ["Lead", "Manager"]
allowed_seniority = ["middle"]
max_experience_years = 5
include_unknown = true

[storage]
database_path = "data/jobs.db"
output_dir = "output"
'''
    )

    def fake_scrape(**kwargs):
        frame = pd.DataFrame([
            {
                "id": "data-1",
                "site": "indeed",
                "title": "Middle Data Engineer",
                "company": "A",
                "location": "Berlin",
                "job_url": "https://de.indeed.com/viewjob?jk=data-1",
                "description": "Requires 3 years of experience.",
            },
            {
                "id": "data-2",
                "site": "indeed",
                "title": "Senior Data Engineer",
                "company": "B",
                "location": "Berlin",
                "job_url": "https://de.indeed.com/viewjob?jk=data-2",
                "description": "Requires 4 years of experience.",
            },
        ])
        frame["date_posted"] = "2026-10-10"
        return frame

    summary = run_pipeline(
        config_path, scrape_fn=fake_scrape, as_of=date(2026, 10, 19)
    )

    assert summary.rows_eligible == 1
    assert summary.rows_rejected == 1
    selected = json.loads((tmp_path / "output/jobs-selected.json").read_text())
    assert selected[0]["title"] == "Middle Data Engineer"


def test_pipeline_applies_cli_overrides_end_to_end(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    def fake_scrape(**kwargs):
        assert kwargs["search_term"] == "Data Engineer"
        assert kwargs["country_indeed"] == "Germany"
        assert kwargs["location"] == "Berlin"
        assert kwargs["results_wanted"] == 2
        frame = pd.DataFrame([
            {
                "id": "data-cli",
                "site": "indeed",
                "title": "Data Engineer",
                "company": "CLI Company",
                "location": "Berlin",
                "job_url": "https://de.indeed.com/viewjob?jk=data-cli",
                "description": "Requires 3 years of experience.",
            }
        ])
        frame["date_posted"] = "2026-10-10"
        return frame

    summary = run_pipeline(
        config_path,
        scrape_fn=fake_scrape,
        overrides=ConfigOverrides(
            titles=("Data Engineer",),
            country="Germany",
            country_code="DE",
            location="Berlin",
            results_per_query=2,
        ),
        as_of=date(2026, 10, 19),
    )

    assert summary.rows_eligible == 1


def test_pipeline_enforces_freshness_locally_and_reports_date_quality(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)

    def fake_scrape(**kwargs):
        base = {
            "site": "indeed",
            "title": "QA Engineer",
            "company": "A",
            "location": "Prague",
            "description": "API testing",
        }
        return pd.DataFrame(
            [
                {**base, "id": "fresh", "job_url": "https://cz.indeed.com/viewjob?jk=fresh", "date_posted": "2026-10-06"},
                {**base, "id": "stale", "job_url": "https://cz.indeed.com/viewjob?jk=stale", "date_posted": "2026-10-05"},
                {**base, "id": "future", "job_url": "https://cz.indeed.com/viewjob?jk=future", "date_posted": "2026-10-20"},
                {**base, "id": "invalid", "job_url": "https://cz.indeed.com/viewjob?jk=invalid", "date_posted": "invalid"},
                {**base, "id": "missing", "job_url": "https://cz.indeed.com/viewjob?jk=missing", "date_posted": None},
            ]
        )

    summary = run_pipeline(config_path, scrape_fn=fake_scrape, as_of=date(2026, 10, 19))

    assert summary.rows_received == 5
    assert summary.rows_fresh == 1
    assert summary.rows_stale == 1
    assert summary.rows_future == 1
    assert summary.rows_invalid_date == 1
    assert summary.rows_missing_date == 1
    database = sqlite3.connect(tmp_path / "data/jobs.db")
    assert database.execute("SELECT count(*) FROM scope_jobs").fetchone()[0] == 1
    database.close()
    selected = json.loads((tmp_path / "output/jobs-selected.json").read_text())
    assert [row["source_job_id"] for row in selected] == ["fresh"]


def test_partial_collection_keeps_last_successful_scope(tmp_path: Path):
    config_path = tmp_path / "config.toml"
    write_config(config_path)
    config_path.write_text(config_path.read_text().replace(
        'queries = ["QA Engineer"]',
        'queries = ["QA Engineer", "QA Automation"]',
    ))

    def row(identifier: str):
        return pd.DataFrame([
            {
                "id": identifier,
                "site": "indeed",
                "title": "QA Engineer",
                "company": "A",
                "location": "Prague",
                "job_url": f"https://cz.indeed.com/viewjob?jk={identifier}",
                "description": "API testing",
                "date_posted": "2026-10-10",
            }
        ])

    run_pipeline(
        config_path,
        scrape_fn=lambda **kwargs: row("old"),
        as_of=date(2026, 10, 19),
    )

    def partial_scrape(**kwargs):
        if kwargs["search_term"] == "QA Automation":
            raise RuntimeError("temporary source failure")
        return row("new")

    summary = run_pipeline(
        config_path,
        scrape_fn=partial_scrape,
        as_of=date(2026, 10, 19),
    )

    assert summary.error_count == 1
    database = sqlite3.connect(tmp_path / "data/jobs.db")
    assert database.execute(
        "SELECT status FROM ingestion_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()[0] == "partial"
    assert database.execute(
        "SELECT source_job_id FROM country_jobs ORDER BY source_job_id"
    ).fetchall() == [("old",)]
    database.close()
