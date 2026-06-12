from apps.imports.parsers import (
    APIParser,
    CareerSiteParser,
    GenericCareerSiteParser,
    GenericHTMLParser,
    GreenhouseParser,
    HandshakeParser,
    LeverParser,
    LinkedInParser,
    RSSParser,
)

from .source_detector import SourceDetector


class ParserRegistry:
    _parsers = {
        SourceDetector.LINKEDIN: LinkedInParser,
        SourceDetector.HANDSHAKE: HandshakeParser,
        SourceDetector.GREENHOUSE: GreenhouseParser,
        SourceDetector.LEVER: LeverParser,
        SourceDetector.CAREER_SITE: GenericCareerSiteParser,
        SourceDetector.RSS: RSSParser,
        SourceDetector.API: APIParser,
        SourceDetector.GENERIC_HTML: GenericHTMLParser,
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
