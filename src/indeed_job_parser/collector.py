from __future__ import annotations

import time
from typing import Any, Callable

from .config import SearchConfig


_ACCESS_CONTROL_MARKERS = (
    "401",
    "403",
    "429",
    "access denied",
    "captcha",
    "forbidden",
    "rate limit",
    "too many requests",
)


def _is_access_control_failure(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", getattr(exc, "status_code", None))
    return status in {401, 403, 429} or any(
        marker in str(exc).casefold() for marker in _ACCESS_CONTROL_MARKERS
    )


def collect_indeed(
    config: SearchConfig,
    scrape_fn: Callable[..., Any] | None = None,
    *,
    max_attempts: int = 2,
    retry_delay: float = 1,
    deadline_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    if retry_delay < 0:
        raise ValueError("retry_delay must not be negative")
    if deadline_seconds is not None and deadline_seconds < 0:
        raise ValueError("deadline_seconds must not be negative")
    if scrape_fn is None:
        from jobspy import scrape_jobs

        scrape_fn = scrape_jobs

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    distance_miles = max(1, round(config.distance_km / 1.60934))
    deadline = time.monotonic() + deadline_seconds if deadline_seconds is not None else None
    for query in config.queries:
        if deadline is not None and time.monotonic() >= deadline:
            errors.append(f"{query}: collection deadline exceeded")
            continue
        for attempt in range(1, max_attempts + 1):
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
                break
            except Exception as exc:
                if _is_access_control_failure(exc) or attempt == max_attempts:
                    errors.append(f"{query}: {type(exc).__name__}: {exc}")
                    break
                elif deadline is not None and time.monotonic() >= deadline:
                    errors.append(f"{query}: collection deadline exceeded")
                    break
                else:
                    time.sleep(retry_delay)
    return rows, errors
