from pathlib import Path

import pytest

from indeed_job_parser.config import ConfigError, ConfigOverrides, load_config


def test_loads_toml_config_and_resolves_relative_paths(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '''
[search]
country = "Czech Republic"
country_code = "CZ"
location = "Prague"
queries = ["QA Engineer", "Data Quality Analyst"]
results_per_query = 25
days_old = 14
distance_km = 80
remote_only = false

[filters]
max_experience_years = 5
include_unknown = true
min_salary = 60000
salary_currency = "CZK"

[storage]
database_path = "data/jobs.db"
output_dir = "output"
'''
    )
    config = load_config(config_file)
    assert config.search.queries == ("QA Engineer", "Data Quality Analyst")
    assert config.filters.include_title_patterns == ("QA Engineer", "Data Quality Analyst")
    assert "junior" in config.filters.exclude_title_patterns
    assert "internship" in config.filters.exclude_title_patterns
    assert "team lead" in config.filters.exclude_title_patterns
    assert config.filters.max_experience_years == 5
    assert config.storage.database_path == tmp_path / "data/jobs.db"


def test_loads_explicit_role_patterns(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '''
[search]
country = "Germany"
country_code = "DE"
location = "Berlin"
queries = ["Data Engineer"]

[filters]
include_title_patterns = ["Data Engineer", "ETL Developer"]
exclude_title_patterns = ["Lead", "Manager"]

[storage]
database_path = "jobs.db"
output_dir = "output"
'''
    )

    config = load_config(config_file)

    assert config.filters.include_title_patterns == ("Data Engineer", "ETL Developer")
    assert config.filters.exclude_title_patterns == ("Lead", "Manager")


def test_cli_overrides_replace_runtime_search_and_role_values(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '''
[search]
country = "Czech Republic"
country_code = "CZ"
location = "Prague"
queries = ["QA Engineer"]
results_per_query = 25
remote_only = false

[filters]
max_experience_years = 5

[storage]
database_path = "jobs.db"
output_dir = "output"
'''
    )

    config = load_config(
        config_file,
        overrides=ConfigOverrides(
            titles=("Data Engineer", "ETL Developer"),
            country="Germany",
            country_code="de",
            location="Berlin",
            results_per_query=50,
            remote_only=True,
            max_experience_years=4,
        ),
    )

    assert config.search.queries == ("Data Engineer", "ETL Developer")
    assert config.filters.include_title_patterns == ("Data Engineer", "ETL Developer")
    assert config.search.country == "Germany"
    assert config.search.country_code == "DE"
    assert config.search.location == "Berlin"
    assert config.search.results_per_query == 50
    assert config.search.remote_only is True
    assert config.filters.max_experience_years == 4


def test_rejects_empty_queries(tmp_path: Path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        '''
[search]
country = "Czech Republic"
country_code = "CZ"
location = "Prague"
queries = []

[storage]
database_path = "jobs.db"
output_dir = "output"
'''
    )
    with pytest.raises(ConfigError, match="queries"):
        load_config(config_file)
