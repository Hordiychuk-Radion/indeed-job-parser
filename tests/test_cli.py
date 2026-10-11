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
        assert overrides.seniority == ("middle",)
        assert overrides.exclude_titles == ("Lead", "Manager")
        assert overrides.salary_period == "yearly"
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
            "--seniority",
            "middle",
            "--exclude-title",
            "Lead",
            "--exclude-title",
            "Manager",
            "--salary-period",
            "yearly",
        ],
        runner=fake_runner,
    )
    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["rows_received"] == 10
    assert payload["run_id"] == "run-1"


def test_cli_runs_named_profile_with_short_command(tmp_path: Path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile = profiles_dir / "data-engineer-middle-de.toml"
    profile.write_text("placeholder")
    received = {}

    def fake_runner(path, *, overrides):
        received["path"] = path
        received["overrides"] = overrides
        return RunSummary(
            run_id="run-profile",
            rows_received=0,
            rows_eligible=0,
            rows_unknown=0,
            rows_rejected=0,
            error_count=0,
            database_path="data/profile.db",
            output_dir="output/profile",
        )

    exit_code = main(
        [
            "run",
            "data-engineer-middle-de",
            "--profiles-dir",
            str(profiles_dir),
            "--results",
            "10",
        ],
        runner=fake_runner,
    )

    assert exit_code == 0
    assert received["path"] == profile
    assert received["overrides"].results_per_query == 10


def test_cli_lists_named_profiles(tmp_path: Path, capsys):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "data-engineer-senior-de.toml").write_text("placeholder")
    (profiles_dir / "data-engineer-middle-de.toml").write_text("placeholder")

    exit_code = main(["profiles", "--profiles-dir", str(profiles_dir)])

    assert exit_code == 0
    assert capsys.readouterr().out.splitlines() == [
        "data-engineer-middle-de",
        "data-engineer-senior-de",
    ]


def test_no_arguments_opens_menu_and_runs_selected_profile(tmp_path: Path):
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile = profiles_dir / "data-engineer-middle-de.toml"
    profile.write_text("placeholder")
    answers = iter(["1", "1"])
    received = {}

    def fake_runner(path, *, overrides):
        received["path"] = path
        return RunSummary(
            run_id="interactive",
            rows_received=0,
            rows_eligible=0,
            rows_unknown=0,
            rows_rejected=0,
            error_count=0,
            database_path="data/profile.db",
            output_dir="output/profile",
        )

    exit_code = main(
        [],
        runner=fake_runner,
        input_fn=lambda _prompt: next(answers),
        profiles_dir=profiles_dir,
    )

    assert exit_code == 0
    assert received["path"] == profile


def test_create_profile_wizard_writes_toml(tmp_path: Path):
    profiles_dir = tmp_path / "config" / "profiles"
    answers = iter(
        [
            "data-engineer-middle-de",
            "Data Engineer, ETL Developer",
            "1",
            "Germany",
            "DE",
            "Berlin",
            "50",
            "14",
            "80",
            "n",
            "5",
            "y",
        ]
    )

    exit_code = main(
        ["create-profile", "--profiles-dir", str(profiles_dir)],
        input_fn=lambda _prompt: next(answers),
    )

    assert exit_code == 0
    text = (profiles_dir / "data-engineer-middle-de.toml").read_text()
    assert 'queries = ["Data Engineer", "ETL Developer"]' in text
    assert 'allowed_seniority = ["middle"]' in text


def test_menu_runs_quick_search_without_saving_profile(tmp_path: Path):
    answers = iter(
        [
            "3",
            "Data Engineer",
            "1",
            "Germany",
            "DE",
            "Berlin",
            "25",
            "7",
            "80",
            "y",
            "5",
            "n",
        ]
    )
    received = {}

    def fake_runner(path, *, overrides):
        received["path"] = path
        received["overrides"] = overrides
        return RunSummary(
            run_id="quick",
            rows_received=0,
            rows_eligible=0,
            rows_unknown=0,
            rows_rejected=0,
            error_count=0,
            database_path="data/jobs.db",
            output_dir="output",
        )

    exit_code = main(
        [],
        runner=fake_runner,
        input_fn=lambda _prompt: next(answers),
        profiles_dir=tmp_path / "profiles",
    )

    assert exit_code == 0
    assert received["path"] == Path("config/example.toml")
    overrides = received["overrides"]
    assert overrides.titles == ("Data Engineer",)
    assert overrides.seniority == ("middle",)
    assert overrides.country == "Germany"
    assert overrides.remote_only is True
    assert overrides.include_unknown is False
