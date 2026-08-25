from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError

import pytest

from apps.imports.models import JobSource
import apps.imports.parsers.lever as lever_parser_module
from apps.imports.parsers.lever import LeverParser, LeverPayloadError
from apps.imports.services import CrawlService, JobNormalizer
from apps.jobs.models import JobPost


def _lever_job(
    posting_id,
    *,
    title="Backend Engineer",
    site="acme",
    host="jobs.lever.co",
):
    return {
        "id": posting_id,
        "text": title,
        "categories": {
            "location": "Remote - US",
            "allLocations": ["Remote - US"],
            "commitment": "Full-time",
            "team": "Engineering",
            "department": "Product & Engineering",
        },
        "country": "US",
        "descriptionPlain": "Build reliable data services.",
        "lists": [
            {
                "text": "Requirements",
                "content": "<li>Python &amp; SQL</li><li>Django</li>",
            },
            {
                "text": "What you'll do",
                "content": "<li>Own production APIs</li>",
            },
        ],
        "additionalPlain": "Equal opportunity employer.",
        "hostedUrl": f"https://{host}/{site}/{posting_id}",
        "applyUrl": f"https://{host}/{site}/{posting_id}/apply",
        "workplaceType": "remote",
        "salaryRange": {
            "currency": "USD",
            "interval": "year",
            "min": 120000,
            "max": 160000,
        },
    }


def test_lever_parser_fetches_paginated_listing_and_stops_on_short_page(monkeypatch):
    source = JobSource(
        name="Acme Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/acme",
        crawl_config={
            "max_pages": 3,
            "max_search_requests": 3,
            "lever_page_size": 2,
            "request_delay_seconds": 0,
        },
        filter_config={"target_companies": ["Acme Corp"]},
    )
    parser = LeverParser(source=source)
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        skip = int(parse_qs(urlparse(url).query)["skip"][0])
        if skip == 0:
            return [_lever_job("job-1"), _lever_job("job-2")]
        if skip == 2:
            return [_lever_job("job-3")]
        raise AssertionError(f"Unexpected pagination request: {url}")

    monkeypatch.setattr(parser, "_fetch_json", fake_fetch_json)

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(calls) == 2
    assert [parse_qs(urlparse(url).query)["skip"][0] for url in calls] == [
        "0",
        "2",
    ]
    assert all(
        url.startswith("https://api.lever.co/v0/postings/acme?") for url in calls
    )
    assert [job["external_id"] for job in jobs] == ["job-1", "job-2", "job-3"]
    assert jobs[0]["leverCompanyName"] == "Acme Corp"
    assert jobs[0]["source"] == "lever"
    assert jobs[0]["sections"]["requirements"] == "Python & SQL\nDjango"
    assert jobs[0]["sections"]["responsibilities"] == "Own production APIs"
    assert "Python & SQL" in jobs[0]["description"]
    assert jobs[0]["metadata"]["salary_range"]["min"] == 120000


@pytest.mark.parametrize(
    ("source_url", "expected_api_url", "host"),
    [
        (
            "https://jobs.lever.co/acme/abc-123",
            "https://api.lever.co/v0/postings/acme/abc-123",
            "jobs.lever.co",
        ),
        (
            "https://jobs.eu.lever.co/acme/abc-123",
            "https://api.eu.lever.co/v0/postings/acme/abc-123",
            "jobs.eu.lever.co",
        ),
        (
            "https://api.eu.lever.co/v0/postings/acme/abc-123",
            "https://api.eu.lever.co/v0/postings/acme/abc-123",
            "jobs.eu.lever.co",
        ),
    ],
)
def test_lever_parser_fetches_single_job_from_global_and_eu_urls(
    monkeypatch,
    source_url,
    expected_api_url,
    host,
):
    parser = LeverParser(source=source_url)
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        return _lever_job("abc-123", host=host)

    monkeypatch.setattr(parser, "_fetch_json", fake_fetch_json)

    jobs = parser.extract_single_job(source_url)

    assert calls == [expected_api_url]
    assert jobs[0]["source_url"] == f"https://{host}/acme/abc-123"
    assert jobs[0]["external_id"] == "abc-123"
    assert jobs[0]["leverCompanyName"] == "Acme"


def test_lever_listing_preserves_supported_api_filters(monkeypatch):
    source = JobSource(
        name="Acme Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url=("https://jobs.lever.co/acme?location=Remote&location=New%20York"),
        crawl_config={
            "lever_api_filters": {
                "commitment": ["Full-time", "Intern"],
                "unsupported": "ignored",
            }
        },
        filter_config={"target_companies": ["Acme"]},
    )
    parser = LeverParser(source=source)
    calls = []
    monkeypatch.setattr(
        parser,
        "_fetch_json",
        lambda url: calls.append(url) or [],
    )

    parser.extract_jobs(parser.find_listing_pages()[0])

    query = parse_qs(urlparse(calls[0]).query)
    assert query["location"] == ["Remote", "New York"]
    assert query["commitment"] == ["Full-time", "Intern"]
    assert "unsupported" not in query
    assert query["mode"] == ["json"]


def test_lever_parser_rejects_invalid_json(monkeypatch):
    parser = LeverParser(source="https://jobs.lever.co/acme")
    monkeypatch.setattr(parser, "_fetch_url", lambda url: "not-json")

    with pytest.raises(LeverPayloadError, match="invalid JSON"):
        parser._fetch_json("https://api.lever.co/v0/postings/acme")


@pytest.mark.django_db
def test_lever_parser_persists_rate_limit_cooldown(monkeypatch):
    source = JobSource.objects.create(
        name="Acme Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/acme",
        crawl_config={"max_pages": 1, "rate_limit_cooldown_minutes": 30},
    )
    parser = LeverParser(source=source)

    def fake_urlopen(request, timeout=None):
        raise HTTPError(request.full_url, 429, "Too Many Requests", None, None)

    monkeypatch.setattr(lever_parser_module, "urlopen", fake_urlopen)

    with pytest.raises(lever_parser_module.LeverRateLimitError, match="Lever limited"):
        parser.extract_jobs(parser.find_listing_pages()[0])

    source.refresh_from_db()
    assert source.crawl_config["rate_limit_status_code"] == 429
    assert source.crawl_config["rate_limited_until"]


def test_lever_parser_requires_tenant_slug_for_live_listing():
    parser = LeverParser(source="https://jobs.lever.co/")

    with pytest.raises(ValueError, match="site slug"):
        parser.extract_jobs(parser.find_listing_pages()[0])


def test_lever_raw_payload_normalizes_to_canonical_payload(monkeypatch):
    source = JobSource(
        name="Acme Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/acme",
        filter_config={"target_companies": ["Acme Corp"]},
    )
    parser = LeverParser(source=source)
    monkeypatch.setattr(
        parser,
        "_fetch_json",
        lambda url: [_lever_job("job-1", title="Senior Data Engineer")],
    )

    raw_job = parser.extract_jobs(parser.find_listing_pages()[0])[0]
    canonical = JobNormalizer.normalize(raw_job, source=source)

    assert canonical.source == "lever"
    assert canonical.source_url == "https://jobs.lever.co/acme/job-1"
    assert canonical.external_id == "job-1"
    assert canonical.company_name == "Acme Corp"
    assert canonical.title == "Senior Data Engineer"
    assert canonical.location == "Remote"
    assert canonical.remote_type == "Remote"
    assert canonical.job_type == "FULL_TIME"
    assert canonical.employment_type == "FULL_TIME"
    assert canonical.sections["requirements"] == "Python & SQL Django"
    assert "Own production APIs" in canonical.description
    assert canonical.metadata["lever_site"] == "acme"
    assert canonical.metadata["raw_payload"]["id"] == "job-1"


@pytest.mark.django_db
def test_lever_live_parser_runs_through_crawl_normalize_and_sync(monkeypatch):
    source = JobSource.objects.create(
        name="Acme Lever",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://jobs.lever.co/acme",
        enabled=True,
        crawl_config={
            "max_pages": 1,
            "max_search_requests": 1,
            "request_delay_seconds": 0,
        },
        filter_config={"target_companies": ["Acme Corp"]},
    )
    monkeypatch.setattr(
        LeverParser,
        "_fetch_json",
        lambda self, url: [_lever_job("job-1", title="Data Engineer")],
    )

    summary = CrawlService.crawl_all_sources([source])

    assert summary["success"] is True
    assert summary["sources_processed"] == 1
    assert summary["jobs_created"] == 1
    assert summary["sources"][0]["parser_type"] == "LEVER"
    job = JobPost.objects.select_related("company").get()
    assert job.company.name == "Acme Corp"
    assert job.title == "Data Engineer"
    assert job.description.startswith("Build reliable data services.")
    assert job.source_url == "https://jobs.lever.co/acme/job-1"
    assert job.external_id == "job-1"
    assert job.source_key == "lever:acme"
