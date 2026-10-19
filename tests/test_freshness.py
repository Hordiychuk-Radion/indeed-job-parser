from datetime import date, datetime, timezone

from indeed_job_parser.freshness import assess_freshness


def test_freshness_accepts_inclusive_cutoff_and_recent_dates():
    today = date(2026, 10, 19)

    assert assess_freshness("2026-10-06", days_old=14, today=today) == "fresh"
    assert assess_freshness(datetime(2026, 10, 19, tzinfo=timezone.utc), days_old=14, today=today) == "fresh"


def test_freshness_rejects_stale_missing_invalid_and_future_dates():
    today = date(2026, 10, 19)

    assert assess_freshness("2026-10-05", days_old=14, today=today) == "stale"
    assert assess_freshness(None, days_old=14, today=today) == "missing"
    assert assess_freshness("not-a-date", days_old=14, today=today) == "invalid"
    assert assess_freshness("2026-10-20", days_old=14, today=today) == "future"
