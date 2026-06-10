from .job_extractor import JobExtractor
from .listing_finder import ListingFinder
from .source_detector import SourceDetector


class BaseParser:
    parser_type = SourceDetector.CAREER_SITE
    listing_finder_class = ListingFinder
    job_extractor_class = JobExtractor

    def __init__(self, source=None):
        self.source = source

    def find_listing_pages(self):
        return self.listing_finder_class(self.source).find()

    def extract_job(self, payload):
        return self.job_extractor_class().extract(payload)

    def extract_jobs(self, listing_page):
        return []


class LinkedInParser(BaseParser):
    parser_type = SourceDetector.LINKEDIN


class GreenhouseParser(BaseParser):
    parser_type = SourceDetector.GREENHOUSE


class LeverParser(BaseParser):
    parser_type = SourceDetector.LEVER


class GenericCareerSiteParser(BaseParser):
    parser_type = SourceDetector.CAREER_SITE


class ParserRegistry:
    _parsers = {
        LinkedInParser.parser_type: LinkedInParser,
        GreenhouseParser.parser_type: GreenhouseParser,
        LeverParser.parser_type: LeverParser,
        GenericCareerSiteParser.parser_type: GenericCareerSiteParser,
        SourceDetector.GENERIC_HTML: GenericCareerSiteParser,
    }

    @classmethod
    def register(cls, parser_type, parser_class):
        cls._parsers[cls._normalize_parser_type(parser_type)] = parser_class

    @classmethod
    def get_parser_class(cls, parser_type):
        return cls._parsers.get(
            cls._normalize_parser_type(parser_type),
            GenericCareerSiteParser,
        )

    @classmethod
    def get_parser(cls, parser_type, source=None):
        parser_class = cls.get_parser_class(parser_type)
        return parser_class(source=source)

    @classmethod
    def get_parser_for_source(cls, source):
        parser_type = SourceDetector.detect_parser_type(source)
        return cls.get_parser(parser_type, source=source)

    @classmethod
    def get_parser_for_url(cls, url):
        parser_type = SourceDetector.detect_parser_type(url)
        return cls.get_parser(parser_type, source=url)

    @staticmethod
    def _normalize_parser_type(parser_type):
        return (parser_type or SourceDetector.CAREER_SITE).upper()
