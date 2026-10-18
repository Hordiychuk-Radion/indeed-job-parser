from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import JobRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_eligible INTEGER NOT NULL DEFAULT 0,
    rows_unknown INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    config_json TEXT NOT NULL,
    scope_key TEXT
);

CREATE TABLE IF NOT EXISTS search_scopes (
    scope_key TEXT PRIMARY KEY,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('europe', 'country')),
    country_code TEXT,
    label TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_job_id TEXT,
    query TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    country_code TEXT NOT NULL,
    description TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    published_at TEXT,
    employment_type TEXT,
    is_remote INTEGER,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT,
    salary_period TEXT,
    eligibility TEXT NOT NULL,
    eligibility_reason TEXT NOT NULL,
    required_experience_years INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS job_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    observed_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_technologies (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    technology TEXT NOT NULL,
    PRIMARY KEY (job_id, category, technology)
);

CREATE TABLE IF NOT EXISTS scope_jobs (
    scope_key TEXT NOT NULL REFERENCES search_scopes(scope_key) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    eligibility TEXT NOT NULL,
    eligibility_reason TEXT NOT NULL,
    PRIMARY KEY (scope_key, job_id)
);

CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_country_idx ON jobs(country_code);
CREATE INDEX IF NOT EXISTS jobs_published_idx ON jobs(published_at);
CREATE INDEX IF NOT EXISTS jobs_eligibility_idx ON jobs(eligibility);
CREATE INDEX IF NOT EXISTS observations_run_idx ON job_observations(run_id);
CREATE INDEX IF NOT EXISTS technologies_name_idx ON job_technologies(technology);
CREATE INDEX IF NOT EXISTS scope_jobs_job_idx ON scope_jobs(job_id);

CREATE VIEW IF NOT EXISTS europe_jobs AS
SELECT
    sj.scope_key,
    s.label AS scope_label,
    sj.eligibility AS scope_eligibility,
    sj.eligibility_reason AS scope_eligibility_reason,
    j.*
FROM scope_jobs AS sj
JOIN search_scopes AS s ON s.scope_key = sj.scope_key
JOIN jobs AS j ON j.id = sj.job_id
WHERE s.scope_type = 'europe';

CREATE VIEW IF NOT EXISTS country_jobs AS
SELECT
    sj.scope_key,
    s.country_code AS scope_country_code,
    s.label AS scope_label,
    sj.eligibility AS scope_eligibility,
    sj.eligibility_reason AS scope_eligibility_reason,
    j.*
FROM scope_jobs AS sj
JOIN search_scopes AS s ON s.scope_key = sj.scope_key
JOIN jobs AS j ON j.id = sj.job_id
WHERE s.scope_type = 'country';
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(SCHEMA)
        run_columns = {
            row[1] for row in self.connection.execute("PRAGMA table_info(ingestion_runs)")
        }
        if "scope_key" not in run_columns:
            self.connection.execute("ALTER TABLE ingestion_runs ADD COLUMN scope_key TEXT")
        self.connection.commit()

    def __enter__(self) -> "JobRepository":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def ensure_scope(
        self,
        scope_key: str,
        scope_type: str,
        *,
        country_code: str | None = None,
        label: str,
    ) -> None:
        if scope_type not in {"europe", "country"}:
            raise ValueError("scope_type must be 'europe' or 'country'")
        normalized_country = country_code.strip().upper() if country_code else None
        if scope_type == "country" and not normalized_country:
            raise ValueError("country scopes require country_code")
        if scope_type == "europe":
            normalized_country = None
        self.connection.execute(
            """
            INSERT INTO search_scopes (scope_key, scope_type, country_code, label, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET
                scope_type=excluded.scope_type,
                country_code=excluded.country_code,
                label=excluded.label,
                updated_at=excluded.updated_at
            """,
            (scope_key, scope_type, normalized_country, label, _now()),
        )

    def start_run(self, config: Mapping[str, Any], *, scope_key: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        self.connection.execute(
            """
            INSERT INTO ingestion_runs (id, started_at, status, config_json, scope_key)
            VALUES (?, ?, 'running', ?, ?)
            """,
            (
                run_id,
                _now(),
                json.dumps(config, ensure_ascii=False, sort_keys=True, default=str),
                scope_key,
            ),
        )
        self.connection.commit()
        return run_id

    def replace_scope_jobs(
        self,
        scope_key: str,
        jobs: list[tuple[int, str, str]],
        *,
        commit: bool = True,
    ) -> None:
        self.connection.execute("DELETE FROM scope_jobs WHERE scope_key=?", (scope_key,))
        unique_jobs = {
            job_id: (eligibility, eligibility_reason)
            for job_id, eligibility, eligibility_reason in jobs
        }
        self.connection.executemany(
            """
            INSERT INTO scope_jobs (scope_key, job_id, eligibility, eligibility_reason)
            VALUES (?, ?, ?, ?)
            """,
            [
                (scope_key, job_id, eligibility, eligibility_reason)
                for job_id, (eligibility, eligibility_reason) in unique_jobs.items()
            ],
        )
        if commit:
            self.connection.commit()

    def save_job(
        self,
        run_id: str,
        job: JobRecord,
        raw_payload: Mapping[str, Any],
        *,
        commit: bool = True,
    ) -> int:
        timestamp = _now()
        values = (
            job.dedupe_key, job.source, job.source_job_id, job.query, job.title, job.company,
            job.location, job.country_code, job.description, job.canonical_url, job.published_at,
            job.employment_type, job.is_remote, job.salary_min, job.salary_max,
            job.salary_currency, job.salary_period, job.eligibility, job.eligibility_reason,
            job.required_experience_years, timestamp, timestamp,
        )
        self.connection.execute(
            """
            INSERT INTO jobs (
                dedupe_key, source, source_job_id, query, title, company, location, country_code,
                description, canonical_url, published_at, employment_type, is_remote, salary_min,
                salary_max, salary_currency, salary_period, eligibility, eligibility_reason,
                required_experience_years, first_seen_at, last_seen_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                source=excluded.source,
                source_job_id=excluded.source_job_id,
                query=excluded.query,
                title=excluded.title,
                company=excluded.company,
                location=excluded.location,
                country_code=excluded.country_code,
                description=excluded.description,
                canonical_url=excluded.canonical_url,
                published_at=COALESCE(excluded.published_at, jobs.published_at),
                employment_type=excluded.employment_type,
                is_remote=excluded.is_remote,
                salary_min=excluded.salary_min,
                salary_max=excluded.salary_max,
                salary_currency=excluded.salary_currency,
                salary_period=excluded.salary_period,
                eligibility=excluded.eligibility,
                eligibility_reason=excluded.eligibility_reason,
                required_experience_years=excluded.required_experience_years,
                last_seen_at=excluded.last_seen_at,
                status='active'
            """,
            values,
        )
        row = self.connection.execute(
            "SELECT id FROM jobs WHERE dedupe_key=?", (job.dedupe_key,)
        ).fetchone()
        job_id = int(row[0])
        self.connection.execute(
            "INSERT INTO job_observations (run_id, job_id, observed_at, raw_payload) VALUES (?,?,?,?)",
            (run_id, job_id, timestamp, json.dumps(raw_payload, ensure_ascii=False, sort_keys=True, default=str)),
        )
        if commit:
            self.connection.commit()
        return job_id

    def replace_job_technologies(
        self,
        job_id: int,
        stack: Mapping[str, list[str]],
        *,
        commit: bool = True,
    ) -> None:
        self.connection.execute("DELETE FROM job_technologies WHERE job_id=?", (job_id,))
        rows = [
            (job_id, category, technology)
            for category, technologies in stack.items()
            for technology in dict.fromkeys(technologies)
            if category and technology
        ]
        self.connection.executemany(
            "INSERT INTO job_technologies (job_id, category, technology) VALUES (?, ?, ?)",
            rows,
        )
        if commit:
            self.connection.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        rows_received: int,
        rows_eligible: int,
        rows_unknown: int,
        rows_rejected: int,
        error_count: int,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE ingestion_runs
            SET finished_at=?, status=?, rows_received=?, rows_eligible=?, rows_unknown=?,
                rows_rejected=?, error_count=?, error_message=?
            WHERE id=?
            """,
            (
                _now(), status, rows_received, rows_eligible, rows_unknown, rows_rejected,
                error_count, error_message, run_id,
            ),
        )
        self.connection.commit()


def inspect_database(database_path: str | Path, *, limit: int = 10) -> dict[str, Any]:
    path = Path(database_path)
    if not path.exists():
        raise FileNotFoundError(f"Database does not exist: {path}")
    if limit <= 0:
        raise ValueError("limit must be positive")

    with JobRepository(path) as repository:
        connection = repository.connection
        counts = {
            "jobs": int(connection.execute("SELECT count(*) FROM jobs").fetchone()[0]),
            "observations": int(
                connection.execute("SELECT count(*) FROM job_observations").fetchone()[0]
            ),
            "runs": int(connection.execute("SELECT count(*) FROM ingestion_runs").fetchone()[0]),
        }
        eligibility_counts = {
            row[0]: int(row[1])
            for row in connection.execute(
                "SELECT eligibility, count(*) FROM jobs GROUP BY eligibility ORDER BY eligibility"
            ).fetchall()
        }
        scopes = [
            {
                "scope_key": row[0],
                "scope_type": row[1],
                "country_code": row[2],
                "label": row[3],
                "jobs": int(row[4]),
            }
            for row in connection.execute(
                "SELECT s.scope_key, s.scope_type, s.country_code, s.label, "
                "count(sj.job_id) AS jobs FROM search_scopes AS s "
                "LEFT JOIN scope_jobs AS sj ON sj.scope_key=s.scope_key "
                "GROUP BY s.scope_key, s.scope_type, s.country_code, s.label "
                "ORDER BY s.scope_type, s.scope_key"
            ).fetchall()
        ]
        technology_counts = [
            {"technology": row[0], "jobs": int(row[1])}
            for row in connection.execute(
                "SELECT jt.technology, count(DISTINCT jt.job_id) AS jobs "
                "FROM job_technologies AS jt JOIN jobs AS j ON j.id=jt.job_id "
                "WHERE EXISTS (SELECT 1 FROM scope_jobs AS selected_scope "
                "WHERE selected_scope.job_id=j.id AND selected_scope.eligibility != 'rejected') "
                "OR (NOT EXISTS (SELECT 1 FROM scope_jobs AS any_scope "
                "WHERE any_scope.job_id=j.id) AND j.eligibility != 'rejected') "
                "GROUP BY jt.technology ORDER BY jobs DESC, jt.technology ASC"
            ).fetchall()
        ]
        job_rows = connection.execute(
            "SELECT id, source_job_id, title, company, location, country_code, description, "
            "canonical_url, published_at, eligibility, eligibility_reason, last_seen_at FROM jobs "
            "ORDER BY last_seen_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        recent_jobs = []
        for row in job_rows:
            stack: dict[str, list[str]] = {}
            for technology_row in connection.execute(
                "SELECT category, technology FROM job_technologies "
                "WHERE job_id=? ORDER BY category, technology",
                (row["id"],),
            ).fetchall():
                stack.setdefault(technology_row["category"], []).append(
                    technology_row["technology"]
                )
            recent_jobs.append(
                {
                    "source_job_id": row["source_job_id"],
                    "title": row["title"],
                    "company": row["company"],
                    "location": row["location"],
                    "country_code": row["country_code"],
                    "description": row["description"],
                    "url": row["canonical_url"],
                    "published_at": row["published_at"],
                    "eligibility": row["eligibility"],
                    "eligibility_reason": row["eligibility_reason"],
                    "last_seen_at": row["last_seen_at"],
                    "stack": stack,
                }
            )
    return {
        "database_path": str(path),
        "counts": counts,
        "scopes": scopes,
        "eligibility_counts": eligibility_counts,
        "technology_counts": technology_counts,
        "recent_jobs": recent_jobs,
    }
