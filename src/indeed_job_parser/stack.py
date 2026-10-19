from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


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

CONCEPT_CATALOG: tuple[tuple[str, str], ...] = (
    ("ETL/ELT", r"\b(?:etl|elt)(?:\s*/\s*(?:etl|elt))?\b"),
    ("Data Quality", r"\bdata quality\b|\bqualit[ée] des donn[ée]es\b"),
    ("Data Modeling", r"\bdata modell?ing\b|\bmod[ée]lisation des donn[ée]es\b"),
    ("Lakehouse", r"\blakehouse\b"),
    ("Data Warehouse", r"\bdata warehouse\b|\bdata warehousing\b"),
    ("Data Lake", r"\bdata lake\b"),
    ("CI/CD", r"\bci\s*/\s*cd\b|\bcontinuous integration\b"),
    ("NLP", r"\bnlp\b|\bnatural language processing\b|\btraitement automatique du langage\b"),
    ("Machine Learning", r"\bmachine learning\b"),
    ("Data Governance", r"\bdata governance\b|\bgouvernance des donn[ée]es\b"),
)
_COMPILED_CONCEPTS = tuple(
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in CONCEPT_CATALOG
)
_TECHNOLOGY_MENTION_CATALOG = tuple(
    (technology, pattern, category)
    for category, entries in _COMPILED_CATALOG.items()
    for technology, pattern in entries
)
_CONCEPT_MENTION_CATALOG = tuple(
    (concept, pattern, "") for concept, pattern in _COMPILED_CONCEPTS
)

_REQUIREMENT_HEADINGS = re.compile(
    r"^(?:requirements?|required qualifications?|qualifications?|profile required|"
    r"profil recherch[ée]|comp[ée]tences requises)$",
    re.IGNORECASE,
)
_PREFERRED_HEADINGS = re.compile(
    r"^(?:nice to have|bonus points?|preferred qualifications?|preferred|assets?|atouts?)$",
    re.IGNORECASE,
)
_RESPONSIBILITY_HEADINGS = re.compile(
    r"^(?:responsibilities|responsabilit[ée]s|missions?|the role|le poste)$",
    re.IGNORECASE,
)
_PREFERRED_CUES = re.compile(
    r"\b(?:nice to have|preferred|would be a plus|is a plus|bonus|advantageous|"
    r"constitue un atout|serait un plus|id[ée]alement|souhait[ée])\b",
    re.IGNORECASE,
)
_REQUIRED_CUES = re.compile(
    r"\b(?:required|must have|must possess|strong (?:knowledge|experience)|"
    r"proficien(?:t|cy)|hands-on experience|minimum \d+|\d+\+? years? of)\b",
    re.IGNORECASE,
)
_ALTERNATIVE_CUES = re.compile(
    r"\b(?:or relevant experience with|relevant alternatives?|acceptable alternatives?|"
    r"substitute such as|one of (?:the )?following)\b",
    re.IGNORECASE,
)
_MENTION_PRIORITY = {"mentioned": 1, "alternative": 2, "preferred": 3, "required": 4}


@dataclass(frozen=True, slots=True)
class TechnologyMention:
    category: str
    technology: str
    requirement_type: str
    section: str | None
    evidence_text: str


@dataclass(frozen=True, slots=True)
class ConceptMention:
    concept: str
    requirement_type: str
    section: str | None
    evidence_text: str


def _clean_heading(line: str) -> str:
    return re.sub(r"^[\s#*_\-]+|[\s:*_\-]+$", "", line).strip()


def _heading_type(line: str) -> str | None:
    heading = _clean_heading(line)
    if _REQUIREMENT_HEADINGS.fullmatch(heading):
        return "required"
    if _PREFERRED_HEADINGS.fullmatch(heading):
        return "preferred"
    if _RESPONSIBILITY_HEADINGS.fullmatch(heading):
        return "mentioned"
    return None


def _iter_evidence(text: str) -> list[tuple[str | None, str, str | None]]:
    section: str | None = None
    section_type: str | None = None
    buffer: list[str] = []
    evidence: list[tuple[str | None, str, str | None]] = []

    def flush() -> None:
        if buffer:
            evidence.append((section, " ".join(buffer).strip(), section_type))
            buffer.clear()

    for raw_line in (text or "").splitlines():
        line = raw_line.strip().strip("* ")
        if not line:
            flush()
            continue
        heading_type = _heading_type(line)
        if heading_type is not None:
            flush()
            section = _clean_heading(line)
            section_type = heading_type
            continue
        inline_heading, separator, remainder = line.partition(":")
        inline_type = _heading_type(inline_heading) if separator else None
        if inline_type is not None and remainder.strip():
            flush()
            section = _clean_heading(inline_heading)
            section_type = inline_type
            line = remainder.strip()
        buffer.append(line)
        if re.search(r"[.!?;:]$", line):
            flush()
    flush()
    return evidence


def _classify_mention(
    evidence: str,
    match_start: int,
    section_type: str | None,
) -> str:
    alternative = _ALTERNATIVE_CUES.search(evidence)
    if alternative:
        alternative_start = alternative.start()
        if "relevant alternative" in alternative.group(0).casefold():
            with_matches = list(
                re.finditer(r"\bwith\b", evidence[: alternative.start()], re.IGNORECASE)
            )
            if with_matches:
                alternative_start = with_matches[-1].end()
        if "one of" in alternative.group(0).casefold() or match_start >= alternative_start:
            return "alternative"
    if section_type == "preferred" or _PREFERRED_CUES.search(evidence):
        return "preferred"
    if section_type == "required" or _REQUIRED_CUES.search(evidence):
        return "required"
    return "mentioned"


def _without_links_and_emails(evidence: str) -> str:
    return re.sub(
        r"https?://\S+|\b[^\s@]+@[^\s@]+\b",
        lambda match: " " * len(match.group(0)),
        evidence,
        flags=re.IGNORECASE,
    )


def _extract_mentions(
    text: str | None,
    catalog: tuple[tuple[str, re.Pattern[str], str], ...],
) -> list[tuple[str, str, str, str | None, str]]:
    selected: dict[str, tuple[str, str, str, str | None, str]] = {}
    for section, evidence, section_type in _iter_evidence(text or ""):
        searchable = _without_links_and_emails(evidence)
        for name, pattern, category in catalog:
            match = pattern.search(searchable)
            if match is None:
                continue
            requirement_type = _classify_mention(searchable, match.start(), section_type)
            mention = (name, category, requirement_type, section, evidence)
            current = selected.get(name)
            if current is None or _MENTION_PRIORITY[requirement_type] > _MENTION_PRIORITY[current[2]]:
                selected[name] = mention
    return list(selected.values())


def extract_technology_mentions(text: str | None) -> list[TechnologyMention]:
    """Extract technologies with deterministic context and auditable evidence."""
    return [
        TechnologyMention(category, name, requirement_type, section, evidence)
        for name, category, requirement_type, section, evidence in _extract_mentions(
            text,
            _TECHNOLOGY_MENTION_CATALOG,
        )
    ]


def extract_concept_mentions(text: str | None) -> list[ConceptMention]:
    """Extract non-tool data concepts separately from the technology stack."""
    return [
        ConceptMention(name, requirement_type, section, evidence)
        for name, _category, requirement_type, section, evidence in _extract_mentions(
            text,
            _CONCEPT_MENTION_CATALOG,
        )
    ]


def extract_stack(text: str | None) -> dict[str, list[str]]:
    """Extract canonical technologies from vacancy text into stable categories."""
    source = _without_links_and_emails(text or "")
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
