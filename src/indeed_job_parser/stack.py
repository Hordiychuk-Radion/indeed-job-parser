from __future__ import annotations

import re
from collections.abc import Mapping


STACK_CATALOG: Mapping[str, tuple[tuple[str, str], ...]] = {
    "languages": (
        ("Python", r"\bpython\b"),
        ("SQL", r"\bsql\b"),
        ("Scala", r"\bscala\b"),
        ("Java", r"\bjava\b"),
        ("R", r"(?<![\w.&])(?-i:R)(?![\w.&])"),
        ("Bash", r"\bbash\b|\bshell scripting\b"),
    ),
    "cloud": (
        ("AWS", r"\baws\b|\bamazon web services\b"),
        ("Microsoft Azure", r"\b(?:microsoft )?azure\b"),
        ("Google Cloud", r"\bgcp\b|\bgoogle cloud(?: platform)?\b"),
    ),
    "data_platforms": (
        ("Databricks", r"\bdatabricks\b"),
        ("Snowflake", r"\bsnowflake\b"),
        ("Microsoft Fabric", r"\bmicrosoft fabric\b|\bfabric data\b"),
        ("BigQuery", r"\bbigquery\b|\bbig query\b"),
        ("Amazon Redshift", r"\bredshift\b"),
        ("Azure Synapse", r"\b(?:azure )?synapse\b"),
    ),
    "processing_streaming": (
        ("Apache Spark", r"\b(?:apache )?spark\b|\bpyspark\b"),
        ("Apache Kafka", r"\b(?:apache )?kafka\b"),
        ("Apache Flink", r"\b(?:apache )?flink\b"),
        ("Apache Beam", r"\b(?:apache )?beam\b"),
        ("Hadoop", r"\bhadoop\b"),
    ),
    "orchestration_transformation": (
        ("Apache Airflow", r"\b(?:apache )?airflow\b"),
        ("dbt", r"(?<![\w])dbt(?![\w])"),
        ("Azure Data Factory", r"\bazure data factory\b|\bADF\b"),
        ("Dagster", r"\bdagster\b"),
        ("Prefect", r"\bprefect\b"),
        ("Luigi", r"\bluigi\b"),
    ),
    "databases": (
        ("PostgreSQL", r"\bpostgres(?:ql)?\b"),
        ("MySQL", r"\bmysql\b"),
        ("Microsoft SQL Server", r"\b(?:microsoft )?sql server\b|\bmssql\b"),
        ("Oracle Database", r"\boracle(?: database| db)?\b"),
        ("MongoDB", r"\bmongodb\b|\bmongo db\b"),
        ("Cassandra", r"\bcassandra\b"),
        ("Redis", r"\bredis\b"),
        ("Elasticsearch", r"\belasticsearch\b|\belastic search\b"),
    ),
    "devops": (
        ("Docker", r"\bdocker\b"),
        ("Kubernetes", r"\bkubernetes\b|\bk8s\b"),
        ("Terraform", r"\bterraform\b"),
        ("Jenkins", r"\bjenkins\b"),
        ("GitHub Actions", r"\bgithub actions\b"),
        ("GitLab CI/CD", r"\bgitlab ci(?:/cd)?\b|\bgitlab pipelines?\b"),
        ("Argo CD", r"\bargo ?cd\b"),
    ),
    "analytics_bi": (
        ("Power BI", r"\bpower ?bi\b"),
        ("Tableau", r"\btableau\b"),
        ("Looker", r"\blooker\b"),
        ("Qlik", r"\bqlik(?:view| sense)?\b"),
    ),
}

_COMPILED_CATALOG = {
    category: tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in entries)
    for category, entries in STACK_CATALOG.items()
}


def extract_stack(text: str | None) -> dict[str, list[str]]:
    """Extract canonical technologies from vacancy text into stable categories."""
    source = text or ""
    return {
        category: [name for name, pattern in entries if pattern.search(source)]
        for category, entries in _COMPILED_CATALOG.items()
    }


def flatten_stack(stack: Mapping[str, list[str]]) -> list[str]:
    """Return technologies in stable category/catalog order without duplicates."""
    seen: set[str] = set()
    flattened: list[str] = []
    for technologies in stack.values():
        for technology in technologies:
            if technology not in seen:
                seen.add(technology)
                flattened.append(technology)
    return flattened
