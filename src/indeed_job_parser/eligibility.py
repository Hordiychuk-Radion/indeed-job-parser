from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence

DEFAULT_INCLUDE_TITLE_PATTERNS = (
    "qa",
    "quality assurance",
    "data quality",
    "software tester",
    "software testing",
    "test automation",
    "automation qa",
    "qa automation",
    "sdet",
)
DEFAULT_EXCLUDE_TITLE_PATTERNS = (
    "junior",
    "jr",
    "trainee",
    "intern",
    "internship",
    "graduate",
    "lead",
    "team lead",
    "principal",
    "staff",
    "head",
    "manager",
    "director",
    "chief",
)
SENIOR_PATTERN = re.compile(r"(?:\bsenior\b|\bsr\.?\b)", re.IGNORECASE)
MIDDLE_PATTERN = re.compile(r"(?:\bmiddle\b|\bmid(?:-level)?\b|\bmedior\b|\bexperienced\b)", re.IGNORECASE)
MIDDLE_DESCRIPTION_PATTERN = re.compile(r"\b(?:middle|mid(?:-level)?|medior\w*)\b", re.IGNORECASE)
EXPERIENCE_PATTERNS = (
    re.compile(r"(?:at least|minimum|min\.?|requires?|required)\s*(\d{1,2})\+?\s*(?:years?|yrs?)", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|professional\s+|commercial\s+)?experience\b", re.IGNORECASE),
    re.compile(r"\b(?:praxe|zkušenost(?:i|í)?)\s*:?\s*(\d{1,2})\+?\s*(?:let|roky|roků)\b", re.IGNORECASE),
)


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    status: str
    reason: str
    required_years: int | None = None


def extract_required_years(description: str) -> int | None:
    values = [
        int(match.group(1))
        for pattern in EXPERIENCE_PATTERNS
        for match in pattern.finditer(description or "")
    ]
    return max(values) if values else None


def _matches_title(title: str, patterns: Sequence[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(pattern.strip())}(?!\w)", title, re.IGNORECASE)
        for pattern in patterns
        if pattern.strip()
    )


def evaluate_job(
    row: Mapping[str, object],
    max_experience_years: int = 5,
    *,
    include_title_patterns: Sequence[str] = DEFAULT_INCLUDE_TITLE_PATTERNS,
    exclude_title_patterns: Sequence[str] = DEFAULT_EXCLUDE_TITLE_PATTERNS,
) -> EligibilityDecision:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "")
    if not _matches_title(title, include_title_patterns):
        return EligibilityDecision("rejected", "irrelevant_title")
    if _matches_title(title, exclude_title_patterns):
        return EligibilityDecision("rejected", "excluded_level")

    required_years = extract_required_years(description)
    if required_years is not None and required_years > max_experience_years:
        return EligibilityDecision("rejected", "experience_above_limit", required_years)
    if SENIOR_PATTERN.search(title):
        if required_years is None:
            return EligibilityDecision("rejected", "senior_without_eligible_experience")
        return EligibilityDecision("eligible", "senior_within_experience_limit", required_years)
    if MIDDLE_PATTERN.search(title):
        return EligibilityDecision("eligible", "middle_level_title", required_years)
    if MIDDLE_DESCRIPTION_PATTERN.search(description):
        return EligibilityDecision("eligible", "middle_level_description", required_years)
    if required_years is not None:
        return EligibilityDecision("eligible", "experience_within_limit", required_years)
    return EligibilityDecision("unknown", "experience_not_stated")
