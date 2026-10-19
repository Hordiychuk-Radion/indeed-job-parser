from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class CollectionAlreadyRunning(RuntimeError):
    pass


@contextmanager
def collection_lock(database_path: str | Path) -> Iterator[int]:
    lock_path = Path(database_path).with_suffix(Path(database_path).suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CollectionAlreadyRunning(
                f"Collection already running for {Path(database_path)}"
            ) from exc
        try:
            yield handle.fileno()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
