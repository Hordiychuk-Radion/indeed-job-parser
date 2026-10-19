from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

Freshness = Literal["fresh", "stale", "missing", "invalid", "future"]


def _as_date(value: Any) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(str(value).strip())


def assess_freshness(
    published_at: Any,
    *,
    days_old: int,
    today: date | None = None,
) -> Freshness:
    if published_at is None or str(published_at).strip() == "":
        return "missing"
    try:
        published = _as_date(published_at)
    except (TypeError, ValueError):
        return "invalid"
    if published is None:
        return "missing"
    current = today or datetime.now(timezone.utc).date()
    if published > current:
        return "future"
    cutoff = current - timedelta(days=days_old - 1)
    return "fresh" if published >= cutoff else "stale"
