from __future__ import annotations

from typing import Any, Callable

from .config import SearchConfig


def collect_indeed(
    config: SearchConfig,
    scrape_fn: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if scrape_fn is None:
        from jobspy import scrape_jobs

        scrape_fn = scrape_jobs

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    distance_miles = max(1, round(config.distance_km / 1.60934))
    for query in config.queries:
        try:
            frame = scrape_fn(
                site_name="indeed",
                search_term=query,
                location=config.location,
                distance=distance_miles,
                is_remote=config.remote_only,
                job_type=config.job_type,
                results_wanted=config.results_per_query,
                hours_old=config.days_old * 24,
                country_indeed=config.country,
                linkedin_fetch_description=False,
                verbose=0,
            )
            for raw in frame.to_dict(orient="records"):
                rows.append({**raw, "_query": query})
        except Exception as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
    return rows, errors
