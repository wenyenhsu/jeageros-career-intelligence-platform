from .base import BaseParser


class CareerSiteParser(BaseParser):
    parser_type = "CAREER_SITE"


class GenericHTMLParser(CareerSiteParser):
    parser_type = "GENERIC_HTML"


class RSSParser(BaseParser):
    parser_type = "RSS"


class APIParser(BaseParser):
    parser_type = "API"
