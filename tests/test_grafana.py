from __future__ import annotations

import json
import runpy
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "grafana" / "dashboards"
EXPECTED = {
    "overview.json": "jobs-overview",
    "technology-demand.json": "jobs-technology-demand",
    "geography.json": "jobs-geography",
    "candidate-fit.json": "jobs-candidate-fit",
    "vacancy-explorer.json": "jobs-vacancy-explorer",
}
DATASOURCE = {"type": "frser-sqlite-datasource", "uid": "jobs-sqlite"}


def _panels(dashboard: dict) -> list[dict]:
    return [panel for panel in dashboard["panels"] if panel.get("type") != "row"]


def _render_for_sqlite(query: str) -> str:
    replacements = {
        "${country:raw}": "__all",
        "${country:sqlstring}": "'__all'",
        "${requirement:raw}": "__all",
        "${requirement:sqlstring}": "'__all'",
        "${eligibility:raw}": "__all",
        "${eligibility:sqlstring}": "'__all'",
        "${remote:raw}": "__all",
        "${remote:sqlstring}": "'__all'",
    }
    for marker, value in replacements.items():
        query = query.replace(marker, value)
    return query


def _test_database() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE europe_jobs (
            id INTEGER PRIMARY KEY,
            title TEXT,
            company TEXT,
            country_code TEXT,
            location TEXT,
            is_remote INTEGER,
            scope_eligibility TEXT,
            required_experience_years INTEGER,
            published_at TEXT,
            employment_type TEXT,
            canonical_url TEXT
        );
        CREATE TABLE job_technologies (
            job_id INTEGER,
            category TEXT,
            technology TEXT,
            requirement_type TEXT,
            section TEXT,
            evidence_text TEXT
        );
        INSERT INTO europe_jobs VALUES (
            1, 'Data Engineer', 'Example', 'CZ', 'Prague', 1,
            'eligible', 3, '2026-10-12', 'fulltime', 'https://example.com/job/1'
        );
        INSERT INTO job_technologies VALUES (
            1, 'languages', 'Python', 'required', 'Requirements', 'Python is required.'
        );
        """
    )
    return connection


def test_grafana_bundle_has_provisioning_and_five_dashboards():
    compose = (ROOT / "docker-compose.grafana.yml").read_text(encoding="utf-8")
    datasource = (ROOT / "grafana" / "provisioning" / "datasources" / "jobs.yaml").read_text(
        encoding="utf-8"
    )
    provider = (ROOT / "grafana" / "provisioning" / "dashboards" / "jobs.yaml").read_text(
        encoding="utf-8"
    )

    assert "grafana/grafana:13.2.4@sha256:" in compose
    assert "python:3.11-alpine@sha256:" in compose
    assert "frser-sqlite-datasource@4.0.6" in compose
    assert "prepare-grafana-db:" in compose
    assert "./data:/source" in compose
    assert "grafana-report-data:/data:ro" in compose
    assert "./data:/data" not in compose
    assert "uid: jobs-sqlite" in datasource
    assert "path: /data/jobs.db" in datasource
    assert "editable: false" in datasource
    assert "/var/lib/grafana/dashboards" in provider
    assert {path.name for path in DASHBOARD_DIR.glob("*.json")} == set(EXPECTED)


def test_prepares_a_consistent_read_only_reporting_snapshot(tmp_path: Path):
    namespace = runpy.run_path(str(ROOT / "scripts" / "prepare_grafana_database.py"))
    source = tmp_path / "source.db"
    destination = tmp_path / "report" / "jobs.db"
    connection = sqlite3.connect(source)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT)")
    connection.execute("INSERT INTO jobs VALUES (1, 'Data Engineer')")
    connection.commit()

    namespace["prepare_database"](source, destination)

    report = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    try:
        assert report.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert report.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert report.execute("SELECT * FROM jobs").fetchall() == [(1, "Data Engineer")]
    finally:
        report.close()
        connection.close()


def test_generated_dashboards_match_the_committed_artifacts():
    namespace = runpy.run_path(str(ROOT / "scripts" / "build_grafana_dashboards.py"))
    generated = namespace["build"]()

    assert set(generated) == set(EXPECTED)
    for filename, payload in generated.items():
        committed = json.loads((DASHBOARD_DIR / filename).read_text(encoding="utf-8"))
        assert payload == committed


def test_dashboards_have_stable_contract_and_executable_queries():
    connection = _test_database()
    try:
        seen_uids: set[str] = set()
        for filename, expected_uid in EXPECTED.items():
            dashboard = json.loads((DASHBOARD_DIR / filename).read_text(encoding="utf-8"))
            assert dashboard["uid"] == expected_uid
            assert dashboard["uid"] not in seen_uids
            seen_uids.add(dashboard["uid"])
            assert dashboard["title"].startswith("Jobs · ")
            assert dashboard["schemaVersion"] >= 41
            assert dashboard["tags"] == ["indeed", "data-engineer", "europe"]
            assert len(_panels(dashboard)) >= 4
            assert ":raw}" not in json.dumps(dashboard)
            for variable in dashboard["templating"]["list"]:
                assert variable["includeAll"] is False
                assert variable["current"] == {"text": "All", "value": "__all"}
                assert "SELECT 'All' AS __text, '__all' AS __value" in variable["query"]
                assert connection.execute(variable["query"]).fetchone() == ("All", "__all")

            for panel in _panels(dashboard):
                assert panel["datasource"] == DATASOURCE
                assert panel["title"]
                assert panel["targets"]
                for target in panel["targets"]:
                    assert target["datasource"] == DATASOURCE
                    query = _render_for_sqlite(target["queryText"])
                    connection.execute(f"SELECT * FROM ({query.rstrip().rstrip(';')}) LIMIT 1").fetchall()
    finally:
        connection.close()


def test_vacancy_explorer_exposes_clickable_url_and_evidence():
    dashboard = json.loads(
        (DASHBOARD_DIR / "vacancy-explorer.json").read_text(encoding="utf-8")
    )
    table = next(panel for panel in dashboard["panels"] if panel["title"] == "Vacancies")
    query = table["targets"][0]["queryText"]

    assert "canonical_url AS URL" in query
    assert "required_stack" in query
    assert "preferred_stack" in query
    assert "alternatives" in query
    assert "evidence" in query
    assert any(
        override.get("matcher", {}).get("options") == "URL"
        and any(prop.get("id") == "links" for prop in override.get("properties", []))
        for override in table["fieldConfig"]["overrides"]
    )


def test_candidate_fit_excludes_incompatible_titles_and_unconfirmed_senior_roles():
    dashboard = json.loads(
        (DASHBOARD_DIR / "candidate-fit.json").read_text(encoding="utf-8")
    )
    queries = "\n".join(
        target["queryText"]
        for panel in dashboard["panels"]
        for target in panel["targets"]
    ).lower()

    for marker in ("junior", "lead", "principal", "staff", "manager", "director"):
        assert f"%{marker}%" in queries
    assert "not like '%senior%'" in queries
    assert "scope_eligibility = 'eligible'" in queries
