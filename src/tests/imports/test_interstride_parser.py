from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from django.test import override_settings

import apps.imports.parsers.interstride as interstride_parser_module
from apps.imports.models import JobSource
from apps.imports.parsers import InterstrideAuthError, InterstrideParser
from apps.imports.services import JobNormalizer, SourceDetector


def _source(**overrides):
    values = {
        "name": "Interstride",
        "resource": JobSource.ResourceChoices.INTERSTRIDE,
        "base_url": "https://student.interstride.com/",
        "crawl_config": {
            "max_pages": 2,
            "max_search_requests": 2,
            "max_detail_requests": 2,
            "fetch_details": "false",
            "request_delay_seconds": 0,
        },
        "filter_config": {
            "location": ["United States"],
            "search_keywords": ["data engineer"],
            "job_types": ["Full-time"],
            "remote_only": True,
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _FakeHeaders:
    @staticmethod
    def get_content_charset():
        return "utf-8"


class _FakeResponse:
    headers = _FakeHeaders()

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


@override_settings(
    INTERSTRIDE_AUTH_TOKEN="test-token",
    INTERSTRIDE_API_BASE_URL="https://web.production.interstride.com/api/v1/",
)
def test_interstride_parser_sends_authorization_header_and_json(monkeypatch):
    parser = InterstrideParser(source=_source())
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "authorization": request.get_header("Authorization"),
                "payload": request.data,
                "timeout": timeout,
            }
        )
        return _FakeResponse(b'{"success": true, "data": {"jobs": []}}')

    monkeypatch.setattr(interstride_parser_module, "urlopen", fake_urlopen)

    response = parser._request_json(
        "jobs/search",
        method="POST",
        payload={"page": 1},
    )

    assert response["success"] is True
    assert captured == {
        "url": "https://web.production.interstride.com/api/v1/jobs/search",
        "method": "POST",
        "authorization": "test-token",
        "payload": b'{"page": 1}',
        "timeout": 12,
    }


@override_settings(INTERSTRIDE_AUTH_TOKEN="test-token")
def test_interstride_parser_fetches_pages_and_returns_raw_jobs(monkeypatch):
    parser = InterstrideParser(source=_source())
    calls = []

    def fake_request_json(path, method="GET", payload=None):
        calls.append((path, method, payload))
        page = payload["page"]
        return {
            "success": True,
            "data": {
                "jobs": [
                    {
                        "job_key": f"interstride-{page}",
                        "job_title": f"Data Engineer {page}",
                        "company_name": "Acme",
                        "city": "Los Angeles",
                        "state": "CA",
                        "country": "US",
                        "employment_type": "Full-time",
                        "work_type": "Remote",
                        "publish_date": "2026-08-24",
                        "api_response": {
                            "job_description": "<p>Build Python pipelines.</p>",
                            "job_application_url": "https://acme.example/apply",
                        },
                    }
                ],
                "total_pages": 2,
            },
        }

    monkeypatch.setattr(parser, "_request_json", fake_request_json)

    jobs = parser.extract_jobs(SimpleNamespace(url=parser.source.base_url))

    assert [job["external_id"] for job in jobs] == [
        "interstride-1",
        "interstride-2",
    ]
    assert jobs[0]["source"] == "interstride"
    assert jobs[0]["title"] == "Data Engineer 1"
    assert jobs[0]["company_name"] == "Acme"
    assert jobs[0]["location"] == "Los Angeles, CA, US"
    assert jobs[0]["description"] == "Build Python pipelines."
    assert jobs[0]["source_url"].endswith("/jobs/job-details/interstride-1")
    assert jobs[0]["metadata"]["application_url"] == ("https://acme.example/apply")
    assert [call[2]["page"] for call in calls] == [1, 2]
    assert calls[0][2]["search"] == "data engineer"
    assert calls[0][2]["country"] == "us"
    assert calls[0][2]["visa"] == "all_sponsored_companies"
    assert calls[0][2]["work_type"] == "remote"


@override_settings(INTERSTRIDE_AUTH_TOKEN="test-token")
def test_interstride_parser_fetches_missing_job_description(monkeypatch):
    source = _source(
        crawl_config={
            "max_pages": 1,
            "max_search_requests": 1,
            "max_detail_requests": 1,
            "fetch_details": "new_or_missing",
            "request_delay_seconds": 0,
        }
    )
    parser = InterstrideParser(source=source)
    paths = []

    def fake_request_json(path, method="GET", payload=None):
        paths.append(path)
        if path == "jobs/search":
            return {
                "success": True,
                "data": {
                    "jobs": [
                        {
                            "job_key": "job-42",
                            "job_title": "Backend Engineer",
                            "company": "Example Co",
                        }
                    ],
                    "total_pages": 1,
                },
            }
        assert path == "jobs/job-42"
        return {
            "success": True,
            "data": {
                "job": {
                    "job_key": "job-42",
                    "job_title": "Backend Engineer",
                    "company": "Example Co",
                    "job_description": "Django and PostgreSQL",
                }
            },
        }

    monkeypatch.setattr(parser, "_request_json", fake_request_json)

    jobs = parser.extract_jobs(SimpleNamespace(url=source.base_url))

    assert paths == ["jobs/search", "jobs/job-42"]
    assert jobs[0]["description"] == "Django and PostgreSQL"


@override_settings(INTERSTRIDE_AUTH_TOKEN="test-token")
def test_interstride_raw_job_normalizes_to_canonical_payload():
    parser = InterstrideParser(source=_source())
    raw = parser.extract_job(
        {
            "job_key": "job-99",
            "job_title": "Software Engineer Intern",
            "company_name": "Example Co",
            "city": "Remote",
            "employment_type": "Internship",
            "job_description": "Build Django applications.",
        }
    )

    canonical = JobNormalizer.normalize(raw, source=SourceDetector.INTERSTRIDE)

    assert canonical.source == "interstride"
    assert canonical.external_id == "job-99"
    assert canonical.company_name == "Example Co"
    assert canonical.title == "Software Engineer Intern"
    assert canonical.job_type == "INTERNSHIP"
    assert canonical.location == "Remote"


@override_settings(INTERSTRIDE_AUTH_TOKEN="")
def test_interstride_parser_requires_environment_token():
    parser = InterstrideParser(source=_source())

    with pytest.raises(InterstrideAuthError, match="INTERSTRIDE_AUTH_TOKEN"):
        parser.extract_jobs(SimpleNamespace(url=parser.source.base_url))


@override_settings(
    INTERSTRIDE_AUTH_TOKEN="expired-token",
    INTERSTRIDE_API_BASE_URL="https://web.production.interstride.com/api/v1/",
)
def test_interstride_parser_reports_expired_token_without_exposing_it(monkeypatch):
    parser = InterstrideParser(source=_source())

    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr(interstride_parser_module, "urlopen", fake_urlopen)

    with pytest.raises(InterstrideAuthError) as exc_info:
        parser._request_json("jobs/search", method="POST", payload={"page": 1})

    assert "expired-token" not in str(exc_info.value)
