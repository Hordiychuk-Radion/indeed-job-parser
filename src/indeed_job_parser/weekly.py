from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .operations import collection_lock

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _remaining_timeout(
    deadline: float,
    command: Sequence[str],
    *,
    cap: float | None = None,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(list(command), 0)
    return min(remaining, cap) if cap is not None else remaining


def _run(
    runner: Runner,
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    pass_fds: Sequence[int] = (),
) -> subprocess.CompletedProcess[str]:
    return runner(
        list(command),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        pass_fds=tuple(pass_fds),
    )


def _quality(database_path: Path, run_id: str) -> dict[str, int | float | str]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT rows_fresh, rows_stale, rows_future,
                   rows_invalid_date, rows_missing_date
            FROM run_quality_metrics WHERE run_id=?
            """,
            (run_id,),
        ).fetchone()
        scope = connection.execute(
            """
            SELECT
                count(*),
                sum(CASE WHEN trim(coalesce(j.description, '')) = '' THEN 1 ELSE 0 END),
                sum(CASE WHEN sj.eligibility = 'unknown' THEN 1 ELSE 0 END),
                sum(CASE WHEN EXISTS (
                        SELECT 1 FROM job_technologies jt WHERE jt.job_id = sj.job_id
                    ) THEN 1 ELSE 0 END),
                sum(CASE WHEN j.canonical_url NOT LIKE 'http://%'
                              AND j.canonical_url NOT LIKE 'https://%'
                         THEN 1 ELSE 0 END)
            FROM scope_jobs sj
            JOIN jobs j ON j.id = sj.job_id
            WHERE sj.scope_key = 'europe:data-engineer'
            """
        ).fetchone()
        inactive_urls = connection.execute(
            """
            SELECT count(*) FROM scope_job_lifecycle
            WHERE scope_key = 'europe:data-engineer' AND status = 'closed'
            """
        ).fetchone()[0]
        run = connection.execute(
            """
            SELECT status, rows_received, rows_eligible, rows_unknown,
                   rows_rejected, error_count
            FROM ingestion_runs WHERE id=?
            """,
            (run_id,),
        ).fetchone()
    if row is None or run is None:
        raise RuntimeError(f"Missing quality metrics for run {run_id}")
    keys = (
        "rows_fresh",
        "rows_stale",
        "rows_future",
        "rows_invalid_date",
        "rows_missing_date",
    )
    quality: dict[str, int | float | str] = dict(zip(keys, map(int, row), strict=True))
    scope_jobs, missing, unknown, technology_jobs, invalid_urls = map(
        int,
        (value or 0 for value in scope),
    )
    quality.update(
        {
            "scope_jobs": scope_jobs,
            "missing_descriptions": missing,
            "unknown_experience": unknown,
            "technology_coverage": (
                round(technology_jobs / scope_jobs, 4) if scope_jobs else 0.0
            ),
            "invalid_urls": invalid_urls,
            "inactive_urls": int(inactive_urls),
            "run_status": str(run[0]),
            "rows_received": int(run[1]),
            "rows_eligible": int(run[2]),
            "rows_unknown": int(run[3]),
            "rows_rejected": int(run[4]),
            "collection_errors": int(run[5]),
        }
    )
    return quality


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _run_weekly(
    project_root: str | Path,
    *,
    database_path: str | Path = "data/jobs.db",
    output_dir: str | Path = "output/europe-data-engineer",
    days_old: int = 14,
    limit: int = 100,
    timeout_seconds: float = 2700,
    runner: Runner = subprocess.run,
    deadline: float | None = None,
    lock_fd: int | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    database = Path(database_path)
    if not database.is_absolute():
        database = root / database
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    status_path = output / "weekly-status.json"
    end = deadline if deadline is not None else time.monotonic() + timeout_seconds

    parser_command = (
        sys.executable,
        "-m",
        "indeed_job_parser",
        "europe-data-engineer",
        "--output-dir",
        str(output),
        "--database",
        str(database),
        "--days-old",
        str(days_old),
        "--limit",
        str(limit),
        "--lock-held",
    )
    parser = _run(
        runner,
        parser_command,
        cwd=root,
        timeout=_remaining_timeout(end, parser_command),
        pass_fds=(lock_fd,) if lock_fd is not None else (),
    )
    parser_summary = json.loads(parser.stdout)
    run_id = str(parser_summary["database_run_id"])

    compose = ("docker", "compose", "-f", str(root / "docker-compose.grafana.yml"))
    prepare_command = (*compose, "run", "--rm", "prepare-grafana-db")
    _run(
        runner,
        prepare_command,
        cwd=root,
        timeout=_remaining_timeout(end, prepare_command, cap=180),
    )
    start_command = (*compose, "up", "-d", "--force-recreate", "--wait", "grafana")
    _run(
        runner,
        start_command,
        cwd=root,
        timeout=_remaining_timeout(end, start_command, cap=180),
    )
    verify_command = (sys.executable, str(root / "scripts/verify_grafana.py"))
    _run(
        runner,
        verify_command,
        cwd=root,
        timeout=_remaining_timeout(end, verify_command, cap=60),
    )

    report = {
        "status": "ok",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "run": parser_summary,
        "quality": _quality(database, run_id),
    }
    _write_status(status_path, report)
    return report


def run_weekly(
    project_root: str | Path,
    *,
    database_path: str | Path = "data/jobs.db",
    output_dir: str | Path = "output/europe-data-engineer",
    days_old: int = 14,
    limit: int = 100,
    timeout_seconds: float = 2700,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    status_path = output / "weekly-status.json"
    database = Path(database_path)
    if not database.is_absolute():
        database = root / database
    deadline = time.monotonic() + timeout_seconds
    try:
        with collection_lock(database) as lock_fd:
            return _run_weekly(
                root,
                database_path=database,
                output_dir=output,
                days_old=days_old,
                limit=limit,
                timeout_seconds=timeout_seconds,
                runner=runner,
                deadline=deadline,
                lock_fd=lock_fd,
            )
    except Exception as exc:
        _write_status(
            status_path,
            {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
        raise
