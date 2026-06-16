import html
import re
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .base import BaseParser


class LinkedInParser(BaseParser):
    parser_type = "LINKEDIN"
    GUEST_SEARCH_URL = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    )
    GUEST_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    DEFAULT_PAGE_SIZE = 25
    DEFAULT_TIMEOUT_SECONDS = 12
    PLACEHOLDER_JOB_IDS = {"1234567890", "0000000000", "1111111111"}
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def extract_job(self, payload):
        raw = super().extract_job(payload)
        self._reject_placeholder_job(raw)
        return raw

    def extract_jobs(self, listing_page):
        configured_jobs = self._configured_raw_jobs()
        if configured_jobs:
            return [self.extract_job(job) for job in configured_jobs]

        listing_url = getattr(listing_page, "url", "") or str(listing_page)
        direct_job_id = self._job_id_from_url(listing_url)
        if direct_job_id:
            raw_job = self._fetch_job_detail(direct_job_id)
            if not self._has_required_raw_fields(raw_job):
                raise ValueError(
                    f"LinkedIn job {direct_job_id} did not return usable job data."
                )
            return [raw_job]

        raw_jobs = []
        for search_url in self._search_urls(listing_url):
            search_html = self.fetch_listing_page(search_url)
            page_jobs = self.parse_listing_page(search_html, search_url)
            raw_jobs.extend(page_jobs)
        return self._dedupe_jobs(raw_jobs)

    def fetch_listing_page(self, listing_page):
        return self._fetch_url(getattr(listing_page, "url", listing_page))

    def parse_listing_page(self, content, listing_page):
        cards = self._parse_search_cards(content)
        if not self._fetch_details_enabled():
            return cards

        jobs = []
        for card in cards:
            job_id = card.get("jobPostingId") or self._job_id_from_url(
                card.get("jobUrl")
            )
            if not job_id:
                jobs.append(card)
                continue
            try:
                detail = self._fetch_job_detail(job_id)
            except Exception:
                jobs.append(card)
                continue
            jobs.append(self._merge_raw_job(card, detail))
        return jobs

    def _search_urls(self, listing_url):
        base_url = (listing_url or "").strip()
        if "jobs-guest/jobs/api/seeMoreJobPostings/search" in base_url:
            return [base_url]

        query = self._search_query_params(base_url)
        max_pages = self._positive_int_config("max_pages", default=1)
        urls = []
        for page in range(max_pages):
            page_query = dict(query)
            page_query["start"] = str(page * self.DEFAULT_PAGE_SIZE)
            urls.append(f"{self.GUEST_SEARCH_URL}?{urlencode(page_query, doseq=True)}")
        return urls

    def _search_query_params(self, base_url):
        parsed = urlparse(base_url or "")
        query = {
            key: value[-1]
            for key, value in parse_qs(parsed.query, keep_blank_values=False).items()
            if value
        }
        config = self._merged_config()

        keywords = self._first_config_value(
            config,
            "keywords",
            "keyword",
            "query",
            "include_keywords",
            "search",
        )
        location = self._first_config_value(config, "location", "locations")

        if keywords and "keywords" not in query:
            query["keywords"] = self._coerce_query_value(keywords)
        if location and "location" not in query:
            query["location"] = self._coerce_query_value(location)

        if config.get("remote_only") and "f_WT" not in query:
            query["f_WT"] = "2"

        for key in ("geoId", "f_TPR", "f_WT", "f_E", "f_JT"):
            if key in config and key not in query:
                query[key] = self._coerce_query_value(config[key])

        query.pop("currentJobId", None)
        return query

    def _fetch_job_detail(self, job_id):
        self._reject_placeholder_job({"jobPostingId": job_id})
        detail_html = self._fetch_url(self.GUEST_JOB_URL.format(job_id=job_id))
        raw_job = self._parse_job_detail(detail_html)
        raw_job.setdefault("jobPostingId", job_id)
        raw_job.setdefault("jobUrl", self._canonical_job_url(job_id))
        self._reject_placeholder_job(raw_job)
        return raw_job

    def _fetch_url(self, url):
        if not url:
            return ""
        request = Request(str(url), headers=self.REQUEST_HEADERS)
        timeout = self._positive_int_config(
            "timeout_seconds", default=self.DEFAULT_TIMEOUT_SECONDS
        )
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")

    def _parse_search_cards(self, content):
        if not content:
            return []

        jobs = []
        blocks = re.split(
            r'(?=<[^>]+data-entity-urn=["\']urn:li:jobPosting:\d+["\'])',
            content,
            flags=re.IGNORECASE,
        )
        for block in blocks:
            job_id = self._first_match(
                block, r'data-entity-urn=["\']urn:li:jobPosting:(\d+)["\']'
            )
            if not job_id:
                continue

            raw_job = {
                "jobPostingId": job_id,
                "jobUrl": self._extract_job_url(block, job_id),
                "jobTitle": self._extract_class_text(
                    block, "base-search-card__title"
                ),
                "companyName": self._extract_class_text(
                    block, "base-search-card__subtitle"
                ),
                "formattedLocation": self._extract_class_text(
                    block, "job-search-card__location"
                ),
                "postedAt": self._extract_time_value(block),
            }
            jobs.append({key: value for key, value in raw_job.items() if value})
        return self._dedupe_jobs(jobs)

    def _parse_job_detail(self, content):
        if not content:
            return {}

        criteria = self._extract_criteria(content)
        description = self._extract_class_text(
            content,
            "show-more-less-html__markup",
            preserve_breaks=True,
        )
        raw_job = {
            "jobTitle": self._extract_class_text(content, "top-card-layout__title")
            or self._extract_tag_text(content, "h1"),
            "companyName": self._extract_class_text(content, "topcard__org-name-link")
            or self._extract_class_text(content, "topcard__flavor--black-link"),
            "formattedLocation": self._extract_class_text(
                content,
                "topcard__flavor--bullet",
            ),
            "employmentType": criteria.get("employment type"),
            "description": description,
            "postedAt": self._extract_time_value(content),
            "metadata": {
                "linkedin_criteria": criteria,
                "source_parser": self.parser_type,
            },
        }
        return {key: value for key, value in raw_job.items() if value}

    def _extract_criteria(self, content):
        criteria = {}
        pattern = re.compile(
            r'<li[^>]*class=["\'][^"\']*description__job-criteria-item[^"\']*["\'][^>]*>(.*?)</li>',
            re.IGNORECASE | re.DOTALL,
        )
        for item in pattern.findall(content):
            label = self._extract_class_text(item, "description__job-criteria-subheader")
            value = self._extract_class_text(item, "description__job-criteria-text")
            if label and value:
                criteria[label.casefold()] = value
        return criteria

    def _extract_job_url(self, block, job_id):
        url = self._first_match(
            block,
            rf'href=["\']([^"\']*/jobs/view/{re.escape(str(job_id))}[^"\']*)["\']',
        )
        return self._canonical_job_url(job_id, url=url)

    @classmethod
    def _canonical_job_url(cls, job_id, url=None):
        if url:
            parsed = urlparse(html.unescape(url))
            if parsed.scheme and parsed.netloc and parsed.path:
                matched_id = cls._job_id_from_url(url)
                if matched_id:
                    return f"https://www.linkedin.com/jobs/view/{matched_id}/"
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    @classmethod
    def _job_id_from_url(cls, url):
        if not url:
            return ""
        patterns = (
            r"/jobs/view/(\d+)",
            r"/jobs-guest/jobs/api/jobPosting/(\d+)",
            r"[?&]currentJobId=(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, str(url))
            if match:
                return match.group(1)
        return ""

    @classmethod
    def _extract_class_text(cls, content, class_name, preserve_breaks=False):
        if not content:
            return ""
        pattern = re.compile(
            rf'<[^>]+class=["\'][^"\']*{re.escape(class_name)}[^"\']*["\'][^>]*>(.*?)</[^>]+>',
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(content)
        if not match:
            return ""
        return cls._html_to_text(match.group(1), preserve_breaks=preserve_breaks)

    @classmethod
    def _extract_tag_text(cls, content, tag_name):
        match = re.search(
            rf"<{tag_name}[^>]*>(.*?)</{tag_name}>",
            content or "",
            flags=re.IGNORECASE | re.DOTALL,
        )
        return cls._html_to_text(match.group(1)) if match else ""

    @classmethod
    def _extract_time_value(cls, content):
        return cls._first_match(content, r"<time[^>]+datetime=[\"']([^\"']+)[\"']")

    @classmethod
    def _html_to_text(cls, value, preserve_breaks=False):
        if value is None:
            return ""
        text = str(value)
        if preserve_breaks:
            text = re.sub(r"</(p|li|div|br|ul|ol|h\d)>", "\n", text, flags=re.I)
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        if preserve_breaks:
            lines = [" ".join(line.split()) for line in text.splitlines()]
            return "\n".join(line for line in lines if line).strip()
        return " ".join(text.split()).strip()

    @staticmethod
    def _first_match(content, pattern):
        match = re.search(pattern, content or "", flags=re.IGNORECASE | re.DOTALL)
        return html.unescape(match.group(1)).strip() if match else ""

    @classmethod
    def _merge_raw_job(cls, card, detail):
        merged = dict(card)
        detail = dict(detail or {})
        detail_metadata = detail.pop("metadata", {}) or {}
        merged.update({key: value for key, value in detail.items() if value})
        if detail_metadata:
            metadata = dict(merged.get("metadata") or {})
            metadata.update(detail_metadata)
            merged["metadata"] = metadata
        return merged

    @classmethod
    def _dedupe_jobs(cls, jobs):
        deduped = []
        seen = set()
        for job in jobs:
            key = (
                job.get("jobPostingId")
                or job.get("jobUrl")
                or repr(sorted(job.items()))
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped

    @classmethod
    def _has_required_raw_fields(cls, raw_job):
        return bool(
            raw_job
            and (raw_job.get("jobTitle") or raw_job.get("title"))
            and (raw_job.get("companyName") or raw_job.get("company_name"))
            and (
                raw_job.get("jobUrl")
                or raw_job.get("source_url")
                or raw_job.get("jobPostingId")
            )
        )

    def _fetch_details_enabled(self):
        config = self._merged_config()
        return config.get("fetch_details", True) is not False

    def _positive_int_config(self, key, default):
        value = self._merged_config().get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _merged_config(self):
        if self.source is None or isinstance(self.source, str):
            return {}
        config = {}
        config.update(getattr(self.source, "filter_config", None) or {})
        config.update(getattr(self.source, "crawl_config", None) or {})
        return config

    @staticmethod
    def _first_config_value(config, *keys):
        for key in keys:
            value = config.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    @staticmethod
    def _coerce_query_value(value):
        if isinstance(value, (list, tuple, set)):
            return " ".join(str(item).strip() for item in value if str(item).strip())
        return str(value).strip()

    @classmethod
    def _reject_placeholder_job(cls, raw_job):
        text_values = [
            str(raw_job.get("jobPostingId") or ""),
            str(raw_job.get("external_id") or ""),
            str(raw_job.get("id") or ""),
            str(
                raw_job.get("jobUrl")
                or raw_job.get("source_url")
                or raw_job.get("url")
                or ""
            ),
        ]
        for value in text_values:
            digits = cls._job_id_from_url(value)
            if not digits:
                digits = "".join(
                    character for character in value if character.isdigit()
                )
            if digits in cls.PLACEHOLDER_JOB_IDS:
                raise ValueError(
                    "LinkedIn job payload contains a placeholder job id. "
                    "Use a real LinkedIn job URL or remove the sample crawl_config job."
                )
