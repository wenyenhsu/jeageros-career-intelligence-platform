import html
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import BaseParser


class CareerSiteParser(BaseParser):
    parser_type = "CAREER_SITE"
    DEFAULT_TIMEOUT_SECONDS = 12
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    JSON_LD_PATTERN = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def extract_single_job(self, url):
        url = str(url or "").strip()
        if not url:
            return []
        page_html = self._fetch_url(url)
        posting = self._job_posting_from_html(page_html)
        if not posting:
            return []
        return [self._raw_job_from_job_posting(posting, url)]

    def _fetch_url(self, url):
        request = Request(str(url), headers=self.REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=self.DEFAULT_TIMEOUT_SECONDS) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError, OSError):
            return ""

    @classmethod
    def _job_posting_from_html(cls, page_html):
        for block in cls.JSON_LD_PATTERN.findall(page_html or ""):
            try:
                payload = json.loads(block)
            except json.JSONDecodeError:
                try:
                    payload = json.loads(html.unescape(block))
                except json.JSONDecodeError:
                    continue
            posting = cls._first_job_posting(payload)
            if posting:
                return posting
        return None

    @classmethod
    def _first_job_posting(cls, payload):
        if isinstance(payload, list):
            for item in payload:
                posting = cls._first_job_posting(item)
                if posting:
                    return posting
            return None
        if not isinstance(payload, dict):
            return None
        types = payload.get("@type")
        type_names = types if isinstance(types, list) else [types]
        if any(str(name or "") == "JobPosting" for name in type_names):
            return payload
        graph = payload.get("@graph")
        if isinstance(graph, list):
            return cls._first_job_posting(graph)
        return None

    @classmethod
    def _raw_job_from_job_posting(cls, posting, url):
        organization = posting.get("hiringOrganization")
        if not isinstance(organization, dict):
            organization = {}
        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            external_id = identifier.get("value") or identifier.get("name")
        else:
            external_id = identifier
        return {
            "source": "career_site",
            "source_url": posting.get("url") or url,
            "absolute_url": posting.get("url") or url,
            "external_id": str(external_id or "").strip(),
            "title": posting.get("title") or posting.get("name"),
            "company_name": organization.get("name"),
            "location": cls._location_from_job_posting(posting),
            "description": cls._decode_html(posting.get("description")),
            "date_posted": posting.get("datePosted"),
        }

    @classmethod
    def _location_from_job_posting(cls, posting):
        locations = posting.get("jobLocation")
        if isinstance(locations, dict):
            locations = [locations]
        if not isinstance(locations, list):
            return ""
        parts = []
        for location in locations:
            if not isinstance(location, dict):
                continue
            address = location.get("address")
            if not isinstance(address, dict):
                address = location
            for key in (
                "addressLocality",
                "addressRegion",
                "addressCountry",
            ):
                value = " ".join(str(address.get(key) or "").split())
                if value and value not in parts:
                    parts.append(value)
        return ", ".join(parts)

    @staticmethod
    def _decode_html(value):
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(text.split())


class GenericHTMLParser(CareerSiteParser):
    parser_type = "GENERIC_HTML"


class RSSParser(BaseParser):
    parser_type = "RSS"


class APIParser(BaseParser):
    parser_type = "API"
