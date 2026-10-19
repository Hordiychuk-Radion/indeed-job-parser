from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .annotations import replace_job_annotations
from .collector import collect_indeed
from .config import SearchConfig
from .eligibility import extract_required_years
from .freshness import assess_freshness
from .models import JobRecord
from .normalizer import normalize_record
from .operations import collection_lock
from .repository import JobRepository
from .stack import (
    extract_stack,
    flatten_stack,
)


@dataclass(frozen=True, slots=True)
class EuropeCountry:
    name: str
    code: str


@dataclass(frozen=True, slots=True)
class EuropeSummary:
    countries_completed: int
    raw_unique_jobs: int
    selected_data_engineers: int
    error_count: int
    output_dir: str
    database_path: str = ""
    database_run_id: str = ""
    rows_fresh: int = 0
    rows_stale: int = 0
    rows_future: int = 0
    rows_invalid_date: int = 0
    rows_missing_date: int = 0
    countries_attempted: int = 0
    countries_failed: int = 0
    scope_anomaly: bool = False
    previous_scope_size: int = 0
    duplicate_rows: int = 0


EUROPE_COUNTRIES = (
    EuropeCountry("Austria", "AT"),
    EuropeCountry("Belgium", "BE"),
    EuropeCountry("Bulgaria", "BG"),
    EuropeCountry("Croatia", "HR"),
    EuropeCountry("Cyprus", "CY"),
    EuropeCountry("Czech Republic", "CZ"),
    EuropeCountry("Denmark", "DK"),
    EuropeCountry("Estonia", "EE"),
    EuropeCountry("Finland", "FI"),
    EuropeCountry("France", "FR"),
    EuropeCountry("Germany", "DE"),
    EuropeCountry("Greece", "GR"),
    EuropeCountry("Hungary", "HU"),
    EuropeCountry("Ireland", "IE"),
    EuropeCountry("Italy", "IT"),
    EuropeCountry("Latvia", "LV"),
    EuropeCountry("Lithuania", "LT"),
    EuropeCountry("Luxembourg", "LU"),
    EuropeCountry("Malta", "MT"),
    EuropeCountry("Netherlands", "NL"),
    EuropeCountry("Norway", "NO"),
    EuropeCountry("Poland", "PL"),
    EuropeCountry("Portugal", "PT"),
    EuropeCountry("Romania", "RO"),
    EuropeCountry("Slovakia", "SK"),
    EuropeCountry("Slovenia", "SI"),
    EuropeCountry("Spain", "ES"),
    EuropeCountry("Sweden", "SE"),
    EuropeCountry("Switzerland", "CH"),
    EuropeCountry("Türkiye", "TR"),
    EuropeCountry("Ukraine", "UA"),
    EuropeCountry("United Kingdom", "GB"),
)

_DATA_ENGINEER_PATTERNS = (
    r"\bdata engineer\b",
    r"\bdateningenieur(?:in)?\b",
    r"\bing[ée]nieur(?:e)?(?: de)? data\b",
    r"\bing[ée]nieur(?:e)? (?:de |des )?donn[ée]es\b",
    r"\bingenier[oa] de datos\b",
    r"\bingegnere (?:dei |di )?dati\b",
    r"\bengenheir[oa] de dados\b",
    r"\binżynier(?:ka)? danych\b",
    r"\bdatov[ýá] inžen[ýy]r(?:ka)?\b",
    r"\bdátov[ýá] inžinier(?:ka)?\b",
    r"\badatmérnök\b",
    r"\bdataingeniør\b",
    r"\bdataingenjör\b",
    r"\bdata-?insinööri\b",
    r"\binginer(?:ă)? de date\b",
    r"μηχανικ(?:ός|ή) δεδομένων",
    r"инженер(?:ка)? (?:по )?данни",
    r"\binženjer(?:ka)? podataka\b",
    r"\bduomenų inžinier(?:ius|ė)\b",
    r"\bdatu inženier(?:is|e)\b",
    r"\bandmeinsener\b",
    r"інженер(?:ка)? даних",
    r"\bveri mühendisi\b",
)
_DATA_ENGINEER_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in _DATA_ENGINEER_PATTERNS),
    re.IGNORECASE,
)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _selected_row(job: dict[str, Any]) -> dict[str, Any]:
    stack = extract_stack(f"{job['title']}\n{job['description']}")
    return {
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "country_code": job["country_code"],
        "published_at": job["published_at"],
        "employment_type": job["employment_type"],
        "is_remote": job["is_remote"],
        "url": job["canonical_url"],
        "stack": stack,
        "stack_flat": flatten_stack(stack),
    }


def collect_europe_data_engineers(
    output_dir: str | Path,
    *,
    countries: Iterable[EuropeCountry] = EUROPE_COUNTRIES,
    limits: Iterable[int] = (100, 500, 1000),
    days_old: int = 3650,
    distance_km: int = 1000,
    scrape_fn: Callable[..., Any] | None = None,
    run_id: str | None = None,
    database_path: str | Path | None = None,
    as_of: date | None = None,
    deadline_seconds: float = 2700,
    minimum_scope_ratio: float = 0.5,
    minimum_baseline_size: int = 20,
    _lock_held: bool = False,
) -> EuropeSummary:
    resolved_database_path = Path(database_path) if database_path else Path(output_dir) / "jobs.db"
    if _lock_held:
        return _collect_europe_data_engineers(
            output_dir,
            countries=countries,
            limits=limits,
            days_old=days_old,
            distance_km=distance_km,
            scrape_fn=scrape_fn,
            run_id=run_id,
            database_path=resolved_database_path,
            as_of=as_of,
            deadline_seconds=deadline_seconds,
            minimum_scope_ratio=minimum_scope_ratio,
            minimum_baseline_size=minimum_baseline_size,
        )
    with collection_lock(resolved_database_path):
        return _collect_europe_data_engineers(
            output_dir,
            countries=countries,
            limits=limits,
            days_old=days_old,
            distance_km=distance_km,
            scrape_fn=scrape_fn,
            run_id=run_id,
            database_path=resolved_database_path,
            as_of=as_of,
            deadline_seconds=deadline_seconds,
            minimum_scope_ratio=minimum_scope_ratio,
            minimum_baseline_size=minimum_baseline_size,
        )


def _collect_europe_data_engineers(
    output_dir: str | Path,
    *,
    countries: Iterable[EuropeCountry] = EUROPE_COUNTRIES,
    limits: Iterable[int] = (100, 500, 1000),
    days_old: int = 3650,
    distance_km: int = 1000,
    scrape_fn: Callable[..., Any] | None = None,
    run_id: str | None = None,
    database_path: str | Path,
    as_of: date | None = None,
    deadline_seconds: float = 2700,
    minimum_scope_ratio: float = 0.5,
    minimum_baseline_size: int = 20,
) -> EuropeSummary:
    directory = Path(output_dir)
    run_key = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_key) is None:
        raise ValueError("run_id must be a safe path segment")
    country_list = tuple(countries)
    limit_list = tuple(limits)
    if not limit_list or any(limit <= 0 for limit in limit_list):
        raise ValueError("limits must contain positive integers")
    if days_old <= 0:
        raise ValueError("days_old must be positive")
    if not country_list:
        raise ValueError("countries must not be empty")
    if not 0 < minimum_scope_ratio <= 1:
        raise ValueError("minimum_scope_ratio must be between 0 and 1")
    if minimum_baseline_size <= 0:
        raise ValueError("minimum_baseline_size must be positive")
    aggregate: dict[str, dict[str, Any]] = {}
    country_summaries = []
    error_count = 0
    countries_completed = 0
    country_unique_jobs = 0
    deadline = time.monotonic() + deadline_seconds

    for country in country_list:
        country_dir = directory / "snapshots" / _slug(country.name)
        largest_path = country_dir / "largest-batch.json"
        historical_largest = None
        if largest_path.exists():
            candidate = json.loads(largest_path.read_text(encoding="utf-8"))
            metadata = candidate.get("metadata", {})
            if (
                metadata.get("query") == "Data Engineer"
                and metadata.get("country") == country.name
                and metadata.get("country_code") == country.code
                and metadata.get("days_old") == days_old
                and metadata.get("distance_km") == distance_km
            ):
                historical_largest = candidate
        attempts = []
        current_largest = None
        country_succeeded = True
        for limit in limit_list:
            search = SearchConfig(
                country=country.name,
                country_code=country.code,
                location=country.name,
                queries=("Data Engineer",),
                results_per_query=limit,
                days_old=days_old,
                distance_km=distance_km,
                remote_only=False,
            )
            raw_rows, collector_errors = collect_indeed(
                search,
                scrape_fn=scrape_fn,
                deadline_seconds=max(0, deadline - time.monotonic()),
            )
            unique = {}
            normalization_errors = []
            for index, raw in enumerate(raw_rows):
                try:
                    job = normalize_record(raw, raw.get("_query", ""), country.code)
                    unique.setdefault(job.dedupe_key, asdict(job))
                except Exception as exc:
                    normalization_errors.append(f"row {index}: {type(exc).__name__}: {exc}")
            payload = {
                "metadata": {
                    "country": country.name,
                    "country_code": country.code,
                    "query": "Data Engineer",
                    "requested": limit,
                    "days_old": days_old,
                    "distance_km": distance_km,
                    "raw_rows": len(raw_rows),
                    "unique_jobs": len(unique),
                    "collector_errors": collector_errors,
                    "normalization_errors": normalization_errors,
                },
                "jobs": list(unique.values()),
            }
            snapshot = country_dir / run_key / f"limit-{limit}.json"
            _write_json(snapshot, payload)
            attempts.append({**payload["metadata"], "snapshot": str(snapshot)})
            error_count += len(collector_errors) + len(normalization_errors)
            country_succeeded = country_succeeded and not (
                collector_errors or normalization_errors
            )
            if current_largest is None or len(payload["jobs"]) > len(current_largest["jobs"]):
                current_largest = payload
            if historical_largest is None or len(payload["jobs"]) > len(historical_largest["jobs"]):
                historical_largest = payload
                _write_json(largest_path, historical_largest)

        if historical_largest is None:
            historical_largest = {"metadata": {"unique_jobs": 0}, "jobs": []}
            _write_json(largest_path, historical_largest)
        if current_largest is None:
            current_largest = {"metadata": {"unique_jobs": 0}, "jobs": []}
        country_unique_jobs += len(current_largest["jobs"])
        for job in current_largest["jobs"]:
            aggregate.setdefault(job["dedupe_key"], job)
        countries_completed += int(country_succeeded)
        country_summaries.append(
            {
                "country": country.name,
                "country_code": country.code,
                "attempts": attempts,
                "largest_snapshot": str(largest_path),
                "best_unique_jobs": len(current_largest["jobs"]),
            }
        )

    all_jobs = list(aggregate.values())
    duplicate_rows = country_unique_jobs - len(all_jobs)
    classified_jobs = [
        (
            job,
            assess_freshness(job.get("published_at"), days_old=days_old, today=as_of),
        )
        for job in all_jobs
    ]
    freshness_counts = Counter(status for _, status in classified_jobs)
    fresh_jobs = [job for job, status in classified_jobs if status == "fresh"]
    title_matched_jobs = [job for job in fresh_jobs if _DATA_ENGINEER_RE.search(job["title"])]
    selected_jobs = [
        job
        for job in title_matched_jobs
        if (extract_required_years(str(job.get("description") or "")) or 0) <= 5
    ]
    selected_rows = [_selected_row(job) for job in selected_jobs]
    technology_counts = Counter(
        technology for row in selected_rows for technology in row["stack_flat"]
    )
    resolved_database_path = Path(database_path) if database_path else directory / "jobs.db"
    scope_key = "europe:data-engineer"
    scope_anomaly = False
    previous_scope_size = 0
    with JobRepository(resolved_database_path) as repository:
        repository.abandon_stale_runs(older_than=timedelta(hours=24))
        repository.ensure_scope(scope_key, "europe", label="Europe Data Engineer")
        previous_scope_size = repository.connection.execute(
            "SELECT count(*) FROM scope_jobs WHERE scope_key = ?",
            (scope_key,),
        ).fetchone()[0]
        database_run_id = repository.start_run(
            {
                "mode": "europe-data-engineer",
                "collector_run_id": run_key,
                "query": "Data Engineer",
                "countries": [asdict(country) for country in country_list],
                "limits": list(limit_list),
                "days_old": days_old,
                "distance_km": distance_km,
            },
            scope_key=scope_key,
        )
        try:
            scope_memberships: list[tuple[int, str, str]] = []
            for job_payload in selected_jobs:
                required_years = extract_required_years(
                    str(job_payload.get("description") or "")
                )
                eligibility = "eligible" if required_years is not None else "unknown"
                eligibility_reason = (
                    "experience_within_limit"
                    if required_years is not None
                    else "experience_not_stated"
                )
                job = replace(
                    JobRecord(**job_payload),
                    eligibility=eligibility,
                    eligibility_reason=eligibility_reason,
                    required_experience_years=required_years,
                )
                job_id = repository.save_job(
                    database_run_id,
                    job,
                    {
                        "persistence_source": "selected_data_engineer_export",
                        "normalized_job": job_payload,
                    },
                    commit=False,
                )
                replace_job_annotations(
                    repository,
                    job_id,
                    job.title,
                    job.description,
                    commit=False,
                )
                scope_memberships.append(
                    (job_id, job.eligibility, job.eligibility_reason)
                )
            scope_anomaly = (
                error_count == 0
                and previous_scope_size >= minimum_baseline_size
                and len(scope_memberships) < previous_scope_size * minimum_scope_ratio
            )
            if scope_anomaly:
                error_count += 1
            if error_count == 0:
                repository.replace_scope_jobs(
                    scope_key,
                    scope_memberships,
                    run_id=database_run_id,
                    commit=False,
                )
            rows_eligible = sum(
                eligibility == "eligible"
                for _, eligibility, _ in scope_memberships
            )
            rows_unknown = sum(
                eligibility == "unknown"
                for _, eligibility, _ in scope_memberships
            )
            repository.record_run_quality(
                database_run_id,
                rows_fresh=freshness_counts["fresh"],
                rows_stale=freshness_counts["stale"],
                rows_future=freshness_counts["future"],
                rows_invalid_date=freshness_counts["invalid"],
                rows_missing_date=freshness_counts["missing"],
                commit=False,
            )
            run_status = (
                "succeeded"
                if error_count == 0
                else "partial"
                if countries_completed > 0
                else "failed"
            )
            repository.finish_run(
                database_run_id,
                status=run_status,
                rows_received=len(all_jobs),
                rows_eligible=rows_eligible,
                rows_unknown=rows_unknown,
                rows_rejected=len(all_jobs) - len(selected_jobs),
                error_count=error_count,
            )
        except Exception as exc:
            repository.connection.rollback()
            repository.finish_run(
                database_run_id,
                status="failed",
                rows_received=0,
                rows_eligible=0,
                rows_unknown=0,
                rows_rejected=0,
                error_count=error_count + 1,
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise
    _write_json(directory / "jobs-all.json", all_jobs)
    _write_json(directory / "jobs-selected.json", selected_rows)
    summary_payload = {
        "run_id": run_key,
        "countries_completed": countries_completed,
        "countries_attempted": len(country_list),
        "countries_failed": len(country_list) - countries_completed,
        "raw_unique_jobs": len(all_jobs),
        "selected_data_engineers": len(selected_rows),
        "technology_counts": dict(technology_counts.most_common()),
        "database_path": str(resolved_database_path),
        "database_run_id": database_run_id,
        "error_count": error_count,
        "scope_anomaly": scope_anomaly,
        "previous_scope_size": previous_scope_size,
        "duplicate_rows": duplicate_rows,
        "freshness": dict(freshness_counts),
        "countries": country_summaries,
    }
    _write_json(directory / "summary.json", summary_payload)

    lines = [
        "# Indeed — Data Engineer vacancies in Europe",
        "",
        f"Total: **{len(selected_rows)}** vacancies.",
        "",
        "## Technology stack",
        "",
    ]
    if technology_counts:
        lines.extend(
            f"- {technology}: **{count}**"
            for technology, count in technology_counts.most_common()
        )
    else:
        lines.append("- No recognized technologies")
    lines.extend(["", "## Vacancies", ""])
    for row in selected_rows:
        lines.append(
            f"- [{row['title']}]({row['url']}) — {row['company'] or 'Company not specified'}; "
            f"{row['location'] or 'Location not specified'}; "
            f"Stack: {', '.join(row['stack_flat']) or 'not recognized'}"
        )
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return EuropeSummary(
        countries_completed=countries_completed,
        raw_unique_jobs=len(all_jobs),
        selected_data_engineers=len(selected_rows),
        error_count=error_count,
        output_dir=str(directory),
        database_path=str(resolved_database_path),
        database_run_id=database_run_id,
        rows_fresh=freshness_counts["fresh"],
        rows_stale=freshness_counts["stale"],
        rows_future=freshness_counts["future"],
        rows_invalid_date=freshness_counts["invalid"],
        rows_missing_date=freshness_counts["missing"],
        countries_attempted=len(country_list),
        countries_failed=len(country_list) - countries_completed,
        scope_anomaly=scope_anomaly,
        previous_scope_size=previous_scope_size,
        duplicate_rows=duplicate_rows,
    )
