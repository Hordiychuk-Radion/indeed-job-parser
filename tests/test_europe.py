import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from indeed_job_parser.europe import EuropeCountry, collect_europe_data_engineers
from indeed_job_parser.models import JobRecord
from indeed_job_parser.repository import JobRepository


def test_europe_collection_keeps_attempt_snapshots_and_exports_clickable_selected_jobs(
    tmp_path: Path,
):
    calls = []

    def fake_scrape(**kwargs):
        calls.append(kwargs)
        if kwargs["results_wanted"] == 2:
            return pd.DataFrame(
                [
                    {
                        "id": "data-1",
                        "site": "indeed",
                        "title": "Senior Data Engineer",
                        "company": "Example",
                        "location": "Berlin, DE",
                        "description": "Build Python and SQL pipelines with Airflow on AWS",
                        "job_url": "https://de.indeed.com/viewjob?jk=data-1&utm_source=test",
                    },
                    {
                        "id": "other-1",
                        "site": "indeed",
                        "title": "Prison Officer",
                        "company": "Other",
                        "location": "Berlin, DE",
                        "description": "The application data is processed securely",
                        "job_url": "https://de.indeed.com/viewjob?jk=other-1",
                    },
                ]
            )
        return pd.DataFrame(
            [
                {
                    "id": "data-1",
                    "site": "indeed",
                    "title": "Senior Data Engineer",
                    "company": "Example",
                    "location": "Berlin, DE",
                    "description": "Build Python and SQL pipelines with Airflow on AWS",
                    "job_url": "https://de.indeed.com/viewjob?jk=data-1",
                }
            ]
        )

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(2, 4),
        days_old=3650,
        scrape_fn=fake_scrape,
        run_id="test-run",
    )

    assert [call["results_wanted"] for call in calls] == [2, 4]
    assert all(call["country_indeed"] == "Germany" for call in calls)
    assert summary.countries_completed == 1
    assert summary.raw_unique_jobs == 2
    assert summary.selected_data_engineers == 1
    assert summary.error_count == 0
    assert summary.database_path == str(tmp_path / "jobs.db")

    with sqlite3.connect(summary.database_path) as connection:
        stored = connection.execute(
            "SELECT title, description, eligibility, eligibility_reason FROM jobs ORDER BY title"
        ).fetchall()
        observations = connection.execute("SELECT count(*) FROM job_observations").fetchone()[0]
        technologies = connection.execute(
            "SELECT category, technology FROM job_technologies "
            "JOIN jobs ON jobs.id = job_technologies.job_id "
            "WHERE jobs.source_job_id='data-1' ORDER BY category, technology"
        ).fetchall()
    assert stored == [
        (
            "Senior Data Engineer",
            "Build Python and SQL pipelines with Airflow on AWS",
            "eligible",
            "title_matches_data_engineer",
        ),
    ]
    assert observations == 1
    assert technologies == [
        ("cloud", "AWS"),
        ("languages", "Python"),
        ("languages", "SQL"),
        ("orchestration_transformation", "Apache Airflow"),
    ]

    snapshots = tmp_path / "snapshots" / "germany" / "test-run"
    assert (snapshots / "limit-2.json").exists()
    assert (snapshots / "limit-4.json").exists()
    largest = json.loads((tmp_path / "snapshots" / "germany" / "largest-batch.json").read_text())
    assert largest["metadata"]["unique_jobs"] == 2

    selected = json.loads((tmp_path / "jobs-selected.json").read_text())
    assert selected == [
        {
            "title": "Senior Data Engineer",
            "company": "Example",
            "location": "Berlin, DE",
            "country_code": "DE",
            "published_at": None,
            "employment_type": None,
            "is_remote": None,
            "url": "https://de.indeed.com/viewjob?jk=data-1",
            "stack": {
                "languages": ["Python", "SQL"],
                "cloud": ["AWS"],
                "data_platforms": [],
                "processing_streaming": [],
                "orchestration_transformation": ["Apache Airflow"],
                "databases": [],
                "devops": [],
                "analytics_bi": [],
            },
            "stack_flat": ["Python", "SQL", "AWS", "Apache Airflow"],
        }
    ]
    report = (tmp_path / "report.md").read_text()
    summary_payload = json.loads((tmp_path / "summary.json").read_text())
    assert summary_payload["technology_counts"] == {
        "Python": 1,
        "SQL": 1,
        "AWS": 1,
        "Apache Airflow": 1,
    }
    assert "## Technology stack" in report
    assert "Python: **1**" in report
    assert "[Senior Data Engineer](https://de.indeed.com/viewjob?jk=data-1)" in report
    assert "Stack: Python, SQL, AWS, Apache Airflow" in report
    assert "Prison Officer" not in report


def test_europe_collection_replaces_reused_database_with_current_selected_jobs(tmp_path: Path):
    database_path = tmp_path / "jobs.db"
    with JobRepository(database_path) as repository:
        run_id = repository.start_run({"mode": "legacy"})
        rejected_id = repository.save_job(
            run_id,
            JobRecord(
                dedupe_key="legacy-rejected",
                source="indeed",
                source_job_id="legacy-rejected",
                query="Data Engineer",
                title="Prison Officer",
                company="Other",
                location="Berlin",
                country_code="DE",
                description="Mentions Python",
                canonical_url="https://de.indeed.com/viewjob?jk=legacy-rejected",
                published_at=None,
                employment_type=None,
                is_remote=None,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                salary_period=None,
                eligibility="rejected",
                eligibility_reason="title_not_data_engineer",
            ),
            {"legacy": True},
        )
        repository.replace_job_technologies(rejected_id, {"languages": ["Python"]})
        stale_eligible_id = repository.save_job(
            run_id,
            JobRecord(
                dedupe_key="stale-eligible",
                source="indeed",
                source_job_id="stale-eligible",
                query="Data Engineer",
                title="Data Engineer",
                company="Old",
                location="Paris",
                country_code="FR",
                description="Build Java pipelines",
                canonical_url="https://fr.indeed.com/viewjob?jk=stale-eligible",
                published_at=None,
                employment_type=None,
                is_remote=None,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                salary_period=None,
                eligibility="eligible",
                eligibility_reason="title_matches_data_engineer",
            ),
            {"legacy": True},
        )
        repository.replace_job_technologies(stale_eligible_id, {"languages": ["Java"]})

    def fake_scrape(**_kwargs):
        return pd.DataFrame(
            [{
                "id": "data-1",
                "site": "indeed",
                "title": "Data Engineer",
                "company": "Example",
                "location": "Berlin",
                "description": "Build SQL pipelines",
                "job_url": "https://de.indeed.com/viewjob?jk=data-1",
            }]
        )

    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        scrape_fn=fake_scrape,
        run_id="selected-only",
        database_path=database_path,
    )

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT source_job_id FROM jobs").fetchall() == [("data-1",)]
        for old_id in (rejected_id, stale_eligible_id):
            assert connection.execute(
                "SELECT count(*) FROM job_observations WHERE job_id=?", (old_id,)
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT count(*) FROM job_technologies WHERE job_id=?", (old_id,)
            ).fetchone()[0] == 0


def test_largest_batch_is_not_reused_across_different_freshness_scopes(tmp_path: Path):
    def fake_scrape(**kwargs):
        count = kwargs["results_wanted"]
        return pd.DataFrame(
            [
                {
                    "id": f"job-{index}",
                    "site": "indeed",
                    "title": "Data Engineer",
                    "company": "Example",
                    "location": "Berlin, DE",
                    "description": "Build pipelines",
                    "job_url": f"https://de.indeed.com/viewjob?jk=job-{index}",
                }
                for index in range(count)
            ]
        )

    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(2,),
        days_old=30,
        scrape_fn=fake_scrape,
        run_id="thirty-days",
    )
    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        days_old=3650,
        scrape_fn=fake_scrape,
        run_id="all-active",
    )

    assert summary.raw_unique_jobs == 1
    largest = json.loads((tmp_path / "snapshots" / "germany" / "largest-batch.json").read_text())
    assert largest["metadata"]["days_old"] == 3650


def test_europe_collection_rejects_nonpositive_limits(tmp_path: Path):
    with pytest.raises(ValueError, match="limits must contain positive integers"):
        collect_europe_data_engineers(tmp_path, limits=(0,))


def test_europe_collection_rejects_nonpositive_days_old(tmp_path: Path):
    with pytest.raises(ValueError, match="days_old must be positive"):
        collect_europe_data_engineers(tmp_path, countries=(), days_old=0)


def test_europe_collection_rejects_unsafe_run_id(tmp_path: Path):
    with pytest.raises(ValueError, match="run_id must be a safe path segment"):
        collect_europe_data_engineers(tmp_path, countries=(), run_id="../../outside")


def test_largest_batch_is_not_reused_for_a_different_country_code(tmp_path: Path):
    def fake_scrape(**kwargs):
        return pd.DataFrame(
            [
                {
                    "id": f"job-{index}",
                    "site": "indeed",
                    "title": "Data Engineer",
                    "company": "Example",
                    "location": "Europe",
                    "description": "Build pipelines",
                    "job_url": f"https://example.indeed.com/viewjob?jk=job-{index}",
                }
                for index in range(kwargs["results_wanted"])
            ]
        )

    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Example Country", "AA"),),
        limits=(2,),
        scrape_fn=fake_scrape,
        run_id="country-aa",
    )
    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Example Country", "BB"),),
        limits=(1,),
        scrape_fn=fake_scrape,
        run_id="country-bb",
    )

    assert summary.raw_unique_jobs == 1
    largest = json.loads(
        (tmp_path / "snapshots" / "example-country" / "largest-batch.json").read_text()
    )
    assert largest["metadata"]["country_code"] == "BB"
