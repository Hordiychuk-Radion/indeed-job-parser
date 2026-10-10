import json
from pathlib import Path

from indeed_job_parser.cli import main
from indeed_job_parser.pipeline import RunSummary


def test_cli_prints_machine_readable_summary(tmp_path: Path, capsys):
    config = tmp_path / "config.toml"
    config.write_text("placeholder")

    def fake_runner(path, *, overrides):
        assert path == config
        assert overrides.titles == ("Data Engineer", "ETL Developer")
        assert overrides.country == "Germany"
        assert overrides.country_code == "DE"
        assert overrides.location == "Berlin"
        assert overrides.days_old == 7
        assert overrides.results_per_query == 50
        assert overrides.remote_only is True
        return RunSummary(
            run_id="run-1",
            rows_received=10,
            rows_eligible=3,
            rows_unknown=4,
            rows_rejected=3,
            error_count=0,
            database_path="data/jobs.db",
            output_dir="output",
        )

    exit_code = main(
        [
            "run",
            "--config",
            str(config),
            "--title",
            "Data Engineer",
            "--title",
            "ETL Developer",
            "--country",
            "Germany",
            "--country-code",
            "DE",
            "--location",
            "Berlin",
            "--days-old",
            "7",
            "--results",
            "50",
            "--remote-only",
        ],
        runner=fake_runner,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["rows_received"] == 10
    assert payload["run_id"] == "run-1"
