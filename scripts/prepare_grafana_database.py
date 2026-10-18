from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def prepare_database(source: Path, destination: Path) -> None:
    """Create an atomic, standalone SQLite snapshot for read-only reporting."""
    source = source.resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.unlink(missing_ok=True)

    source_connection = sqlite3.connect(source, timeout=30)
    snapshot_connection = sqlite3.connect(temporary)
    try:
        source_connection.backup(snapshot_connection)
        snapshot_connection.execute("PRAGMA journal_mode=DELETE")
        result = snapshot_connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise RuntimeError(f"Snapshot integrity check failed: {result}")
        snapshot_connection.commit()
    finally:
        snapshot_connection.close()
        source_connection.close()

    os.chmod(temporary, 0o444)
    os.replace(temporary, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a read-only Grafana SQLite snapshot")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    prepare_database(args.source, args.destination)
    print(f"Prepared Grafana snapshot: {args.destination}")


if __name__ == "__main__":
    main()
