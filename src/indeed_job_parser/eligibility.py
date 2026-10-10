from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

ROLE_PATTERN = re.compile(
    r"(?:\bqa\b|quality assurance|data quality|software test(?:er|ing)?|test automation|automation qa|qa automation|\bsdet\b)",
    re.IGNORECASE,
)
EXCLUDED_LEVEL_PATTERN = re.compile(
    r"(?:\bjunior\b|\bjr\.?\b|trainee|intern(?:ship)?|graduate|\blead\b|team lead|principal|staff|head|manager|director|chief)",
    re.IGNORECASE,
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


def evaluate_job(row: Mapping[str, object], max_experience_years: int = 5) -> EligibilityDecision:
    title = str(row.get("title") or "").strip()
    description = str(row.get("description") or "")
    if not ROLE_PATTERN.search(title):
        return EligibilityDecision("rejected", "irrelevant_title")
    if EXCLUDED_LEVEL_PATTERN.search(title):
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
