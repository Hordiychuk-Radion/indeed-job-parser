import json
import sqlite3
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
        return pd.DataFrame([
            {
                "id": "eligible",
                "site": "indeed",
                "title": "Middle QA Engineer",
                "company": "A",
                "location": "Prague",
                "job_url": "https://cz.indeed.com/viewjob?jk=eligible",
                "description": "Automation testing",
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

    summary = run_pipeline(config_path, scrape_fn=fake_scrape)

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
        return pd.DataFrame([
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

    summary = run_pipeline(config_path, scrape_fn=fake_scrape)

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
        return pd.DataFrame([
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
    )

    assert summary.rows_eligible == 1
