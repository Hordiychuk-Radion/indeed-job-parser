from pathlib import Path

import pytest

from indeed_job_parser.config import ConfigError, load_config


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
    assert config.filters.max_experience_years == 5
    assert config.storage.database_path == tmp_path / "data/jobs.db"


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
