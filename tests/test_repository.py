import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from indeed_job_parser.models import JobRecord
from indeed_job_parser.repository import JobRepository, inspect_database


def sample_job() -> JobRecord:
    return JobRecord(
        dedupe_key="key-1",
        source="indeed",
        source_job_id="abc",
        query="QA Engineer",
        title="QA Engineer",
        company="Example",
        location="Prague",
        country_code="CZ",
        description="Test APIs",
        canonical_url="https://cz.indeed.com/viewjob?jk=abc",
        published_at="2026-09-30",
        employment_type="fulltime",
        is_remote=False,
        salary_min=60000,
        salary_max=80000,
        salary_currency="CZK",
        salary_period="monthly",
        eligibility="unknown",
        eligibility_reason="experience_not_stated",
    )


def test_initializes_wal_schema(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        mode = repository.connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert mode == "wal"
    assert {"jobs", "ingestion_runs", "job_observations", "job_technologies"}.issubset(tables)


def test_replaces_structured_job_technologies(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python", "SQL"], "cloud": ["AWS"]},
        )
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python"], "cloud": ["Microsoft Azure"]},
        )
        rows = repository.connection.execute(
            "SELECT category, technology FROM job_technologies WHERE job_id=? "
            "ORDER BY category, technology",
            (job_id,),
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("cloud", "Microsoft Azure"),
        ("languages", "Python"),
    ]


def test_can_batch_job_and_stack_writes_in_one_transaction(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1}, commit=False)
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python"]},
            commit=False,
        )
        repository.connection.rollback()
        counts = (
            repository.connection.execute("SELECT count(*) FROM jobs").fetchone()[0],
            repository.connection.execute("SELECT count(*) FROM job_observations").fetchone()[0],
            repository.connection.execute("SELECT count(*) FROM job_technologies").fetchone()[0],
        )

    assert counts == (0, 0, 0)


def test_upsert_preserves_one_job_and_records_each_observation(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.save_job(run_id, replace(sample_job(), salary_max=90000), {"raw": 2})
        jobs = repository.connection.execute("SELECT count(*), max(salary_max) FROM jobs").fetchone()
        observations = repository.connection.execute(
            "SELECT count(*), max(raw_payload) FROM job_observations"
        ).fetchone()
    assert tuple(jobs) == (1, 90000)
    assert observations[0] == 2
    assert json.loads(observations[1]) == {"raw": 2}


def test_finishes_run_with_auditable_counts(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"queries": ["QA Engineer"]})
        repository.finish_run(
            run_id,
            status="succeeded",
            rows_received=10,
            rows_eligible=3,
            rows_unknown=4,
            rows_rejected=3,
            error_count=0,
        )
        run = repository.connection.execute(
            "SELECT status, rows_received, rows_eligible, rows_unknown, rows_rejected, error_count, finished_at "
            "FROM ingestion_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    assert tuple(run[:6]) == ("succeeded", 10, 3, 4, 3, 0)
    assert run[6]


def test_inspects_database_with_descriptions_and_stack(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        run_id = repository.start_run({"queries": ["QA Engineer"]})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python"], "cloud": ["AWS"]},
        )
        repository.finish_run(
            run_id,
            status="succeeded",
            rows_received=1,
            rows_eligible=0,
            rows_unknown=1,
            rows_rejected=0,
            error_count=0,
        )

    payload = inspect_database(database, limit=5)

    assert payload["counts"] == {"jobs": 1, "observations": 1, "runs": 1}
    assert payload["eligibility_counts"] == {"unknown": 1}
    assert payload["technology_counts"] == [
        {"technology": "AWS", "jobs": 1},
        {"technology": "Python", "jobs": 1},
    ]
    assert payload["recent_jobs"][0]["description"] == "Test APIs"
    assert payload["recent_jobs"][0]["eligibility"] == "unknown"
    assert payload["recent_jobs"][0]["stack"] == {
        "cloud": ["AWS"],
        "languages": ["Python"],
    }
