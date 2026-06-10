from dataclasses import dataclass

from .source_detector import SourceDetector


@dataclass(frozen=True)
class ListingPage:
    url: str
    parser_type: str
    source_name: str = ""


class ListingFinder:
    def __init__(self, source=None):
        self.source = source

    def find(self):
        url = self._source_url()
        if not url:
            return []

        return [
            ListingPage(
                url=url,
                parser_type=SourceDetector.detect_parser_type(self.source or url),
                source_name=self._source_name(),
            )
        ]

    def _source_url(self):
        if self.source is None:
            return ""
        if isinstance(self.source, str):
            return self.source
        return (
            getattr(self.source, "base_url", "")
            or getattr(self.source, "url", "")
            or ""
        )

    def _source_name(self):
        if self.source is None or isinstance(self.source, str):
            return ""
        return getattr(self.source, "name", "")
