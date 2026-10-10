from __future__ import annotations

import hashlib
import math
from datetime import date, datetime
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import JobRecord


def _clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _optional_float(value: Any) -> float | None:
    if value is None or _clean(value) == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = parse_qsl(parts.query, keep_blank_values=False)
    if "indeed." in parts.netloc.casefold():
        query = [(key, value) for key, value in query if key.casefold() in {"jk", "vjk"}]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def normalize_record(raw: Mapping[str, Any], query: str, country: str) -> JobRecord:
    canonical_url = canonicalize_url(_clean(raw.get("job_url") or raw.get("job_url_direct")))
    source_job_id = _clean(raw.get("id"))
    identity = source_job_id or canonical_url or "|".join(
        (_clean(raw.get("title")), _clean(raw.get("company")), _clean(raw.get("location")))
    )
    dedupe_key = hashlib.sha256(f"indeed|{identity}".encode("utf-8")).hexdigest()
    published = raw.get("date_posted")
    if isinstance(published, (date, datetime)):
        published_at = published.isoformat()
    else:
        published_at = _clean(published) or None
    remote = raw.get("is_remote")
    is_remote = remote if isinstance(remote, bool) else None
    job_type = raw.get("job_type")
    if isinstance(job_type, (list, tuple, set)):
        employment_type = ",".join(_clean(item) for item in job_type if _clean(item)) or None
    else:
        employment_type = _clean(job_type) or None
    return JobRecord(
        dedupe_key=dedupe_key,
        source=_clean(raw.get("site")) or "indeed",
        source_job_id=source_job_id,
        query=query,
        title=_clean(raw.get("title")),
        company=_clean(raw.get("company") or raw.get("company_name")),
        location=_clean(raw.get("location")),
        country_code=country,
        description=_clean(raw.get("description")),
        canonical_url=canonical_url,
        published_at=published_at,
        employment_type=employment_type,
        is_remote=is_remote,
        salary_min=_optional_float(raw.get("min_amount")),
        salary_max=_optional_float(raw.get("max_amount")),
        salary_currency=_clean(raw.get("currency")) or None,
        salary_period=_clean(raw.get("interval")) or None,
    )
