import pytest
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

from apps.companies.models import Company
import apps.imports.parsers.linkedin as linkedin_parser_module
from apps.imports.models import JobSource
from apps.imports.services import (
    CareerSiteParser,
    GenericHTMLParser,
    GreenhouseParser,
    HandshakeParser,
    LeverParser,
    LinkedInParser,
    ParserRegistry,
    SourceDetector,
)
from apps.jobs.models import JobPost


def test_source_detector_detects_supported_job_boards():
    assert (
        SourceDetector.detect_parser_type("https://www.linkedin.com/jobs/")
        == SourceDetector.LINKEDIN
    )
    assert (
        SourceDetector.detect_parser_type("https://boards.greenhouse.io/openai")
        == SourceDetector.GREENHOUSE
    )
    assert (
        SourceDetector.detect_parser_type("https://jobs.lever.co/openai")
        == SourceDetector.LEVER
    )
    assert (
        SourceDetector.detect_parser_type("https://app.joinhandshake.com/stu/jobs")
        == SourceDetector.HANDSHAKE
    )


def test_source_detector_uses_generic_career_site_for_unknown_urls():
    assert (
        SourceDetector.detect_parser_type("https://careers.example.com/jobs")
        == SourceDetector.CAREER_SITE
    )


def test_source_detector_falls_back_to_job_source_resource_without_url():
    source = SimpleNamespace(resource=SourceDetector.LEVER, base_url="")

    assert SourceDetector.detect_parser_type(source) == SourceDetector.LEVER


def test_source_detector_preserves_explicit_resource_for_unknown_source_url():
    source = SimpleNamespace(
        resource=SourceDetector.LEVER,
        base_url="https://careers.example.com/jobs",
    )

    assert SourceDetector.detect_parser_type(source) == SourceDetector.LEVER


def test_parser_registry_returns_specific_and_generic_parsers():
    assert ParserRegistry.get_parser_class(SourceDetector.LINKEDIN) is LinkedInParser
    assert ParserRegistry.get_parser_class(SourceDetector.HANDSHAKE) is HandshakeParser
    assert (
        ParserRegistry.get_parser_class(SourceDetector.GREENHOUSE) is GreenhouseParser
    )
    assert ParserRegistry.get_parser_class(SourceDetector.LEVER) is LeverParser
    assert (
        ParserRegistry.get_parser_class(SourceDetector.CAREER_SITE) is CareerSiteParser
    )
    assert (
        ParserRegistry.get_parser_class(SourceDetector.GENERIC_HTML)
        is GenericHTMLParser
    )
    assert ParserRegistry.get_parser_class("UNKNOWN") is CareerSiteParser


def test_parser_registry_selects_parser_from_url():
    parser = ParserRegistry.get_parser_for_url("https://boards.greenhouse.io/openai")

    assert isinstance(parser, GreenhouseParser)
    assert parser.source == "https://boards.greenhouse.io/openai"


def test_parser_finds_listing_page_from_source():
    source = JobSource(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/",
    )

    pages = ParserRegistry.get_parser_for_source(source).find_listing_pages()

    assert len(pages) == 1
    assert pages[0].url == "https://www.linkedin.com/jobs/"
    assert pages[0].parser_type == SourceDetector.LINKEDIN
    assert pages[0].source_name == "LinkedIn"


def test_parser_extracts_raw_job_payload_without_normalizing():
    parser = ParserRegistry.get_parser(SourceDetector.LEVER)

    extracted = parser.extract_job(
        {
            "jobTitle": "Backend Engineer",
            "company": "OpenAI",
            "url": "https://jobs.lever.co/openai/backend-engineer",
            "external_id": "backend-engineer",
            "location": "Remote",
            "remote_type": "Remote",
            "description": "Build Django services.",
        }
    )

    assert isinstance(extracted, dict)
    assert extracted["jobTitle"] == "Backend Engineer"
    assert extracted["company"] == "OpenAI"
    assert extracted["url"] == "https://jobs.lever.co/openai/backend-engineer"
    assert extracted["external_id"] == "backend-engineer"
    assert "company_name" not in extracted


def test_linkedin_parser_extracts_direct_public_job_url(monkeypatch):
    source = JobSource(
        name="LinkedIn SWE Intern",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/view/9876543210/",
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/9876543210": _linkedin_detail_html(
                    job_id="9876543210",
                    title="Software Engineer Intern",
                    company="OpenAI",
                    location="San Francisco, CA",
                    employment_type="Internship",
                )
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert jobs == [
        {
            "jobTitle": "Software Engineer Intern",
            "companyName": "OpenAI",
            "formattedLocation": "San Francisco, CA",
            "employmentType": "Internship",
            "description": "Build reliable Django services.",
            "postedAt": "2026-06-10",
            "metadata": {
                "linkedin_criteria": {"employment type": "Internship"},
                "source_parser": "LINKEDIN",
            },
            "jobPostingId": "9876543210",
            "jobUrl": "https://www.linkedin.com/jobs/view/9876543210/",
        }
    ]


def test_linkedin_parser_extracts_search_results_through_guest_endpoint(monkeypatch):
    source = JobSource(
        name="LinkedIn Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&f_TPR=r604800&sortBy=DD&start=0": _linkedin_search_html(),
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/5555555555": _linkedin_detail_html(
                    job_id="5555555555",
                    title="Backend Engineer",
                    company="OpenAI",
                    location="Remote",
                    employment_type="Full-time",
                ),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["jobPostingId"] == "5555555555"
    assert jobs[0]["jobUrl"] == "https://www.linkedin.com/jobs/view/5555555555/"
    assert jobs[0]["jobTitle"] == "Backend Engineer"
    assert jobs[0]["companyName"] == "OpenAI"
    assert jobs[0]["formattedLocation"] == "Remote"
    assert jobs[0]["employmentType"] == "Full-time"


def test_linkedin_parser_extracts_job_type_from_search_card_without_detail(monkeypatch):
    source = JobSource(
        name="LinkedIn Search Card Type",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=data&location=CA",
        crawl_config={"max_pages": 1, "fetch_details": False},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=data&location=CA&f_TPR=r604800&sortBy=DD&start=0": _linkedin_search_html(
                    job_id="7777777777",
                    title="Data Scientist, Product Analytics",
                    company="Meta",
                    location="Burlingame, CA",
                    employment_type="Full-time",
                ),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["jobTitle"] == "Data Scientist, Product Analytics"
    assert jobs[0]["employmentType"] == "Full-time"


def test_linkedin_parser_extracts_job_type_from_detail_top_card_without_criteria(
    monkeypatch,
):
    source = JobSource(
        name="LinkedIn Detail Type",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/view/7777777777/",
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/7777777777": _linkedin_detail_html(
                    job_id="7777777777",
                    title="Data Scientist, Product Analytics",
                    company="Meta",
                    location="Burlingame, CA",
                    employment_type="Full-time",
                    include_criteria=False,
                )
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["employmentType"] == "Full-time"


@pytest.mark.django_db
def test_linkedin_parser_skips_detail_fetch_for_existing_described_job(monkeypatch):
    company = Company.objects.create(name="OpenAI")
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/5555555555/",
        external_id="5555555555",
        employment_type="Full-time",
        description="Already fetched from LinkedIn.",
    )
    source = JobSource(
        name="LinkedIn Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1, "fetch_details": "new_or_missing"},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&f_TPR=r604800&sortBy=DD&start=0": _linkedin_search_html(),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["jobPostingId"] == "5555555555"
    assert jobs[0]["jobUrl"] == "https://www.linkedin.com/jobs/view/5555555555/"
    assert "description" not in jobs[0]
    assert "employmentType" not in jobs[0]


@pytest.mark.django_db
def test_linkedin_parser_fetches_detail_for_existing_job_missing_description(
    monkeypatch,
):
    company = Company.objects.create(name="OpenAI")
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/5555555555/",
        external_id="5555555555",
        description="",
    )
    source = JobSource(
        name="LinkedIn Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1, "fetch_details_for": "new_or_missing"},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&f_TPR=r604800&sortBy=DD&start=0": _linkedin_search_html(),
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/5555555555": _linkedin_detail_html(
                    job_id="5555555555",
                    title="Backend Engineer",
                    company="OpenAI",
                    location="Remote",
                    employment_type="Full-time",
                ),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["description"] == "Build reliable Django services."
    assert jobs[0]["employmentType"] == "Full-time"


@pytest.mark.django_db
def test_linkedin_parser_fetches_detail_for_new_job_when_new_or_missing(monkeypatch):
    source = JobSource(
        name="LinkedIn Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1, "fetch_details": "new_or_missing"},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&f_TPR=r604800&sortBy=DD&start=0": _linkedin_search_html(),
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/5555555555": _linkedin_detail_html(
                    job_id="5555555555",
                    title="Backend Engineer",
                    company="OpenAI",
                    location="Remote",
                    employment_type="Full-time",
                ),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 1
    assert jobs[0]["description"] == "Build reliable Django services."
    assert jobs[0]["employmentType"] == "Full-time"


def test_linkedin_parser_expands_filter_config_into_search_urls():
    source = JobSource(
        name="LinkedIn Location Only",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={"max_pages": 1},
        filter_config={
            "include_keywords": ["data engineer", "backend"],
            "location": ["CA", "TX"],
            "workplace_types": ["Remote", "Hybrid", "On-site"],
        },
    )
    parser = LinkedInParser(source=source)

    urls = parser._search_urls(source.base_url)

    assert urls == [
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=data+engineer&location=CA&start=0",
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=data+engineer&location=TX&start=0",
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=backend&location=CA&start=0",
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=backend&location=TX&start=0",
    ]


def test_linkedin_parser_limits_expanded_search_combinations():
    source = JobSource(
        name="LinkedIn Limited Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={"max_pages": 1, "max_search_combinations": 2},
        filter_config={
            "include_keywords": ["data engineer", "backend"],
            "location": ["CA", "TX"],
        },
    )
    parser = LinkedInParser(source=source)

    urls = parser._search_urls(source.base_url)

    assert len(urls) == 2
    assert "keywords=data+engineer&location=CA" in urls[0]
    assert "keywords=data+engineer&location=TX" in urls[1]


def test_linkedin_parser_maps_job_type_config_to_linkedin_filter():
    source = JobSource(
        name="LinkedIn Full-time Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={"max_pages": 1},
        filter_config={
            "search_keywords": ["data engineer"],
            "location": ["CA"],
            "job_types": ["Full-time", "Internship"],
        },
    )
    parser = LinkedInParser(source=source)

    urls = parser._search_urls(source.base_url)

    assert urls == [
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=data+engineer&location=CA&f_JT=F&start=0",
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r604800&sortBy=DD&keywords=data+engineer&location=CA&f_JT=I&start=0",
    ]


def test_linkedin_parser_applies_newest_sort_and_date_window():
    source = JobSource(
        name="LinkedIn Latest Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={
            "max_pages": 1,
            "sort_by": "newest first",
            "date_posted": "past 24 hours",
        },
        filter_config={
            "search_keywords": ["data engineer"],
            "location": ["CA"],
        },
    )
    parser = LinkedInParser(source=source)

    urls = parser._search_urls(source.base_url)

    assert urls == [
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?f_TPR=r86400&sortBy=DD&keywords=data+engineer&location=CA&start=0",
    ]


def test_linkedin_parser_limits_total_search_requests_across_pages():
    source = JobSource(
        name="LinkedIn Request Limited Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={"max_pages": 2, "max_search_requests": 3},
        filter_config={
            "include_keywords": ["data engineer", "backend", "python"],
            "location": ["CA", "TX"],
        },
    )
    parser = LinkedInParser(source=source)

    urls = parser._search_urls(source.base_url)

    assert len(urls) == 3
    assert all("start=0" in url for url in urls)
    assert "keywords=data+engineer&location=CA" in urls[0]
    assert "keywords=data+engineer&location=TX" in urls[1]
    assert "keywords=backend&location=CA" in urls[2]


@pytest.mark.django_db
def test_linkedin_parser_rolls_limited_search_requests_between_runs():
    source = JobSource.objects.create(
        name="LinkedIn Rolling Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        crawl_config={"max_pages": 1, "max_search_requests": 2},
        filter_config={
            "include_keywords": ["data engineer", "backend"],
            "location": ["CA", "TX"],
        },
    )
    parser = LinkedInParser(source=source)

    first_urls = parser._search_urls(source.base_url)
    second_urls = parser._search_urls(source.base_url)

    source.refresh_from_db()
    assert len(first_urls) == 2
    assert len(second_urls) == 2
    assert first_urls != second_urls
    assert "keywords=data+engineer&location=CA" in first_urls[0]
    assert "keywords=backend&location=CA" in second_urls[0]
    assert source.crawl_config["rolling_state"]["linkedin_search_offset"] == 0


def test_linkedin_parser_limits_detail_requests(monkeypatch):
    source = JobSource(
        name="LinkedIn Detail Limited Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1, "max_detail_requests": 1},
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&f_TPR=r604800&sortBy=DD&start=0": (
                    _linkedin_search_html(job_id="5555555555")
                    + _linkedin_search_html(
                        job_id="6666666666",
                        title="Data Engineer",
                    )
                ),
                "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/5555555555": _linkedin_detail_html(
                    job_id="5555555555",
                    title="Backend Engineer",
                    company="OpenAI",
                    location="Remote",
                    employment_type="Full-time",
                ),
            }
        ),
    )

    jobs = parser.extract_jobs(parser.find_listing_pages()[0])

    assert len(jobs) == 2
    assert jobs[0]["description"] == "Build reliable Django services."
    assert "description" not in jobs[1]


@pytest.mark.django_db
def test_linkedin_parser_raises_helpful_rate_limit_error(monkeypatch):
    source = JobSource.objects.create(
        name="LinkedIn Rate Limited Search",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1},
    )
    parser = LinkedInParser(source=source)

    def fake_urlopen(request, timeout=None):
        raise HTTPError(request.full_url, 429, "Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr(linkedin_parser_module, "urlopen", fake_urlopen)

    with pytest.raises(
        linkedin_parser_module.LinkedInRateLimitError,
        match="max_search_requests/max_detail_requests",
    ):
        parser.extract_jobs(parser.find_listing_pages()[0])

    source.refresh_from_db()
    assert source.crawl_config["rate_limit_status_code"] == 429
    assert source.crawl_config["rate_limited_until"]


def test_linkedin_parser_raises_helpful_network_error(monkeypatch):
    source = JobSource(
        name="LinkedIn Network Failure",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=python&location=Remote",
        crawl_config={"max_pages": 1},
    )
    parser = LinkedInParser(source=source)

    def fake_urlopen(request, timeout=None):
        raise URLError("[Errno -2] Name or service not known")

    monkeypatch.setattr(linkedin_parser_module, "urlopen", fake_urlopen)

    with pytest.raises(
        linkedin_parser_module.LinkedInNetworkError,
        match="Docker/celery outbound network",
    ):
        parser.extract_jobs(parser.find_listing_pages()[0])


def test_linkedin_parser_rejects_placeholder_job_ids():
    parser = LinkedInParser(
        source=JobSource(
            name="LinkedIn Placeholder",
            resource=JobSource.ResourceChoices.LINKEDIN,
            base_url="https://www.linkedin.com/jobs/",
            crawl_config={
                "jobs": [
                    {
                        "jobTitle": "Backend Engineer",
                        "companyName": "OpenAI",
                        "jobUrl": "https://www.linkedin.com/jobs/view/1234567890/",
                    }
                ]
            },
        )
    )

    try:
        parser.extract_jobs(parser.find_listing_pages()[0])
    except ValueError as exc:
        assert "placeholder job id" in str(exc)
    else:
        raise AssertionError("Expected placeholder LinkedIn job ids to be rejected.")


class _FakeLinkedInHeaders:
    def get_content_charset(self):
        return "utf-8"


class _FakeLinkedInResponse:
    headers = _FakeLinkedInHeaders()

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body.encode()


def _fake_linkedin_urlopen(responses):
    def fake_urlopen(request, timeout=None):
        url = request.full_url
        assert timeout
        if url not in responses:
            raise AssertionError(f"Unexpected LinkedIn URL requested: {url}")
        return _FakeLinkedInResponse(responses[url])

    return fake_urlopen


def _linkedin_search_html(
    job_id="5555555555",
    title="Backend Engineer",
    company="OpenAI",
    location="Remote",
    employment_type=None,
):
    employment_type_html = (
        f'<span class="job-search-card__job-type">{employment_type}</span>'
        if employment_type
        else ""
    )
    return f"""
    <div class="base-search-card" data-entity-urn="urn:li:jobPosting:{job_id}">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{job_id}/?refId=abc">View job</a>
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle"><a>{company}</a></h4>
      <span class="job-search-card__location">{location}</span>
      {employment_type_html}
      <time datetime="2026-06-11"></time>
    </div>
    """


def _linkedin_detail_html(
    job_id,
    title,
    company,
    location,
    employment_type,
    include_criteria=True,
):
    criteria_html = (
        f"""
        <li class="description__job-criteria-item">
          <h3 class="description__job-criteria-subheader">Employment type</h3>
          <span class="description__job-criteria-text">{employment_type}</span>
        </li>
        """
        if include_criteria
        else ""
    )
    return f"""
    <html>
      <body>
        <h1 class="top-card-layout__title">{title}</h1>
        <a class="topcard__org-name-link">{company}</a>
        <span class="topcard__flavor--bullet">{location}</span>
        <span class="top-card-layout__job-type">{employment_type}</span>
        <time datetime="2026-06-10"></time>
        <div class="show-more-less-html__markup">
          <p>Build reliable Django services.</p>
        </div>
        {criteria_html}
        <a href="https://www.linkedin.com/jobs/view/{job_id}/">Canonical</a>
      </body>
    </html>
    """
