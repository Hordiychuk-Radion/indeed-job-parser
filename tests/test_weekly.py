import json
import subprocess
from pathlib import Path

import pytest

from indeed_job_parser.models import JobRecord
from indeed_job_parser.operations import CollectionAlreadyRunning, collection_lock
from indeed_job_parser.repository import JobRepository
from indeed_job_parser.stack import TechnologyMention
from indeed_job_parser.weekly import run_weekly


def test_weekly_run_is_bounded_refreshes_grafana_and_writes_quality_report(tmp_path: Path):
    database = tmp_path / "data/jobs.db"
    with JobRepository(database) as repository:
        repository.ensure_scope("europe:data-engineer", "europe", label="Europe Data Engineer")
        run_id = repository.start_run({"mode": "test"}, scope_key="europe:data-engineer")
        job = JobRecord(
            dedupe_key="indeed:1",
            source="indeed",
            source_job_id="1",
            query="Data Engineer",
            title="Data Engineer",
            company="Example",
            location="Prague",
            country_code="CZ",
            description="",
            canonical_url="invalid-url",
            published_at="2026-10-10",
            employment_type=None,
            is_remote=False,
            salary_min=None,
            salary_max=None,
            salary_currency=None,
            salary_period=None,
            eligibility="unknown",
            eligibility_reason="experience_not_stated",
        )
        job_id = repository.save_job(run_id, job, {}, commit=False)
        repository.replace_job_technology_mentions(
            job_id,
            [
                TechnologyMention("languages", "Python", "required", None, "Python"),
                TechnologyMention("languages", "SQL", "required", None, "SQL"),
            ],
            commit=False,
        )
        repository.replace_scope_jobs(
            "europe:data-engineer",
            [(job_id, "unknown", "experience_not_stated")],
            run_id=run_id,
            commit=False,
        )
        repository.record_run_quality(
            run_id,
            rows_fresh=10,
            rows_stale=2,
            rows_future=0,
            rows_invalid_date=1,
            rows_missing_date=3,
        )
        repository.finish_run(
            run_id,
            status="succeeded",
            rows_received=16,
            rows_eligible=4,
            rows_unknown=6,
            rows_rejected=6,
            error_count=0,
        )

    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        stdout = json.dumps({"database_run_id": run_id}) if "europe-data-engineer" in command else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    report = run_weekly(
        tmp_path,
        database_path=database,
        output_dir=tmp_path / "output/europe-data-engineer",
        runner=fake_runner,
        timeout_seconds=123,
    )

    assert 0 < calls[0][1]["timeout"] <= 123
    assert calls[0][1]["pass_fds"]
    assert "--days-old" in calls[0][0]
    assert calls[0][0][calls[0][0].index("--days-old") + 1] == "14"
    assert calls[0][0][calls[0][0].index("--limit") + 1] == "100"
    assert any("prepare-grafana-db" in command for command, _ in calls)
    grafana_start = next(command for command, _ in calls if "grafana" in command and "up" in command)
    assert "--force-recreate" in grafana_start
    assert report["status"] == "ok"
    assert report["quality"] == {
        "rows_fresh": 10,
        "rows_stale": 2,
        "rows_future": 0,
        "rows_invalid_date": 1,
        "rows_missing_date": 3,
        "scope_jobs": 1,
        "missing_descriptions": 1,
        "unknown_experience": 1,
        "technology_coverage": 1.0,
        "invalid_urls": 1,
        "inactive_urls": 0,
        "run_status": "succeeded",
        "rows_received": 16,
        "rows_eligible": 4,
        "rows_unknown": 6,
        "rows_rejected": 6,
        "collection_errors": 0,
    }
    written = json.loads(
        (tmp_path / "output/europe-data-engineer/weekly-status.json").read_text()
    )
    assert written == report


def test_weekly_timeout_writes_failure_status(tmp_path: Path):
    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    output = tmp_path / "output/europe-data-engineer"
    with pytest.raises(subprocess.TimeoutExpired):
        run_weekly(
            tmp_path,
            output_dir=output,
            runner=timed_out,
            timeout_seconds=5,
        )

    status = json.loads((output / "weekly-status.json").read_text())
    assert status["status"] == "failed"
    assert status["error_type"] == "TimeoutExpired"


def test_weekly_holds_collection_lock_through_grafana_refresh(tmp_path: Path):
    database = tmp_path / "data/jobs.db"
    output = tmp_path / "output/europe-data-engineer"

    def fake_runner(command, **_kwargs):
        if "europe-data-engineer" in command:
            assert "--lock-held" in command
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"database_run_id": "run-1"}),
                stderr="",
            )
        with pytest.raises(CollectionAlreadyRunning):
            with collection_lock(database):
                pass
        raise RuntimeError("stop after lock assertion")

    with pytest.raises(RuntimeError, match="stop after lock assertion"):
        run_weekly(
            tmp_path,
            database_path=database,
            output_dir=output,
            runner=fake_runner,
        )


def test_weekly_uses_one_deadline_for_all_subprocesses(tmp_path: Path, monkeypatch):
    ticks = iter((100.0, 100.0, 104.0, 104.0))
    monkeypatch.setattr("indeed_job_parser.weekly.time.monotonic", lambda: next(ticks))
    timeouts = []

    def fake_runner(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        if "europe-data-engineer" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps({"database_run_id": "run-1"}),
                stderr="",
            )
        raise RuntimeError("stop after timeout assertion")

    with pytest.raises(RuntimeError, match="stop after timeout assertion"):
        run_weekly(
            tmp_path,
            database_path=tmp_path / "jobs.db",
            runner=fake_runner,
            timeout_seconds=10,
        )

    assert timeouts == [10, 6]
