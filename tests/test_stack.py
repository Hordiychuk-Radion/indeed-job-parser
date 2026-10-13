from indeed_job_parser.stack import extract_stack


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
