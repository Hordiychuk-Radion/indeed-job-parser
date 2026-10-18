from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path


PROFILE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProfileDraft:
    name: str
    titles: tuple[str, ...]
    seniority: tuple[str, ...]
    country: str
    country_code: str
    location: str
    results_per_query: int = 50
    days_old: int = 14
    distance_km: int = 80
    remote_only: bool = False
    max_experience_years: int = 5
    include_unknown: bool = True


def discover_profiles(profiles_dir: str | Path) -> dict[str, Path]:
    directory = Path(profiles_dir)
    if not directory.is_dir():
        return {}
    return {
        path.stem: path
        for path in sorted(directory.glob("*.toml"), key=lambda candidate: candidate.stem)
        if PROFILE_NAME_PATTERN.fullmatch(path.stem)
    }


def resolve_profile(name: str, profiles_dir: str | Path) -> Path:
    if not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ProfileError(f"Invalid profile name: {name}")
    profiles = discover_profiles(profiles_dir)
    try:
        return profiles[name]
    except KeyError as error:
        raise ProfileError(f"Unknown profile: {name}") from error


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def write_profile(draft: ProfileDraft, profiles_dir: str | Path) -> Path:
    if not PROFILE_NAME_PATTERN.fullmatch(draft.name):
        raise ProfileError("Profile name must use lowercase letters, digits, and hyphens")
    if not draft.titles:
        raise ProfileError("Profile must contain at least one title")
    directory = Path(profiles_dir)
    path = directory / f"{draft.name}.toml"
    if path.exists():
        raise ProfileError(f"Profile already exists: {draft.name}")
    directory.mkdir(parents=True, exist_ok=True)
    seniority_line = (
        f"allowed_seniority = {_toml_list(draft.seniority)}\n" if draft.seniority else ""
    )
    content = (
        "[search]\n"
        f"country = {_toml_string(draft.country)}\n"
        f"country_code = {_toml_string(draft.country_code.upper())}\n"
        f"location = {_toml_string(draft.location)}\n"
        f"queries = {_toml_list(draft.titles)}\n"
        f"results_per_query = {draft.results_per_query}\n"
        f"days_old = {draft.days_old}\n"
        f"distance_km = {draft.distance_km}\n"
        f"remote_only = {str(draft.remote_only).lower()}\n"
        "\n[filters]\n"
        f"max_experience_years = {draft.max_experience_years}\n"
        f"include_unknown = {str(draft.include_unknown).lower()}\n"
        f"{seniority_line}"
        f"include_title_patterns = {_toml_list(draft.titles)}\n"
        "\n[storage]\n"
        'database_path = "../../data/jobs.db"\n'
        f'output_dir = "../../output/profiles/{draft.name}"\n'
    )
    path.write_text(content, encoding="utf-8")
    return path
