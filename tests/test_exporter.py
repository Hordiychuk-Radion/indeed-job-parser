import csv
from pathlib import Path

from indeed_job_parser.exporter import export_jobs
from indeed_job_parser.models import JobRecord


def _job(identifier: str) -> JobRecord:
    return JobRecord(
        dedupe_key=f"indeed:{identifier}",
        source="indeed",
        source_job_id=identifier,
        query="Data Engineer",
        title="Data Engineer",
        company="Example",
        location="Prague",
        country_code="CZ",
        description="Python and SQL",
        canonical_url=f"https://example.com/{identifier}",
        published_at="2026-10-19",
        employment_type=None,
        is_remote=False,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_period=None,
        eligibility="eligible",
        eligibility_reason="within_experience_limit",
    )


def test_export_jobs_accepts_one_shot_iterables(tmp_path: Path):
    job = _job("1")

    export_jobs(tmp_path, (item for item in [job]), (item for item in [job]))

    with (tmp_path / "jobs-all.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["source_job_id"] == "1"
    assert rows[0]["canonical_url"] == "https://example.com/1"
