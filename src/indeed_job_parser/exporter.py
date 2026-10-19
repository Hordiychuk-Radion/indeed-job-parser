from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .models import JobRecord


def export_jobs(output_dir: str | Path, all_jobs: Iterable[JobRecord], selected: Iterable[JobRecord]) -> None:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    all_rows = [asdict(job) for job in all_jobs]
    selected_rows = [asdict(job) for job in selected]
    (directory / "jobs-all.json").write_text(
        json.dumps(all_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (directory / "jobs-selected.json").write_text(
        json.dumps(selected_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fields = list((all_rows or selected_rows)[0]) if all_rows or selected_rows else []
    for filename, rows in (("jobs-all.csv", all_rows), ("jobs-selected.csv", selected_rows)):
        with (directory / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            if fields:
                writer.writeheader()
                writer.writerows(rows)

    counts = {
        status: sum(row["eligibility"] == status for row in all_rows)
        for status in ("eligible", "unknown", "rejected")
    }
    lines = [
        "# Indeed vacancy report",
        "",
        f"- eligible: {counts['eligible']}",
        f"- unknown: {counts['unknown']}",
        f"- rejected: {counts['rejected']}",
        "",
        "## Selected vacancies",
        "",
    ]
    for row in selected_rows:
        lines.append(
            f"- [{row['title']}]({row['canonical_url']}) — {row['company']}; "
            f"{row['location']}; **{row['eligibility']}**"
        )
    if not selected_rows:
        lines.append("- No matching vacancies")
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
