from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from .config import ConfigOverrides
from .pipeline import RunSummary, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="indeed-jobs", description="Collect Indeed vacancies into SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run one configured collection")
    run.add_argument("--config", type=Path, default=Path("config/example.toml"), help="Path to TOML configuration")
    run.add_argument("--title", dest="titles", action="append", help="Job title; repeat for multiple titles")
    run.add_argument("--country", help="Indeed country name")
    run.add_argument("--country-code", help="ISO country code stored with results")
    run.add_argument("--location", help="City, region, or country")
    run.add_argument("--results", dest="results_per_query", type=int, help="Results per title")
    run.add_argument("--days-old", type=int, help="Only jobs posted in the last N days")
    run.add_argument("--distance-km", type=int, help="Search radius in kilometres")
    run.add_argument("--remote-only", action=argparse.BooleanOptionalAction, default=None)
    run.add_argument("--job-type", help="JobSpy employment type, for example fulltime")
    run.add_argument("--max-experience-years", type=int)
    run.add_argument("--include-unknown", action=argparse.BooleanOptionalAction, default=None)
    run.add_argument("--min-salary", type=float)
    run.add_argument("--salary-currency")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., RunSummary] = run_pipeline,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        overrides = ConfigOverrides(
            titles=tuple(args.titles) if args.titles else None,
            country=args.country,
            country_code=args.country_code,
            location=args.location,
            results_per_query=args.results_per_query,
            days_old=args.days_old,
            distance_km=args.distance_km,
            remote_only=args.remote_only,
            job_type=args.job_type,
            max_experience_years=args.max_experience_years,
            include_unknown=args.include_unknown,
            min_salary=args.min_salary,
            salary_currency=args.salary_currency,
        )
        summary = runner(args.config, overrides=overrides)
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
        return 0 if summary.error_count == 0 else 1
    return 2
