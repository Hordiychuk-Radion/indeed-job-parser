from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .collector import collect_indeed
from .config import AppConfig, load_config
from .eligibility import evaluate_job
from .exporter import export_jobs
from .models import JobRecord
from .normalizer import normalize_record
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


def _apply_decision(job: JobRecord, config: AppConfig) -> JobRecord:
    decision = evaluate_job(asdict(job), config.filters.max_experience_years)
    status, reason = decision.status, decision.reason
    if (
        status != "rejected"
        and config.filters.min_salary is not None
        and job.salary_max is not None
        and (
            config.filters.salary_currency is None
            or job.salary_currency == config.filters.salary_currency
        )
        and job.salary_max < config.filters.min_salary
    ):
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
) -> RunSummary:
    config = load_config(config_path)
    raw_rows, errors = collect_indeed(config.search, scrape_fn=scrape_fn)
    processed: list[JobRecord] = []
    with JobRepository(config.storage.database_path) as repository:
        run_id = repository.start_run(asdict(config))
        try:
            for raw in raw_rows:
                job = normalize_record(raw, raw.get("_query", ""), config.search.country_code)
                job = _apply_decision(job, config)
                processed.append(job)
                repository.save_job(run_id, job, raw)
            counts = {
                status: sum(job.eligibility == status for job in processed)
                for status in ("eligible", "unknown", "rejected")
            }
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
    )
