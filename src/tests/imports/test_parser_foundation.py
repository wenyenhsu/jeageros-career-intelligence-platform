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
    source = JobSource(name="Lever", resource=JobSource.ResourceChoices.LEVER)

    assert SourceDetector.detect_parser_type(source) == SourceDetector.LEVER


def test_source_detector_preserves_explicit_resource_for_unknown_source_url():
    source = JobSource(
        name="Custom Lever Feed",
        resource=JobSource.ResourceChoices.LEVER,
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
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=python&location=Remote&start=0": _linkedin_search_html(),
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


def test_linkedin_parser_does_not_apply_filter_keywords_to_search_url(monkeypatch):
    source = JobSource(
        name="LinkedIn Location Only",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?location=United+States",
        crawl_config={"max_pages": 1},
        filter_config={
            "include_keywords": ["backend", "python", "django"],
            "target_companies": ["OpenAI"],
        },
    )
    parser = LinkedInParser(source=source)
    monkeypatch.setattr(
        linkedin_parser_module,
        "urlopen",
        _fake_linkedin_urlopen(
            {
                "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?location=United+States&start=0": _linkedin_search_html(),
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
    assert jobs[0]["companyName"] == "OpenAI"


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


def _linkedin_search_html():
    return """
    <div class="base-search-card" data-entity-urn="urn:li:jobPosting:5555555555">
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/5555555555/?refId=abc">View job</a>
      <h3 class="base-search-card__title">Backend Engineer</h3>
      <h4 class="base-search-card__subtitle"><a>OpenAI</a></h4>
      <span class="job-search-card__location">Remote</span>
      <time datetime="2026-06-11"></time>
    </div>
    """


def _linkedin_detail_html(job_id, title, company, location, employment_type):
    return f"""
    <html>
      <body>
        <h1 class="top-card-layout__title">{title}</h1>
        <a class="topcard__org-name-link">{company}</a>
        <span class="topcard__flavor--bullet">{location}</span>
        <time datetime="2026-06-10"></time>
        <div class="show-more-less-html__markup">
          <p>Build reliable Django services.</p>
        </div>
        <li class="description__job-criteria-item">
          <h3 class="description__job-criteria-subheader">Employment type</h3>
          <span class="description__job-criteria-text">{employment_type}</span>
        </li>
        <a href="https://www.linkedin.com/jobs/view/{job_id}/">Canonical</a>
      </body>
    </html>
    """
