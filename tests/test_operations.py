import os
from pathlib import Path

import pytest

from indeed_job_parser.operations import CollectionAlreadyRunning, collection_lock


def test_collection_lock_prevents_overlapping_runs(tmp_path: Path):
    database = tmp_path / "jobs.db"

    with collection_lock(database):
        with pytest.raises(CollectionAlreadyRunning):
            with collection_lock(database):
                pass

    with collection_lock(database):
        pass


def test_collection_lock_exposes_inheritable_file_descriptor(tmp_path: Path):
    with collection_lock(tmp_path / "jobs.db") as lock_fd:
        assert isinstance(lock_fd, int)
        assert os.fstat(lock_fd)
