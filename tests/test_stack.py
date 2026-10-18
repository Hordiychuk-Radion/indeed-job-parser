from indeed_job_parser.stack import (
    extract_concept_mentions,
    extract_stack,
    extract_technology_mentions,
)


def test_extract_stack_returns_categorized_canonical_technologies():
    text = """
    Build Python and SQL pipelines with Apache Spark on Databricks and AWS.
    Orchestrate jobs in Apache Airflow, stream through Kafka, deploy with Docker,
    Kubernetes and Terraform, and expose datasets to Power BI.
    """

    stack = extract_stack(text)

    assert stack == {
        "languages": ["Python", "SQL"],
        "cloud": ["AWS"],
        "data_platforms": ["Databricks"],
        "processing_streaming": ["Apache Spark", "Apache Kafka"],
        "orchestration_transformation": ["Apache Airflow"],
        "databases": [],
        "devops": ["Docker", "Kubernetes", "Terraform"],
        "analytics_bi": ["Power BI"],
    }


def test_extract_stack_uses_boundaries_and_deduplicates_aliases():
    stack = extract_stack(
        "Experience with dbt/DBT, Microsoft Azure, Azure Data Factory, "
        "PostgreSQL, and GitHub Actions. Candidate communicates clearly."
    )

    assert stack["cloud"] == ["Microsoft Azure"]
    assert stack["orchestration_transformation"] == ["dbt", "Azure Data Factory"]
    assert stack["databases"] == ["PostgreSQL"]
    assert stack["devops"] == ["GitHub Actions"]
    assert "C" not in {tech for values in stack.values() for tech in values}


def test_extract_stack_does_not_treat_research_and_development_as_r_language():
    stack = extract_stack("Join our R&D organization as a data engineer")

    assert "R" not in stack["languages"]


def test_classifies_required_preferred_and_alternative_technologies_with_evidence():
    text = """
    Requirements
    2+ years of advanced experience building production dbt models.
    Databricks experience is required, or relevant experience with Snowflake,
    BigQuery, Microsoft Fabric/Synapse or Redshift.

    Nice to Have
    Azure experience is a plus, with AWS or GCP as relevant alternatives.
    """

    mentions = {mention.technology: mention for mention in extract_technology_mentions(text)}

    assert mentions["dbt"].requirement_type == "required"
    assert mentions["dbt"].section == "Requirements"
    assert mentions["Databricks"].requirement_type == "required"
    assert mentions["Snowflake"].requirement_type == "alternative"
    assert mentions["BigQuery"].requirement_type == "alternative"
    assert mentions["Microsoft Fabric"].requirement_type == "alternative"
    assert mentions["Azure Synapse"].requirement_type == "alternative"
    assert mentions["Amazon Redshift"].requirement_type == "alternative"
    assert "relevant experience with Snowflake" in mentions["Snowflake"].evidence_text
    assert mentions["Microsoft Azure"].requirement_type == "preferred"
    assert mentions["Microsoft Azure"].section == "Nice to Have"
    assert mentions["AWS"].requirement_type == "alternative"
    assert mentions["Google Cloud"].requirement_type == "alternative"


def test_extracts_concepts_separately_from_technology_stack():
    text = """
    Responsibilities
    Build ETL/ELT pipelines, improve data quality, and maintain a lakehouse.
    Nice to have
    Experience with NLP and machine learning would be a plus.
    """

    concepts = {mention.concept: mention for mention in extract_concept_mentions(text)}

    assert set(concepts) == {
        "ETL/ELT",
        "Data Quality",
        "Lakehouse",
        "NLP",
        "Machine Learning",
    }
    assert concepts["ETL/ELT"].section == "Responsibilities"
    assert concepts["NLP"].requirement_type == "preferred"
    assert "machine learning" in concepts["Machine Learning"].evidence_text


def test_french_atout_overrides_required_profile_section():
    text = """
    Profil recherché
    Une expérience avec Dagster ou le traitement automatique du langage constitue un atout.
    Voir l'offre : https://example.com/apply/data-engineer-nlp
    """

    technologies = {item.technology: item for item in extract_technology_mentions(text)}
    concepts = {item.concept: item for item in extract_concept_mentions(text)}

    assert technologies["Dagster"].requirement_type == "preferred"
    assert concepts["NLP"].requirement_type == "preferred"
    assert "Databricks" not in extract_stack(
        "Apply at https://example.com/jobs/senior-databricks-engineer"
    )["data_platforms"]
    url_cue = extract_technology_mentions(
        "Python is used in our stack. See https://example.com/required/aws"
    )
    assert [(item.technology, item.requirement_type) for item in url_cue] == [
        ("Python", "mentioned")
    ]


def test_preserves_inline_section_heading_on_evidence():
    mentions = extract_technology_mentions(
        "Requirements: Python is required.\nNice to have: AWS is a plus."
    )
    by_name = {item.technology: item for item in mentions}

    assert by_name["Python"].section == "Requirements"
    assert by_name["Python"].evidence_text == "Python is required."
    assert by_name["AWS"].section == "Nice to have"
    assert by_name["AWS"].evidence_text == "AWS is a plus."
