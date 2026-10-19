import json
import sqlite3
from datetime import date
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
                        "date_posted": "2026-10-10",
                    },
                    {
                        "id": "other-1",
                        "site": "indeed",
                        "title": "Prison Officer",
                        "company": "Other",
                        "location": "Berlin, DE",
                        "description": "The application data is processed securely",
                        "job_url": "https://de.indeed.com/viewjob?jk=other-1",
                        "date_posted": "2026-10-10",
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
                    "date_posted": "2026-10-10",
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
        as_of=date(2026, 10, 19),
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
        run_counts = connection.execute(
            "SELECT rows_eligible, rows_unknown, rows_rejected FROM ingestion_runs"
        ).fetchone()
    assert stored == [
        (
            "Senior Data Engineer",
            "Build Python and SQL pipelines with Airflow on AWS",
            "unknown",
            "experience_not_stated",
        ),
    ]
    assert observations == 1
    assert tuple(run_counts) == (0, 1, 1)
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
            "published_at": "2026-10-10",
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


def test_country_is_failed_when_any_required_attempt_fails(tmp_path: Path):
    def mixed_scrape(**kwargs):
        if kwargs["results_wanted"] == 4:
            raise RuntimeError("blocked")
        return pd.DataFrame(
            [
                {
                    "id": "data-1",
                    "site": "indeed",
                    "title": "Data Engineer",
                    "company": "Example",
                    "location": "Berlin",
                    "description": "Python and SQL",
                    "job_url": "https://de.indeed.com/viewjob?jk=data-1",
                    "date_posted": "2026-10-10",
                }
            ]
        )

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(2, 4),
        days_old=14,
        scrape_fn=mixed_scrape,
        as_of=date(2026, 10, 19),
    )

    assert summary.countries_completed == 0
    assert summary.countries_failed == 1
    assert summary.error_count == 1
    with sqlite3.connect(summary.database_path) as connection:
        assert connection.execute(
            "SELECT status FROM ingestion_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0] == "failed"


def test_europe_collection_excludes_title_match_above_experience_limit(tmp_path: Path):
    def fake_scrape(**_kwargs):
        return pd.DataFrame(
            [
                {
                    "id": "within-limit",
                    "site": "indeed",
                    "title": "Senior Data Engineer",
                    "company": "Keep",
                    "location": "London",
                    "description": (
                        "Requirements\nRequires 5+ years of experience with Python.\n"
                        "Nice to Have\nSnowflake is a plus.\n"
                        "Responsibilities\nBuild ETL pipelines and improve data quality."
                    ),
                    "job_url": "https://uk.indeed.com/viewjob?jk=within-limit",
                    "date_posted": "2026-10-10",
                },
                {
                    "id": "above-limit",
                    "site": "indeed",
                    "title": "Senior Data Engineer",
                    "company": "Reject",
                    "location": "London",
                    "description": "Requires 7+ years of professional experience with SQL.",
                    "job_url": "https://uk.indeed.com/viewjob?jk=above-limit",
                    "date_posted": "2026-10-10",
                },
            ]
        )

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("United Kingdom", "GB"),),
        limits=(2,),
        scrape_fn=fake_scrape,
        run_id="experience-filter",
        as_of=date(2026, 10, 19),
    )

    assert summary.raw_unique_jobs == 2
    assert summary.selected_data_engineers == 1
    with sqlite3.connect(summary.database_path) as connection:
        assert connection.execute(
            "SELECT source_job_id, required_experience_years FROM europe_jobs"
        ).fetchall() == [("within-limit", 5)]
        assert connection.execute(
            "SELECT technology, requirement_type FROM job_technologies "
            "ORDER BY technology"
        ).fetchall() == [("Python", "required"), ("Snowflake", "preferred")]
        assert connection.execute(
            "SELECT concept, requirement_type FROM job_concepts ORDER BY concept"
        ).fetchall() == [("Data Quality", "mentioned"), ("ETL/ELT", "mentioned")]


def test_europe_collection_replaces_only_europe_scope_in_shared_database(tmp_path: Path):
    database_path = tmp_path / "jobs.db"
    with JobRepository(database_path) as repository:
        repository.ensure_scope(
            "country:DE", "country", country_code="DE", label="Germany"
        )
        repository.ensure_scope(
            "europe:data-engineer", "europe", label="Europe Data Engineer"
        )
        run_id = repository.start_run({"mode": "seed"}, scope_key="country:DE")
        country_job_id = repository.save_job(
            run_id,
            JobRecord(
                dedupe_key="country-only",
                source="indeed",
                source_job_id="country-only",
                query="Data Engineer",
                title="Prison Officer",
                company="Other",
                location="Berlin",
                country_code="DE",
                description="Mentions Python",
                canonical_url="https://de.indeed.com/viewjob?jk=country-only",
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
            {"country": True},
        )
        repository.replace_job_technologies(country_job_id, {"languages": ["Python"]})
        stale_europe_id = repository.save_job(
            run_id,
            JobRecord(
                dedupe_key="stale-europe",
                source="indeed",
                source_job_id="stale-europe",
                query="Data Engineer",
                title="Data Engineer",
                company="Old",
                location="Paris",
                country_code="FR",
                description="Build Java pipelines",
                canonical_url="https://fr.indeed.com/viewjob?jk=stale-europe",
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
            {"europe": True},
        )
        repository.replace_job_technologies(stale_europe_id, {"languages": ["Java"]})
        repository.replace_scope_jobs(
            "country:DE",
            [(country_job_id, "rejected", "title_not_data_engineer")],
        )
        repository.replace_scope_jobs(
            "europe:data-engineer",
            [(stale_europe_id, "eligible", "title_matches_data_engineer")],
        )

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
                "date_posted": "2026-10-10",
            }]
        )

    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        scrape_fn=fake_scrape,
        run_id="selected-only",
        database_path=database_path,
        as_of=date(2026, 10, 19),
    )

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT source_job_id FROM europe_jobs ORDER BY source_job_id"
        ).fetchall() == [("data-1",)]
        assert connection.execute(
            "SELECT source_job_id FROM country_jobs ORDER BY source_job_id"
        ).fetchall() == [("country-only",)]
        assert connection.execute(
            "SELECT count(*) FROM scope_jobs "
            "WHERE scope_key='europe:data-engineer' AND job_id=?",
            (stale_europe_id,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM job_observations WHERE job_id=?", (country_job_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT technology FROM job_technologies WHERE job_id=?", (country_job_id,)
        ).fetchall() == [("Python",)]


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


def test_current_scope_uses_current_run_not_historical_largest_batch(tmp_path: Path):
    def fake_scrape(**kwargs):
        identifier = "old-a" if kwargs["results_wanted"] == 2 else "current"
        rows = [
            {
                "id": identifier,
                "site": "indeed",
                "title": "Data Engineer",
                "company": "Example",
                "location": "Berlin",
                "description": "Build SQL pipelines",
                "job_url": f"https://de.indeed.com/viewjob?jk={identifier}",
                "date_posted": "2026-10-10",
            }
        ]
        if kwargs["results_wanted"] == 2:
            rows.append({**rows[0], "id": "old-b", "job_url": "https://de.indeed.com/viewjob?jk=old-b"})
        return pd.DataFrame(rows)

    database = tmp_path / "jobs.db"
    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(2,),
        days_old=14,
        scrape_fn=fake_scrape,
        run_id="first",
        database_path=database,
        as_of=date(2026, 10, 19),
    )
    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        days_old=14,
        scrape_fn=fake_scrape,
        run_id="second",
        database_path=database,
        as_of=date(2026, 10, 19),
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT source_job_id FROM europe_jobs"
        ).fetchall() == [("current",)]
    largest = json.loads((tmp_path / "snapshots" / "germany" / "largest-batch.json").read_text())
    assert len(largest["jobs"]) == 2


def test_europe_reports_cross_country_duplicate_hits(tmp_path: Path):
    def fake_scrape(**_kwargs):
        return pd.DataFrame(
            [
                {
                    "id": "shared",
                    "site": "indeed",
                    "title": "Data Engineer",
                    "company": "Example",
                    "location": "Europe",
                    "description": "Requires 3 years of experience. Python and SQL.",
                    "job_url": "https://example.indeed.com/viewjob?jk=shared",
                    "date_posted": "2026-10-10",
                }
            ]
        )

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(
            EuropeCountry("Germany", "DE"),
            EuropeCountry("Austria", "AT"),
        ),
        limits=(1,),
        days_old=14,
        scrape_fn=fake_scrape,
        as_of=date(2026, 10, 19),
    )

    assert summary.raw_unique_jobs == 1
    assert summary.duplicate_rows == 1


def test_europe_scope_size_anomaly_keeps_previous_publication(tmp_path: Path):
    def fake_scrape(**kwargs):
        return pd.DataFrame(
            [
                {
                    "id": f"job-{kwargs['results_wanted']}-{index}",
                    "site": "indeed",
                    "title": "Data Engineer",
                    "company": "Example",
                    "location": "Berlin",
                    "description": "Requires 3 years of experience. Python and SQL.",
                    "job_url": (
                        "https://de.indeed.com/viewjob?jk="
                        f"job-{kwargs['results_wanted']}-{index}"
                    ),
                    "date_posted": "2026-10-10",
                }
                for index in range(kwargs["results_wanted"])
            ]
        )

    database = tmp_path / "jobs.db"
    collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(4,),
        days_old=14,
        scrape_fn=fake_scrape,
        run_id="baseline",
        database_path=database,
        as_of=date(2026, 10, 19),
    )
    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        days_old=14,
        scrape_fn=fake_scrape,
        run_id="anomaly",
        database_path=database,
        as_of=date(2026, 10, 19),
        minimum_scope_ratio=0.5,
        minimum_baseline_size=1,
    )

    assert summary.scope_anomaly is True
    assert summary.error_count == 1
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM europe_jobs"
        ).fetchone()[0] == 4
        assert connection.execute(
            "SELECT status FROM ingestion_runs ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0] == "partial"


def test_europe_collection_rejects_empty_country_list(tmp_path: Path):
    with pytest.raises(ValueError, match="countries must not be empty"):
        collect_europe_data_engineers(tmp_path, countries=())


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


def test_europe_collection_enforces_freshness_after_source_response(tmp_path: Path):
    def fake_scrape(**_kwargs):
        base = {
            "site": "indeed",
            "title": "Data Engineer",
            "company": "Example",
            "location": "Berlin",
            "description": "Build SQL pipelines",
        }
        return pd.DataFrame(
            [
                {**base, "id": "fresh", "job_url": "https://de.indeed.com/viewjob?jk=fresh", "date_posted": "2026-10-06"},
                {**base, "id": "stale", "job_url": "https://de.indeed.com/viewjob?jk=stale", "date_posted": "2026-10-05"},
                {**base, "id": "missing", "job_url": "https://de.indeed.com/viewjob?jk=missing", "date_posted": None},
            ]
        )

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(3,),
        days_old=14,
        scrape_fn=fake_scrape,
        run_id="freshness",
        as_of=date(2026, 10, 19),
    )

    assert summary.raw_unique_jobs == 3
    assert summary.selected_data_engineers == 1
    assert summary.rows_fresh == 1
    assert summary.rows_stale == 1
    assert summary.rows_missing_date == 1
    selected = json.loads((tmp_path / "jobs-selected.json").read_text())
    assert [row["url"] for row in selected] == ["https://de.indeed.com/viewjob?jk=fresh"]


def test_europe_failure_is_failed_and_keeps_last_successful_scope(tmp_path: Path):
    database_path = tmp_path / "jobs.db"
    with JobRepository(database_path) as repository:
        repository.ensure_scope("europe:data-engineer", "europe", label="Europe Data Engineer")
        run_id = repository.start_run({"mode": "seed"}, scope_key="europe:data-engineer")
        job_id = repository.save_job(
            run_id,
            JobRecord(
                dedupe_key="existing",
                source="indeed",
                source_job_id="existing",
                query="Data Engineer",
                title="Data Engineer",
                company="Existing",
                location="Berlin",
                country_code="DE",
                description="Build SQL pipelines",
                canonical_url="https://de.indeed.com/viewjob?jk=existing",
                published_at="2026-10-10",
                employment_type=None,
                is_remote=None,
                salary_min=None,
                salary_max=None,
                salary_currency=None,
                salary_period=None,
                eligibility="unknown",
                eligibility_reason="experience_not_stated",
            ),
            {"seed": True},
        )
        repository.replace_scope_jobs(
            "europe:data-engineer",
            [(job_id, "unknown", "experience_not_stated")],
        )

    def failed_scrape(**_kwargs):
        raise RuntimeError("Indeed unavailable")

    summary = collect_europe_data_engineers(
        tmp_path,
        countries=(EuropeCountry("Germany", "DE"),),
        limits=(1,),
        days_old=14,
        scrape_fn=failed_scrape,
        run_id="failed-run",
        database_path=database_path,
        as_of=date(2026, 10, 19),
    )

    assert summary.countries_completed == 0
    assert summary.error_count == 1
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT status FROM ingestion_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()[0] == "failed"
        assert connection.execute(
            "SELECT source_job_id FROM europe_jobs"
        ).fetchall() == [("existing",)]
