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
