from __future__ import annotations

from .repository import JobRepository
from .stack import extract_concept_mentions, extract_technology_mentions


def replace_job_annotations(
    repository: JobRepository,
    job_id: int,
    title: str,
    description: str,
    *,
    commit: bool = True,
) -> None:
    source = f"{title}\n{description}"
    repository.replace_job_technology_mentions(
        job_id,
        extract_technology_mentions(source),
        commit=False,
    )
    repository.replace_job_concepts(
        job_id,
        extract_concept_mentions(source),
        commit=False,
    )
    if commit:
        repository.connection.commit()
