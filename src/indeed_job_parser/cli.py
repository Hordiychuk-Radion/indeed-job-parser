from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from .pipeline import RunSummary, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="indeed-jobs", description="Collect Indeed vacancies into SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Run one configured collection")
    run.add_argument("--config", type=Path, required=True, help="Path to TOML configuration")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[[Path], RunSummary] = run_pipeline,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        summary = runner(args.config)
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
        return 0 if summary.error_count == 0 else 1
    return 2
