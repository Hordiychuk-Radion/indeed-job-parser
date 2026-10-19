import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from indeed_job_parser.models import JobRecord
from indeed_job_parser.repository import JobRepository, inspect_database
from indeed_job_parser.stack import ConceptMention, TechnologyMention


def sample_job() -> JobRecord:
    return JobRecord(
        dedupe_key="key-1",
        source="indeed",
        source_job_id="abc",
        query="QA Engineer",
        title="QA Engineer",
        company="Example",
        location="Prague",
        country_code="CZ",
        description="Test APIs",
        canonical_url="https://cz.indeed.com/viewjob?jk=abc",
        published_at="2026-09-30",
        employment_type="fulltime",
        is_remote=False,
        salary_min=60000,
        salary_max=80000,
        salary_currency="CZK",
        salary_period="monthly",
        eligibility="unknown",
        eligibility_reason="experience_not_stated",
    )


def test_initializes_wal_schema(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        mode = repository.connection.execute("PRAGMA journal_mode").fetchone()[0]
        tables = {
            row[0]
            for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert mode == "wal"
    assert {
        "jobs",
        "ingestion_runs",
        "job_observations",
        "job_technologies",
        "search_scopes",
        "scope_jobs",
    }.issubset(tables)


def test_migrates_legacy_ingestion_runs_with_no_scope_column(tmp_path: Path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE ingestion_runs (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, rows_received INTEGER NOT NULL DEFAULT 0,
                rows_eligible INTEGER NOT NULL DEFAULT 0,
                rows_unknown INTEGER NOT NULL DEFAULT 0,
                rows_rejected INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0, error_message TEXT,
                config_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO ingestion_runs (id, started_at, status, config_json) "
            "VALUES ('legacy-run', '2026-01-01T00:00:00Z', 'succeeded', '{}')"
        )

    with JobRepository(database) as repository:
        columns = {
            row[1] for row in repository.connection.execute(
                "PRAGMA table_info(ingestion_runs)"
            )
        }
        legacy = repository.connection.execute(
            "SELECT id, scope_key FROM ingestion_runs WHERE id='legacy-run'"
        ).fetchone()

    assert "scope_key" in columns
    assert tuple(legacy) == ("legacy-run", None)


def test_one_job_can_belong_to_europe_and_country_scopes(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        repository.ensure_scope("europe:data-engineer", "europe", label="Europe Data Engineer")
        repository.ensure_scope(
            "country:DE", "country", country_code="DE", label="Germany"
        )
        run_id = repository.start_run(
            {"mode": "country"}, scope_key="country:DE"
        )
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_scope_jobs(
            "country:DE", [(job_id, "unknown", "experience_not_stated")]
        )
        repository.replace_scope_jobs(
            "europe:data-engineer",
            [(job_id, "eligible", "title_matches_data_engineer")],
        )

        jobs = repository.connection.execute("SELECT count(*) FROM jobs").fetchone()[0]
        memberships = repository.connection.execute(
            "SELECT scope_key, eligibility FROM scope_jobs ORDER BY scope_key"
        ).fetchall()

    assert jobs == 1
    assert [tuple(row) for row in memberships] == [
        ("country:DE", "unknown"),
        ("europe:data-engineer", "eligible"),
    ]


def test_replacing_one_scope_preserves_other_scope_memberships(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        repository.ensure_scope("europe:data-engineer", "europe", label="Europe")
        repository.ensure_scope("country:DE", "country", country_code="DE", label="Germany")
        run_id = repository.start_run({}, scope_key="country:DE")
        shared_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        country_only_id = repository.save_job(
            run_id,
            replace(sample_job(), dedupe_key="country-only", source_job_id="country-only"),
            {"raw": 2},
        )
        repository.replace_scope_jobs(
            "country:DE",
            [
                (shared_id, "unknown", "experience_not_stated"),
                (country_only_id, "eligible", "eligible"),
            ],
        )
        repository.replace_scope_jobs(
            "europe:data-engineer", [(shared_id, "eligible", "title_matches")]
        )
        repository.replace_scope_jobs("europe:data-engineer", [])

        country_ids = repository.connection.execute(
            "SELECT job_id FROM scope_jobs WHERE scope_key='country:DE' ORDER BY job_id"
        ).fetchall()
        europe_count = repository.connection.execute(
            "SELECT count(*) FROM scope_jobs WHERE scope_key='europe:data-engineer'"
        ).fetchone()[0]
        country_view_count = repository.connection.execute(
            "SELECT count(*) FROM country_jobs"
        ).fetchone()[0]

    assert [row[0] for row in country_ids] == [shared_id, country_only_id]
    assert europe_count == 0
    assert country_view_count == 2


def test_scope_membership_replacement_deduplicates_repeated_jobs(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        repository.ensure_scope("country:CZ", "country", country_code="CZ", label="Czechia")
        run_id = repository.start_run({}, scope_key="country:CZ")
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})

        repository.replace_scope_jobs(
            "country:CZ",
            [
                (job_id, "unknown", "first_query"),
                (job_id, "eligible", "second_query"),
            ],
        )

        memberships = repository.connection.execute(
            "SELECT job_id, eligibility, eligibility_reason FROM scope_jobs"
        ).fetchall()

    assert [tuple(row) for row in memberships] == [
        (job_id, "eligible", "second_query")
    ]


def test_replaces_structured_job_technologies(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python", "SQL"], "cloud": ["AWS"]},
        )
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python"], "cloud": ["Microsoft Azure"]},
        )
        rows = repository.connection.execute(
            "SELECT category, technology FROM job_technologies WHERE job_id=? "
            "ORDER BY category, technology",
            (job_id,),
        ).fetchall()

    assert [tuple(row) for row in rows] == [
        ("cloud", "Microsoft Azure"),
        ("languages", "Python"),
    ]


def test_persists_contextual_technology_and_concept_evidence(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technology_mentions(
            job_id,
            [
                TechnologyMention(
                    category="data_platforms",
                    technology="Databricks",
                    requirement_type="required",
                    section="Requirements",
                    evidence_text="Databricks experience is required.",
                ),
                TechnologyMention(
                    category="data_platforms",
                    technology="Snowflake",
                    requirement_type="alternative",
                    section="Requirements",
                    evidence_text="Or relevant experience with Snowflake.",
                ),
            ],
        )
        repository.replace_job_concepts(
            job_id,
            [
                ConceptMention(
                    concept="Data Quality",
                    requirement_type="mentioned",
                    section="Responsibilities",
                    evidence_text="Improve data quality.",
                )
            ],
        )
        technologies = repository.connection.execute(
            "SELECT category, technology, requirement_type, section, evidence_text "
            "FROM job_technologies ORDER BY technology"
        ).fetchall()
        concepts = repository.connection.execute(
            "SELECT concept, requirement_type, section, evidence_text FROM job_concepts"
        ).fetchall()

    assert [tuple(row) for row in technologies] == [
        (
            "data_platforms",
            "Databricks",
            "required",
            "Requirements",
            "Databricks experience is required.",
        ),
        (
            "data_platforms",
            "Snowflake",
            "alternative",
            "Requirements",
            "Or relevant experience with Snowflake.",
        ),
    ]
    assert [tuple(row) for row in concepts] == [
        (
            "Data Quality",
            "mentioned",
            "Responsibilities",
            "Improve data quality.",
        )
    ]


def test_can_batch_job_and_stack_writes_in_one_transaction(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1}, commit=False)
        repository.replace_job_technologies(
            job_id,
            {"languages": ["Python"]},
            commit=False,
        )
        repository.connection.rollback()
        counts = (
            repository.connection.execute("SELECT count(*) FROM jobs").fetchone()[0],
            repository.connection.execute("SELECT count(*) FROM job_observations").fetchone()[0],
            repository.connection.execute("SELECT count(*) FROM job_technologies").fetchone()[0],
        )

    assert counts == (0, 0, 0)


def test_upsert_preserves_one_job_and_records_each_observation(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"country": "Czech Republic"})
        repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.save_job(run_id, replace(sample_job(), salary_max=90000), {"raw": 2})
        jobs = repository.connection.execute("SELECT count(*), max(salary_max) FROM jobs").fetchone()
        observations = repository.connection.execute(
            "SELECT count(*), max(raw_payload) FROM job_observations"
        ).fetchone()
    assert tuple(jobs) == (1, 90000)
    assert observations[0] == 2
    assert json.loads(observations[1]) == {"raw": 2}


def test_finishes_run_with_auditable_counts(tmp_path: Path):
    with JobRepository(tmp_path / "jobs.db") as repository:
        run_id = repository.start_run({"queries": ["QA Engineer"]})
        repository.finish_run(
            run_id,
            status="succeeded",
            rows_received=10,
            rows_eligible=3,
            rows_unknown=4,
            rows_rejected=3,
            error_count=0,
        )
        run = repository.connection.execute(
            "SELECT status, rows_received, rows_eligible, rows_unknown, rows_rejected, error_count, finished_at "
            "FROM ingestion_runs WHERE id=?",
            (run_id,),
        ).fetchone()
    assert tuple(run[:6]) == ("succeeded", 10, 3, 4, 3, 0)
    assert run[6]


def test_inspects_database_with_descriptions_and_stack(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        run_id = repository.start_run({"queries": ["QA Engineer"]})
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technology_mentions(
            job_id,
            [
                TechnologyMention(
                    category="languages",
                    technology="Python",
                    requirement_type="required",
                    section="Requirements",
                    evidence_text="Python is required.",
                ),
                TechnologyMention(
                    category="cloud",
                    technology="AWS",
                    requirement_type="preferred",
                    section="Nice to Have",
                    evidence_text="AWS is a plus.",
                ),
            ],
        )
        repository.replace_job_concepts(
            job_id,
            [
                ConceptMention(
                    concept="Data Quality",
                    requirement_type="mentioned",
                    section="Responsibilities",
                    evidence_text="Improve data quality.",
                )
            ],
        )
        repository.ensure_scope(
            "country:CZ", "country", country_code="CZ", label="Czech Republic"
        )
        repository.replace_scope_jobs(
            "country:CZ", [(job_id, "unknown", "experience_not_stated")]
        )
        repository.finish_run(
            run_id,
            status="succeeded",
            rows_received=1,
            rows_eligible=0,
            rows_unknown=1,
            rows_rejected=0,
            error_count=0,
        )

    payload = inspect_database(database, limit=5)

    assert payload["counts"] == {"jobs": 1, "observations": 1, "runs": 1}
    assert payload["scopes"] == [
        {
            "scope_key": "country:CZ",
            "scope_type": "country",
            "country_code": "CZ",
            "label": "Czech Republic",
            "jobs": 1,
        }
    ]
    assert payload["eligibility_counts"] == {"unknown": 1}
    assert payload["technology_counts"] == [
        {"technology": "AWS", "jobs": 1},
        {"technology": "Python", "jobs": 1},
    ]
    assert payload["recent_jobs"][0]["description"] == "Test APIs"
    assert payload["recent_jobs"][0]["eligibility"] == "unknown"
    assert payload["recent_jobs"][0]["stack"] == {
        "cloud": ["AWS"],
        "languages": ["Python"],
    }
    assert payload["recent_jobs"][0]["technology_mentions"] == [
        {
            "category": "cloud",
            "technology": "AWS",
            "requirement_type": "preferred",
            "section": "Nice to Have",
            "evidence_text": "AWS is a plus.",
        },
        {
            "category": "languages",
            "technology": "Python",
            "requirement_type": "required",
            "section": "Requirements",
            "evidence_text": "Python is required.",
        },
    ]
    assert payload["recent_jobs"][0]["concepts"] == [
        {
            "concept": "Data Quality",
            "requirement_type": "mentioned",
            "section": "Responsibilities",
            "evidence_text": "Improve data quality.",
        }
    ]


def test_abandon_stale_runs_marks_only_expired_running_rows(tmp_path: Path):
    database = tmp_path / "jobs.db"
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    with JobRepository(database) as repository:
        stale = repository.start_run({"name": "stale"})
        recent = repository.start_run({"name": "recent"})
        repository.connection.execute(
            "UPDATE ingestion_runs SET started_at=? WHERE id=?",
            ((now - timedelta(hours=25)).isoformat(), stale),
        )
        repository.connection.execute(
            "UPDATE ingestion_runs SET started_at=? WHERE id=?",
            ((now - timedelta(hours=1)).isoformat(), recent),
        )
        changed = repository.abandon_stale_runs(
            older_than=timedelta(hours=24), now=now
        )
        statuses = dict(repository.connection.execute(
            "SELECT id, status FROM ingestion_runs"
        ).fetchall())

    assert changed == 1
    assert statuses == {stale: "abandoned", recent: "running"}


def test_scope_publication_records_lifecycle_and_trend_snapshots(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        repository.ensure_scope("country:CZ", "country", country_code="CZ", label="Czechia")
        first_run = repository.start_run({"run": 1}, scope_key="country:CZ")
        first = repository.save_job(first_run, sample_job(), {"run": 1})
        second_job = replace(
            sample_job(),
            dedupe_key="key-2",
            source_job_id="def",
            canonical_url="https://cz.indeed.com/viewjob?jk=def",
        )
        second = repository.save_job(first_run, second_job, {"run": 1})
        repository.replace_job_technology_mentions(
            first,
            [TechnologyMention("languages", "Python", "required", "requirements", "Python required")],
        )
        repository.replace_scope_jobs(
            "country:CZ",
            [(first, "unknown", "experience_not_stated"), (second, "unknown", "experience_not_stated")],
            run_id=first_run,
            observed_at="2026-10-12T00:00:00+00:00",
        )

        second_run = repository.start_run({"run": 2}, scope_key="country:CZ")
        third_job = replace(
            sample_job(),
            dedupe_key="key-3",
            source_job_id="ghi",
            canonical_url="https://cz.indeed.com/viewjob?jk=ghi",
        )
        third = repository.save_job(second_run, third_job, {"run": 2})
        repository.replace_scope_jobs(
            "country:CZ",
            [(second, "unknown", "experience_not_stated"), (third, "unknown", "experience_not_stated")],
            run_id=second_run,
            observed_at="2026-10-19T00:00:00+00:00",
        )

        lifecycle = [tuple(row) for row in repository.connection.execute(
            "SELECT job_id, status, closed_at FROM scope_job_lifecycle ORDER BY job_id"
        ).fetchall()]
        job_statuses = [tuple(row) for row in repository.connection.execute(
            "SELECT id, status FROM jobs ORDER BY id"
        ).fetchall()]
        snapshots = [tuple(row) for row in repository.connection.execute(
            "SELECT run_id, job_count FROM scope_snapshots ORDER BY captured_at"
        ).fetchall()]
        technology = [tuple(row) for row in repository.connection.execute(
            "SELECT run_id, technology, requirement_type, vacancy_count "
            "FROM technology_snapshots WHERE country_code='__all'"
        ).fetchall()]

    assert lifecycle == [
        (first, "closed", "2026-10-19T00:00:00+00:00"),
        (second, "active", None),
        (third, "active", None),
    ]
    assert job_statuses == [(first, "inactive"), (second, "active"), (third, "active")]
    assert snapshots == [(first_run, 2), (second_run, 2)]
    assert technology == [(first_run, "Python", "required", 1)]


def test_empty_successful_scope_records_zero_snapshot(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        repository.ensure_scope("country:CZ", "country", country_code="CZ", label="Czechia")
        run_id = repository.start_run({"run": "empty"}, scope_key="country:CZ")
        repository.replace_scope_jobs(
            "country:CZ",
            [],
            run_id=run_id,
            observed_at="2026-10-19T00:00:00+00:00",
        )
        snapshot = repository.connection.execute(
            "SELECT job_count, eligible_count, unknown_count, remote_count FROM scope_snapshots"
        ).fetchone()

    assert tuple(snapshot) == (0, 0, 0, 0)


def test_records_run_quality_metrics(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        run_id = repository.start_run({"run": "quality"})
        repository.record_run_quality(
            run_id,
            rows_fresh=10,
            rows_stale=2,
            rows_future=1,
            rows_invalid_date=3,
            rows_missing_date=4,
        )
        metrics = repository.connection.execute(
            "SELECT rows_fresh, rows_stale, rows_future, rows_invalid_date, rows_missing_date "
            "FROM run_quality_metrics WHERE run_id=?",
            (run_id,),
        ).fetchone()

    assert tuple(metrics) == (10, 2, 1, 3, 4)


def test_run_quality_can_participate_in_publication_transaction(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        scope_key = repository.ensure_scope(
            "country:CZ", "country", country_code="CZ", label="Czech Republic"
        )
        run_id = repository.start_run({}, scope_key=scope_key)
        repository.record_run_quality(
            run_id,
            rows_fresh=1,
            rows_stale=0,
            rows_future=0,
            rows_invalid_date=0,
            rows_missing_date=0,
            commit=False,
        )
        repository.connection.rollback()
        row = repository.connection.execute(
            "SELECT run_id FROM run_quality_metrics WHERE run_id=?",
            (run_id,),
        ).fetchone()

    assert row is None


def test_inspection_counts_technology_when_any_scope_selects_the_job(tmp_path: Path):
    database = tmp_path / "jobs.db"
    with JobRepository(database) as repository:
        repository.ensure_scope("europe:data-engineer", "europe", label="Europe")
        repository.ensure_scope("country:DE", "country", country_code="DE", label="Germany")
        run_id = repository.start_run({}, scope_key="europe:data-engineer")
        job_id = repository.save_job(run_id, sample_job(), {"raw": 1})
        repository.replace_job_technologies(job_id, {"languages": ["Python"]})
        repository.replace_scope_jobs(
            "europe:data-engineer", [(job_id, "eligible", "title_matches")]
        )
        repository.save_job(
            run_id,
            replace(
                sample_job(),
                eligibility="rejected",
                eligibility_reason="country_filter_rejected",
            ),
            {"raw": 2},
        )
        repository.replace_scope_jobs(
            "country:DE", [(job_id, "rejected", "country_filter_rejected")]
        )

    payload = inspect_database(database)

    assert payload["technology_counts"] == [{"technology": "Python", "jobs": 1}]
