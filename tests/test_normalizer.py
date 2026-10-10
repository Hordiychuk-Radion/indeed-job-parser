from indeed_job_parser.normalizer import canonicalize_url, normalize_record


def test_canonical_indeed_url_keeps_job_identity_and_drops_tracking():
    url = "https://cz.indeed.com/viewjob?jk=abc123&utm_source=x&from=serp"
    assert canonicalize_url(url) == "https://cz.indeed.com/viewjob?jk=abc123"


def test_normalize_record_builds_stable_contract():
    raw = {
        "id": "abc123",
        "site": "indeed",
        "title": " QA Engineer ",
        "company": " Example s.r.o. ",
        "location": "Prague",
        "job_url": "https://cz.indeed.com/viewjob?jk=abc123&utm_source=x",
        "description": None,
        "date_posted": "2026-09-30",
        "min_amount": 60000,
        "max_amount": 80000,
        "currency": "CZK",
        "interval": "monthly",
        "is_remote": False,
        "job_type": "fulltime",
    }
    job = normalize_record(raw, query="QA Engineer", country="CZ")
    assert job.title == "QA Engineer"
    assert job.company == "Example s.r.o."
    assert job.description == ""
    assert job.canonical_url.endswith("?jk=abc123")
    assert job.dedupe_key
    assert job.salary_min == 60000
    assert job.salary_period == "monthly"
