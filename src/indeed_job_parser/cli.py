from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from .config import ConfigOverrides
from .europe import EuropeSummary, collect_europe_data_engineers
from .pipeline import RunSummary, run_pipeline
from .profiles import ProfileDraft, discover_profiles, resolve_profile, write_profile
from .repository import inspect_database
from .weekly import run_weekly


DEFAULT_CONFIG = Path("config/example.toml")
DEFAULT_PROFILES_DIR = Path("config/profiles")
DEFAULT_DATABASE = Path("data/jobs.db")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="indeed-jobs", description="Collect Indeed vacancies into SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run one configured collection")
    run.add_argument("profile", nargs="?", help="Saved profile name from config/profiles")
    run.add_argument("--config", type=Path, help="Path to TOML configuration")
    run.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR, help=argparse.SUPPRESS)
    run.add_argument("--title", dest="titles", action="append", help="Job title; repeat for multiple titles")
    run.add_argument(
        "--exclude-title",
        dest="exclude_titles",
        action="append",
        help="Reject titles containing this phrase; repeat for multiple phrases",
    )
    run.add_argument("--country", help="Indeed country name")
    run.add_argument("--country-code", help="ISO country code stored with results")
    run.add_argument("--location", help="City, region, or country")
    run.add_argument("--results", dest="results_per_query", type=int, help="Results per title")
    run.add_argument("--days-old", type=int, help="Only jobs posted in the last N days")
    run.add_argument("--distance-km", type=int, help="Search radius in kilometres")
    run.add_argument("--remote-only", action=argparse.BooleanOptionalAction, default=None)
    run.add_argument("--job-type", help="JobSpy employment type, for example fulltime")
    run.add_argument("--max-experience-years", type=int)
    run.add_argument(
        "--seniority",
        action="append",
        choices=("middle", "senior", "unspecified"),
        help="Allowed seniority; repeat to allow multiple levels",
    )
    run.add_argument("--include-unknown", action=argparse.BooleanOptionalAction, default=None)
    run.add_argument("--min-salary", type=float)
    run.add_argument("--salary-currency")
    run.add_argument("--salary-period", help="Salary interval, for example yearly or monthly")

    profiles = subparsers.add_parser("profiles", help="List saved profiles")
    profiles.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR, help=argparse.SUPPRESS)

    create = subparsers.add_parser("create-profile", help="Create a saved profile interactively")
    create.add_argument("--profiles-dir", type=Path, default=DEFAULT_PROFILES_DIR, help=argparse.SUPPRESS)

    europe = subparsers.add_parser(
        "europe-data-engineer",
        help="Collect Data Engineer vacancies across supported European Indeed countries",
    )
    europe.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/europe-data-engineer"),
        help="Directory for snapshots and aggregate exports",
    )
    europe.add_argument(
        "--limit",
        dest="limits",
        action="append",
        type=int,
        help="Results limit per country attempt; repeat for multiple attempts",
    )
    europe.add_argument(
        "--days-old",
        type=int,
        default=3650,
        help="Freshness window; default effectively includes all active listings",
    )
    europe.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="Shared SQLite path; defaults to data/jobs.db",
    )
    europe.add_argument("--lock-held", action="store_true", help=argparse.SUPPRESS)

    inspect = subparsers.add_parser("inspect-db", help="Show SQLite contents as JSON")
    inspect.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="SQLite database path",
    )
    inspect.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent jobs to include",
    )
    weekly = subparsers.add_parser(
        "weekly",
        help="Run a bounded Europe refresh, publish quality metrics, and refresh Grafana",
    )
    weekly.add_argument("--project-root", type=Path, default=Path.cwd())
    weekly.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    weekly.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/europe-data-engineer"),
    )
    weekly.add_argument("--days-old", type=int, default=14)
    weekly.add_argument("--limit", type=int, default=100)
    weekly.add_argument("--timeout-minutes", type=float, default=45)
    return parser


def _prompt_required(prompt: str, input_fn: Callable[[str], str]) -> str:
    while True:
        value = input_fn(prompt).strip()
        if value:
            return value
        print("Значення не може бути порожнім.")


def _prompt_int(prompt: str, default: int, input_fn: Callable[[str], str]) -> int:
    while True:
        value = input_fn(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            result = int(value)
        except ValueError:
            result = 0
        if result > 0:
            return result
        print("Введіть додатне ціле число.")


def _prompt_bool(prompt: str, default: bool, input_fn: Callable[[str], str]) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        value = input_fn(f"{prompt} [{suffix}]: ").strip().casefold()
        if not value:
            return default
        if value in {"y", "yes", "т", "так"}:
            return True
        if value in {"n", "no", "н", "ні"}:
            return False
        print("Введіть y або n.")


def _prompt_seniority(input_fn: Callable[[str], str]) -> tuple[str, ...]:
    print("Seniority: 1 — Middle, 2 — Senior, 3 — Unspecified, 4 — без обмеження")
    while True:
        choice = input_fn("Вибір [4]: ").strip() or "4"
        values = {
            "1": ("middle",),
            "2": ("senior",),
            "3": ("unspecified",),
            "4": (),
        }
        if choice in values:
            return values[choice]
        print("Введіть номер від 1 до 4.")


def _create_profile_wizard(profiles_dir: Path, input_fn: Callable[[str], str]) -> Path:
    print("\nСтворення профілю")
    name = _prompt_required("Коротка назва (lowercase-with-hyphens): ", input_fn)
    titles = tuple(
        title.strip()
        for title in _prompt_required("Професії через кому: ", input_fn).split(",")
        if title.strip()
    )
    draft = ProfileDraft(
        name=name,
        titles=titles,
        seniority=_prompt_seniority(input_fn),
        country=_prompt_required("Країна: ", input_fn),
        country_code=_prompt_required("ISO-код країни: ", input_fn),
        location=_prompt_required("Місто або регіон: ", input_fn),
        results_per_query=_prompt_int("Результатів на професію", 50, input_fn),
        days_old=_prompt_int("Давність у днях", 14, input_fn),
        distance_km=_prompt_int("Радіус у км", 80, input_fn),
        remote_only=_prompt_bool("Тільки remote", False, input_fn),
        max_experience_years=_prompt_int("Максимум років досвіду", 5, input_fn),
        include_unknown=_prompt_bool("Залишати вакансії без вказаного досвіду", True, input_fn),
    )
    path = write_profile(draft, profiles_dir)
    print(f"Профіль створено: {path}")
    return path


def _quick_search(
    runner: Callable[..., RunSummary],
    input_fn: Callable[[str], str],
) -> int:
    print("\nШвидкий одноразовий пошук")
    titles = tuple(
        title.strip()
        for title in _prompt_required("Професії через кому: ", input_fn).split(",")
        if title.strip()
    )
    seniority = _prompt_seniority(input_fn)
    overrides = ConfigOverrides(
        titles=titles,
        seniority=seniority or None,
        country=_prompt_required("Країна: ", input_fn),
        country_code=_prompt_required("ISO-код країни: ", input_fn),
        location=_prompt_required("Місто або регіон: ", input_fn),
        results_per_query=_prompt_int("Результатів на професію", 50, input_fn),
        days_old=_prompt_int("Давність у днях", 14, input_fn),
        distance_km=_prompt_int("Радіус у км", 80, input_fn),
        remote_only=_prompt_bool("Тільки remote", False, input_fn),
        max_experience_years=_prompt_int("Максимум років досвіду", 5, input_fn),
        include_unknown=_prompt_bool("Залишати вакансії без вказаного досвіду", True, input_fn),
    )
    return _print_summary(runner(DEFAULT_CONFIG, overrides=overrides))


def _print_summary(summary: RunSummary) -> int:
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0 if summary.error_count == 0 else 1


def _print_europe_summary(summary: EuropeSummary) -> int:
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    return 0 if summary.error_count == 0 else 1


def _interactive_menu(
    profiles_dir: Path,
    runner: Callable[..., RunSummary],
    input_fn: Callable[[str], str],
) -> int:
    print("\nIndeed Job Parser")
    print("1. Запустити збережений профіль")
    print("2. Створити новий профіль")
    print("3. Швидкий одноразовий пошук")
    print("4. Показати профілі")
    print("0. Вихід")
    choice = input_fn("Вибір: ").strip()
    if choice == "0":
        return 0
    if choice == "2":
        _create_profile_wizard(profiles_dir, input_fn)
        return 0
    if choice == "3":
        return _quick_search(runner, input_fn)
    profiles = discover_profiles(profiles_dir)
    if choice == "4":
        for name in profiles:
            print(name)
        return 0
    if choice != "1":
        print("Невідомий пункт меню.")
        return 2
    if not profiles:
        print("Збережених профілів немає. Спочатку створіть профіль.")
        return 2
    names = list(profiles)
    for index, name in enumerate(names, start=1):
        print(f"{index}. {name}")
    selected = input_fn("Профіль: ").strip()
    try:
        path = profiles[names[int(selected) - 1]]
    except (ValueError, IndexError):
        print("Невірний номер профілю.")
        return 2
    return _print_summary(runner(path, overrides=ConfigOverrides()))


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., RunSummary] = run_pipeline,
    europe_runner: Callable[..., EuropeSummary] = collect_europe_data_engineers,
    database_inspector: Callable[..., dict[str, object]] = inspect_database,
    weekly_runner: Callable[..., dict[str, object]] = run_weekly,
    input_fn: Callable[[str], str] = input,
    profiles_dir: Path = DEFAULT_PROFILES_DIR,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return _interactive_menu(profiles_dir, runner, input_fn)

    args = build_parser().parse_args(arguments)
    if args.command == "profiles":
        for name in discover_profiles(args.profiles_dir):
            print(name)
        return 0
    if args.command == "create-profile":
        _create_profile_wizard(args.profiles_dir, input_fn)
        return 0
    if args.command == "inspect-db":
        print(
            json.dumps(
                database_inspector(args.database, limit=args.limit),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "weekly":
        payload = weekly_runner(
            args.project_root,
            database_path=args.database,
            output_dir=args.output_dir,
            days_old=args.days_old,
            limit=args.limit,
            timeout_seconds=args.timeout_minutes * 60,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.command == "europe-data-engineer":
        limits = tuple(args.limits) if args.limits else (100, 500, 1000)
        lock_options = {"_lock_held": True} if args.lock_held else {}
        return _print_europe_summary(
            europe_runner(
                args.output_dir,
                limits=limits,
                days_old=args.days_old,
                database_path=args.database,
                **lock_options,
            )
        )
    if args.command == "run":
        if args.profile and args.config:
            raise SystemExit("Use either a profile name or --config, not both")
        config_path = (
            resolve_profile(args.profile, args.profiles_dir)
            if args.profile
            else args.config or DEFAULT_CONFIG
        )
        overrides = ConfigOverrides(
            titles=tuple(args.titles) if args.titles else None,
            exclude_titles=tuple(args.exclude_titles) if args.exclude_titles else None,
            country=args.country,
            country_code=args.country_code,
            location=args.location,
            results_per_query=args.results_per_query,
            days_old=args.days_old,
            distance_km=args.distance_km,
            remote_only=args.remote_only,
            job_type=args.job_type,
            max_experience_years=args.max_experience_years,
            seniority=tuple(args.seniority) if args.seniority else None,
            include_unknown=args.include_unknown,
            min_salary=args.min_salary,
            salary_currency=args.salary_currency,
            salary_period=args.salary_period,
        )
        return _print_summary(runner(config_path, overrides=overrides))
    return 2
