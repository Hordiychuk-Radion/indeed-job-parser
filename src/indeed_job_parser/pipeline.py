from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .annotations import replace_job_annotations
from .collector import collect_indeed
from .config import AppConfig, ConfigOverrides, load_config
from .eligibility import evaluate_job
from .exporter import export_jobs
from .freshness import assess_freshness
from .models import JobRecord
from .normalizer import normalize_record
from .operations import collection_lock
from .repository import JobRepository


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    rows_received: int
    rows_eligible: int
    rows_unknown: int
    rows_rejected: int
    error_count: int
    database_path: str
    output_dir: str
    rows_fresh: int = 0
    rows_stale: int = 0
    rows_future: int = 0
    rows_invalid_date: int = 0
    rows_missing_date: int = 0


def _apply_decision(job: JobRecord, config: AppConfig) -> JobRecord:
    decision = evaluate_job(
        asdict(job),
        config.filters.max_experience_years,
        include_title_patterns=config.filters.include_title_patterns,
        exclude_title_patterns=config.filters.exclude_title_patterns,
        allowed_seniority=config.filters.allowed_seniority,
    )
    status, reason = decision.status, decision.reason
    if status != "rejected" and config.filters.min_salary is not None and job.salary_max is not None:
        if (
            config.filters.salary_currency is not None
            and job.salary_currency is not None
            and job.salary_currency != config.filters.salary_currency
        ):
            status, reason = "rejected", "salary_currency_mismatch"
        elif (
            config.filters.salary_period is not None
            and job.salary_period is not None
            and job.salary_period.casefold() != config.filters.salary_period
        ):
            status, reason = "rejected", "salary_period_mismatch"
        elif job.salary_max < config.filters.min_salary:
            status, reason = "rejected", "salary_below_minimum"
    return replace(
        job,
        eligibility=status,
        eligibility_reason=reason,
        required_experience_years=decision.required_years,
    )


def run_pipeline(
    config_path: str | Path,
    scrape_fn: Callable[..., Any] | None = None,
    *,
    overrides: ConfigOverrides | None = None,
    as_of: date | None = None,
    deadline_seconds: float = 600,
) -> RunSummary:
    config = load_config(config_path, overrides=overrides)
    with collection_lock(config.storage.database_path):
        return _run_pipeline(
            config,
            scrape_fn=scrape_fn,
            as_of=as_of,
            deadline_seconds=deadline_seconds,
        )


def _run_pipeline(
    config: AppConfig,
    *,
    scrape_fn: Callable[..., Any] | None = None,
    as_of: date | None = None,
    deadline_seconds: float = 600,
) -> RunSummary:
    raw_rows, errors = collect_indeed(
        config.search,
        scrape_fn=scrape_fn,
        deadline_seconds=deadline_seconds,
    )
    processed: list[JobRecord] = []
    scope_key = f"country:{config.search.country_code.upper()}"
    with JobRepository(config.storage.database_path) as repository:
        repository.abandon_stale_runs(older_than=timedelta(hours=24))
        repository.ensure_scope(
            scope_key,
            "country",
            country_code=config.search.country_code,
            label=config.search.country,
        )
        run_id = repository.start_run(asdict(config), scope_key=scope_key)
        freshness_counts = {status: 0 for status in ("fresh", "stale", "future", "invalid", "missing")}
        try:
            scope_memberships: list[tuple[int, str, str]] = []
            for raw in raw_rows:
                job = normalize_record(raw, raw.get("_query", ""), config.search.country_code)
                freshness = assess_freshness(
                    job.published_at,
                    days_old=config.search.days_old,
                    today=as_of,
                )
                freshness_counts[freshness] += 1
                if freshness == "fresh":
                    job = _apply_decision(job, config)
                else:
                    job = replace(
                        job,
                        eligibility="rejected",
                        eligibility_reason=f"published_at_{freshness}",
                    )
                processed.append(job)
                job_id = repository.save_job(run_id, job, raw, commit=False)
                replace_job_annotations(
                    repository,
                    job_id,
                    job.title,
                    job.description,
                    commit=False,
                )
                if freshness == "fresh":
                    scope_memberships.append(
                        (job_id, job.eligibility, job.eligibility_reason)
                    )
            if not errors:
                repository.replace_scope_jobs(
                    scope_key,
                    scope_memberships,
                    run_id=run_id,
                    commit=False,
                )
            counts = {
                status: sum(job.eligibility == status for job in processed)
                for status in ("eligible", "unknown", "rejected")
            }
            repository.record_run_quality(
                run_id,
                rows_fresh=freshness_counts["fresh"],
                rows_stale=freshness_counts["stale"],
                rows_future=freshness_counts["future"],
                rows_invalid_date=freshness_counts["invalid"],
                rows_missing_date=freshness_counts["missing"],
                commit=False,
            )
            repository.finish_run(
                run_id,
                status="succeeded" if not errors else "partial",
                rows_received=len(raw_rows),
                rows_eligible=counts["eligible"],
                rows_unknown=counts["unknown"],
                rows_rejected=counts["rejected"],
                error_count=len(errors),
                error_message="\n".join(errors) or None,
            )
        except Exception as exc:
            repository.connection.rollback()
            repository.finish_run(
                run_id,
                status="failed",
                rows_received=len(raw_rows),
                rows_eligible=0,
                rows_unknown=0,
                rows_rejected=0,
                error_count=len(errors) + 1,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

    selected = [
        job
        for job in processed
        if job.eligibility == "eligible"
        or (config.filters.include_unknown and job.eligibility == "unknown")
    ]
    export_jobs(config.storage.output_dir, processed, selected)
    return RunSummary(
        run_id=run_id,
        rows_received=len(raw_rows),
        rows_eligible=counts["eligible"],
        rows_unknown=counts["unknown"],
        rows_rejected=counts["rejected"],
        error_count=len(errors),
        database_path=str(config.storage.database_path),
        output_dir=str(config.storage.output_dir),
        rows_fresh=freshness_counts["fresh"],
        rows_stale=freshness_counts["stale"],
        rows_future=freshness_counts["future"],
        rows_invalid_date=freshness_counts["invalid"],
        rows_missing_date=freshness_counts["missing"],
    )
