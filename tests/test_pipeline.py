import json
import sqlite3
from pathlib import Path

import pandas as pd

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
        ])

    summary = run_pipeline(config_path, scrape_fn=fake_scrape)

    assert summary.rows_received == 3
    assert summary.rows_eligible == 1
    assert summary.rows_unknown == 1
    assert summary.rows_rejected == 1
    database = sqlite3.connect(tmp_path / "data/jobs.db")
    assert database.execute("SELECT count(*) FROM jobs").fetchone()[0] == 3
    assert database.execute("SELECT count(*) FROM job_observations").fetchone()[0] == 3
    database.close()
    selected = json.loads((tmp_path / "output/jobs-selected.json").read_text())
    assert [row["company"] for row in selected] == ["A", "B"]
    report = (tmp_path / "output/report.md").read_text()
    assert "[Middle QA Engineer](https://cz.indeed.com/viewjob?jk=eligible)" in report
    assert "eligible: 1" in report
    assert "unknown: 1" in report
