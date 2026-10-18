from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .collector import collect_indeed
from .config import SearchConfig
from .models import JobRecord
from .normalizer import normalize_record
from .repository import JobRepository
from .stack import extract_stack, flatten_stack


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
    aggregate: dict[str, dict[str, Any]] = {}
    country_summaries = []
    error_count = 0

    for country in country_list:
        country_dir = directory / "snapshots" / _slug(country.name)
        largest_path = country_dir / "largest-batch.json"
        largest = None
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
                largest = candidate
        attempts = []
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
            raw_rows, collector_errors = collect_indeed(search, scrape_fn=scrape_fn)
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
            if largest is None or len(payload["jobs"]) > len(largest["jobs"]):
                largest = payload
                _write_json(largest_path, largest)

        if largest is None:
            largest = {"metadata": {"unique_jobs": 0}, "jobs": []}
            _write_json(largest_path, largest)
        for job in largest["jobs"]:
            aggregate.setdefault(job["dedupe_key"], job)
        country_summaries.append(
            {
                "country": country.name,
                "country_code": country.code,
                "attempts": attempts,
                "largest_snapshot": str(largest_path),
                "best_unique_jobs": len(largest["jobs"]),
            }
        )

    all_jobs = list(aggregate.values())
    selected_jobs = [job for job in all_jobs if _DATA_ENGINEER_RE.search(job["title"])]
    selected_rows = [_selected_row(job) for job in selected_jobs]
    technology_counts = Counter(
        technology for row in selected_rows for technology in row["stack_flat"]
    )
    resolved_database_path = Path(database_path) if database_path else directory / "jobs.db"
    with JobRepository(resolved_database_path) as repository:
        database_run_id = repository.start_run(
            {
                "mode": "europe-data-engineer",
                "collector_run_id": run_key,
                "query": "Data Engineer",
                "countries": [asdict(country) for country in country_list],
                "limits": list(limit_list),
                "days_old": days_old,
                "distance_km": distance_km,
            }
        )
        try:
            repository.connection.execute("DELETE FROM job_observations")
            repository.connection.execute("DELETE FROM job_technologies")
            repository.connection.execute("DELETE FROM jobs")
            for job_payload in selected_jobs:
                job = replace(
                    JobRecord(**job_payload),
                    eligibility="eligible",
                    eligibility_reason="title_matches_data_engineer",
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
                repository.replace_job_technologies(
                    job_id,
                    extract_stack(f"{job.title}\n{job.description}"),
                    commit=False,
                )
            repository.finish_run(
                database_run_id,
                status="succeeded",
                rows_received=len(all_jobs),
                rows_eligible=len(selected_jobs),
                rows_unknown=0,
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
        "countries_completed": len(country_list),
        "raw_unique_jobs": len(all_jobs),
        "selected_data_engineers": len(selected_rows),
        "technology_counts": dict(technology_counts.most_common()),
        "database_path": str(resolved_database_path),
        "database_run_id": database_run_id,
        "error_count": error_count,
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
        countries_completed=len(country_list),
        raw_unique_jobs=len(all_jobs),
        selected_data_engineers=len(selected_rows),
        error_count=error_count,
        output_dir=str(directory),
        database_path=str(resolved_database_path),
        database_run_id=database_run_id,
    )
