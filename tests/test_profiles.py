from pathlib import Path

import pytest

from indeed_job_parser.config import load_config
from indeed_job_parser.profiles import (
    ProfileDraft,
    ProfileError,
    discover_profiles,
    resolve_profile,
    write_profile,
)


def test_discovers_named_toml_profiles_in_sorted_order(tmp_path: Path):
    (tmp_path / "senior.toml").write_text("senior")
    (tmp_path / "middle.toml").write_text("middle")
    (tmp_path / "ignore.txt").write_text("ignored")

    assert discover_profiles(tmp_path) == {
        "middle": tmp_path / "middle.toml",
        "senior": tmp_path / "senior.toml",
    }


def test_resolves_profile_name_to_toml_path(tmp_path: Path):
    profile = tmp_path / "data-engineer-middle-de.toml"
    profile.write_text("profile")

    assert resolve_profile("data-engineer-middle-de", tmp_path) == profile


def test_rejects_unknown_or_unsafe_profile_names(tmp_path: Path):
    with pytest.raises(ProfileError, match="Unknown profile"):
        resolve_profile("missing", tmp_path)
    with pytest.raises(ProfileError, match="Invalid profile name"):
        resolve_profile("../secret", tmp_path)


def test_writes_loadable_profile_with_shared_database_and_own_output_path(tmp_path: Path):
    profile_path = write_profile(
        ProfileDraft(
            name="data-engineer-middle-de",
            titles=("Data Engineer", "ETL Developer"),
            seniority=("middle",),
            country="Germany",
            country_code="DE",
            location="Berlin",
            results_per_query=50,
            days_old=14,
            distance_km=80,
            remote_only=False,
            max_experience_years=5,
            include_unknown=True,
        ),
        tmp_path / "config" / "profiles",
    )

    config = load_config(profile_path)
    assert config.search.queries == ("Data Engineer", "ETL Developer")
    assert config.filters.allowed_seniority == ("middle",)
    assert config.storage.database_path == tmp_path / "data" / "jobs.db"
    assert config.storage.output_dir == tmp_path / "output" / "profiles" / "data-engineer-middle-de"


def test_refuses_to_overwrite_existing_profile(tmp_path: Path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "existing.toml").write_text("original")
    draft = ProfileDraft(
        name="existing",
        titles=("Data Engineer",),
        seniority=(),
        country="Germany",
        country_code="DE",
        location="Berlin",
    )

    with pytest.raises(ProfileError, match="already exists"):
        write_profile(draft, profiles_dir)
