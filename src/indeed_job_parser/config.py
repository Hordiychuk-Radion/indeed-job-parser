from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDE_TITLE_PATTERNS = (
    "junior",
    "jr",
    "trainee",
    "intern",
    "internship",
    "graduate",
    "lead",
    "team lead",
    "principal",
    "staff",
    "head",
    "manager",
    "director",
    "chief",
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SearchConfig:
    country: str
    country_code: str
    location: str
    queries: tuple[str, ...]
    results_per_query: int = 25
    days_old: int = 14
    distance_km: int = 50
    remote_only: bool = False
    job_type: str | None = None


@dataclass(frozen=True, slots=True)
class FilterConfig:
    max_experience_years: int = 5
    include_unknown: bool = True
    min_salary: float | None = None
    salary_currency: str | None = None
    include_title_patterns: tuple[str, ...] = ()
    exclude_title_patterns: tuple[str, ...] = DEFAULT_EXCLUDE_TITLE_PATTERNS


@dataclass(frozen=True, slots=True)
class StorageConfig:
    database_path: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    search: SearchConfig
    filters: FilterConfig
    storage: StorageConfig


@dataclass(frozen=True, slots=True)
class ConfigOverrides:
    titles: tuple[str, ...] | None = None
    country: str | None = None
    country_code: str | None = None
    location: str | None = None
    results_per_query: int | None = None
    days_old: int | None = None
    distance_km: int | None = None
    remote_only: bool | None = None
    job_type: str | None = None
    max_experience_years: int | None = None
    include_unknown: bool | None = None
    min_salary: float | None = None
    salary_currency: str | None = None


def _positive(value: Any, name: str, default: int) -> int:
    result = int(value if value is not None else default)
    if result <= 0:
        raise ConfigError(f"{name} must be positive")
    return result


def _strings(values: Any) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values or () if str(value).strip())


def apply_overrides(config: AppConfig, overrides: ConfigOverrides | None) -> AppConfig:
    if overrides is None:
        return config
    titles = _strings(overrides.titles) if overrides.titles is not None else None
    if overrides.titles is not None and not titles:
        raise ConfigError("--title must not be empty")
    search = replace(
        config.search,
        queries=titles or config.search.queries,
        country=overrides.country.strip() if overrides.country is not None else config.search.country,
        country_code=(
            overrides.country_code.strip().upper()
            if overrides.country_code is not None
            else config.search.country_code
        ),
        location=overrides.location.strip() if overrides.location is not None else config.search.location,
        results_per_query=(
            _positive(overrides.results_per_query, "results_per_query", config.search.results_per_query)
            if overrides.results_per_query is not None
            else config.search.results_per_query
        ),
        days_old=(
            _positive(overrides.days_old, "days_old", config.search.days_old)
            if overrides.days_old is not None
            else config.search.days_old
        ),
        distance_km=(
            _positive(overrides.distance_km, "distance_km", config.search.distance_km)
            if overrides.distance_km is not None
            else config.search.distance_km
        ),
        remote_only=(
            overrides.remote_only if overrides.remote_only is not None else config.search.remote_only
        ),
        job_type=overrides.job_type if overrides.job_type is not None else config.search.job_type,
    )
    filters = replace(
        config.filters,
        max_experience_years=(
            _positive(
                overrides.max_experience_years,
                "max_experience_years",
                config.filters.max_experience_years,
            )
            if overrides.max_experience_years is not None
            else config.filters.max_experience_years
        ),
        include_unknown=(
            overrides.include_unknown
            if overrides.include_unknown is not None
            else config.filters.include_unknown
        ),
        min_salary=(
            overrides.min_salary if overrides.min_salary is not None else config.filters.min_salary
        ),
        salary_currency=(
            overrides.salary_currency.strip().upper()
            if overrides.salary_currency is not None
            else config.filters.salary_currency
        ),
        include_title_patterns=titles or config.filters.include_title_patterns,
    )
    return replace(config, search=search, filters=filters)


def load_config(path: str | Path, overrides: ConfigOverrides | None = None) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    search = raw.get("search") or {}
    storage = raw.get("storage") or {}
    filters = raw.get("filters") or {}
    queries = _strings(search.get("queries"))
    if not queries:
        raise ConfigError("search.queries must contain at least one query")
    for key in ("country", "country_code", "location"):
        if not str(search.get(key) or "").strip():
            raise ConfigError(f"search.{key} is required")
    if not storage.get("database_path") or not storage.get("output_dir"):
        raise ConfigError("storage.database_path and storage.output_dir are required")
    base = config_path.parent
    config = AppConfig(
        search=SearchConfig(
            country=str(search["country"]).strip(),
            country_code=str(search["country_code"]).strip().upper(),
            location=str(search["location"]).strip(),
            queries=queries,
            results_per_query=_positive(search.get("results_per_query"), "results_per_query", 25),
            days_old=_positive(search.get("days_old"), "days_old", 14),
            distance_km=_positive(search.get("distance_km"), "distance_km", 50),
            remote_only=bool(search.get("remote_only", False)),
            job_type=str(search["job_type"]).strip() if search.get("job_type") else None,
        ),
        filters=FilterConfig(
            max_experience_years=_positive(filters.get("max_experience_years"), "max_experience_years", 5),
            include_unknown=bool(filters.get("include_unknown", True)),
            min_salary=float(filters["min_salary"]) if filters.get("min_salary") is not None else None,
            salary_currency=str(filters["salary_currency"]).strip().upper() if filters.get("salary_currency") else None,
            include_title_patterns=_strings(filters.get("include_title_patterns")) or queries,
            exclude_title_patterns=(
                _strings(filters.get("exclude_title_patterns"))
                if "exclude_title_patterns" in filters
                else DEFAULT_EXCLUDE_TITLE_PATTERNS
            ),
        ),
        storage=StorageConfig(
            database_path=(base / str(storage["database_path"])).resolve(),
            output_dir=(base / str(storage["output_dir"])).resolve(),
        ),
    )
    return apply_overrides(config, overrides)
