from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobRecord:
    dedupe_key: str
    source: str
    source_job_id: str
    query: str
    title: str
    company: str
    location: str
    country_code: str
    description: str
    canonical_url: str
    published_at: str | None
    employment_type: str | None
    is_remote: bool | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    eligibility: str = "unknown"
    eligibility_reason: str = "not_evaluated"
    required_experience_years: int | None = None
