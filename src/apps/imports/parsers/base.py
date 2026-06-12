class BaseParser:
    parser_type = "CAREER_SITE"
    listing_finder_class = None

    def __init__(self, source=None):
        self.source = source

    def find_listing_pages(self):
        finder_class = self.listing_finder_class or self._default_listing_finder()
        return finder_class(self.source).find()

    def extract_job(self, payload):
        if isinstance(payload, dict):
            return dict(payload)
        if isinstance(payload, str):
            return {"url": payload}
        raise TypeError("Parser payload must be a raw dict or URL string.")

    def extract_jobs(self, listing_page):
        configured_jobs = self._configured_raw_jobs()
        if configured_jobs:
            return [self.extract_job(job) for job in configured_jobs]
        return self.parse_listing_page(
            content=self.fetch_listing_page(listing_page),
            listing_page=listing_page,
        )

    def fetch_listing_page(self, listing_page):
        return ""

    def parse_listing_page(self, content, listing_page):
        return []

    def _configured_raw_jobs(self):
        config = getattr(self.source, "crawl_config", None) or {}
        raw_jobs = config.get("raw_jobs") or config.get("jobs") or []
        return raw_jobs if isinstance(raw_jobs, list) else []

    @staticmethod
    def _default_listing_finder():
        from apps.imports.services.listing_finder import ListingFinder

        return ListingFinder
