from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass(frozen=True, slots=True)
class StorageConfig:
    database_path: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    search: SearchConfig
    filters: FilterConfig
    storage: StorageConfig


def _positive(value: Any, name: str, default: int) -> int:
    result = int(value if value is not None else default)
    if result <= 0:
        raise ConfigError(f"{name} must be positive")
    return result


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    search = raw.get("search") or {}
    storage = raw.get("storage") or {}
    filters = raw.get("filters") or {}
    queries = tuple(str(value).strip() for value in search.get("queries", ()) if str(value).strip())
    if not queries:
        raise ConfigError("search.queries must contain at least one query")
    for key in ("country", "country_code", "location"):
        if not str(search.get(key) or "").strip():
            raise ConfigError(f"search.{key} is required")
    if not storage.get("database_path") or not storage.get("output_dir"):
        raise ConfigError("storage.database_path and storage.output_dir are required")
    base = config_path.parent
    return AppConfig(
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
        ),
        storage=StorageConfig(
            database_path=(base / str(storage["database_path"])).resolve(),
            output_dir=(base / str(storage["output_dir"])).resolve(),
        ),
    )
