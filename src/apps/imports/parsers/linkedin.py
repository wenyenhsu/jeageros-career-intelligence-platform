import html
import re
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from django.db.models import Q
from django.utils import timezone

from .base import BaseParser


class LinkedInRateLimitError(RuntimeError):
    pass


class LinkedInNetworkError(RuntimeError):
    pass


class LinkedInParser(BaseParser):
    parser_type = "LINKEDIN"
    GUEST_SEARCH_URL = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    )
    GUEST_JOB_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    DEFAULT_PAGE_SIZE = 25
    DEFAULT_TIMEOUT_SECONDS = 12
    DEFAULT_MAX_SEARCH_REQUESTS = 10
    DEFAULT_MAX_DETAIL_REQUESTS = 10
    DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES = 60
    DEFAULT_SORT_BY = "DD"
    DEFAULT_DATE_POSTED = "r604800"
    PLACEHOLDER_JOB_IDS = {"1234567890", "0000000000", "1111111111"}
    JOB_TYPE_PATTERNS = (
        ("Full-time", r"\bfull[\s-]?time\b"),
        ("Part-time", r"\bpart[\s-]?time\b"),
        ("Internship", r"\binternship\b|\bco[\s-]?op\b"),
        ("Contract", r"\bcontract(or)?\b"),
        ("Temporary", r"\btemp(orary)?\b"),
    )
    LINKEDIN_JOB_TYPE_FILTERS = {
        "full time": "F",
        "full-time": "F",
        "fulltime": "F",
        "full_time": "F",
        "f": "F",
        "part time": "P",
        "part-time": "P",
        "parttime": "P",
        "part_time": "P",
        "p": "P",
        "contract": "C",
        "contractor": "C",
        "c": "C",
        "temporary": "T",
        "temp": "T",
        "t": "T",
        "internship": "I",
        "intern": "I",
        "i": "I",
        "volunteer": "V",
        "v": "V",
        "other": "O",
        "o": "O",
    }
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, source=None):
        super().__init__(source=source)
        self._request_count = 0
        self._detail_requests_made = 0

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
            if not self._should_fetch_detail_for_card(card):
                jobs.append(card)
                continue
            if not self._detail_request_available():
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

        query_sets = self._search_query_param_sets(base_url)
        max_pages = self._positive_int_config("max_pages", default=1)
        max_search_requests = self._positive_int_config(
            "max_search_requests",
            default=self.DEFAULT_MAX_SEARCH_REQUESTS,
        )
        all_urls = []
        for page in range(max_pages):
            for query in query_sets:
                page_query = dict(query)
                page_query["start"] = str(page * self.DEFAULT_PAGE_SIZE)
                all_urls.append(
                    f"{self.GUEST_SEARCH_URL}?{urlencode(page_query, doseq=True)}"
                )
        return self._rolling_search_urls(all_urls, max_search_requests)

    def _search_query_param_sets(self, base_url):
        parsed = urlparse(base_url or "")
        base_query = {
            key: value[-1]
            for key, value in parse_qs(parsed.query, keep_blank_values=False).items()
            if value
        }
        config = self._merged_config()

        keyword_values = self._query_values(
            base_query,
            config,
            "keywords",
            ("search_keywords", "include_keywords", "keywords", "keyword", "query"),
        )
        location_values = self._query_values(
            base_query,
            config,
            "location",
            ("locations", "location"),
        )
        workplace_values = self._workplace_query_values(base_query, config)
        job_type_values = self._job_type_query_values(base_query, config)
        date_posted = self._date_posted_query_value(base_query, config)
        sort_by = self._sort_by_query_value(base_query, config)

        for key in ("geoId", "f_WT", "f_E"):
            if key in config and key not in base_query:
                base_query[key] = self._coerce_query_value(config[key])
        if date_posted and "f_TPR" not in base_query:
            base_query["f_TPR"] = date_posted
        if sort_by and "sortBy" not in base_query:
            base_query["sortBy"] = sort_by

        base_query.pop("currentJobId", None)
        query_sets = []
        seen = set()
        for keywords in keyword_values:
            for location in location_values:
                for workplace in workplace_values:
                    for job_type in job_type_values:
                        query = dict(base_query)
                        if keywords:
                            query["keywords"] = keywords
                        if location:
                            query["location"] = location
                        if workplace:
                            query["f_WT"] = workplace
                        if job_type:
                            query["f_JT"] = job_type
                        key = tuple(sorted(query.items()))
                        if key in seen:
                            continue
                        seen.add(key)
                        query_sets.append(query)

        max_combinations = self._positive_int_config(
            "max_search_combinations",
            default=60,
        )
        return query_sets[:max_combinations] or [base_query]

    def _query_values(self, base_query, config, query_key, config_keys):
        if query_key in base_query:
            return [self._coerce_query_value(base_query[query_key])]

        for key in config_keys:
            value = config.get(key)
            values = self._coerce_query_values(value)
            if values:
                return values
        return [""]

    def _workplace_query_values(self, base_query, config):
        if "f_WT" in base_query:
            return [self._coerce_query_value(base_query["f_WT"])]
        if config.get("remote_only"):
            return ["2"]
        if "f_WT" in config:
            return self._coerce_query_values(config.get("f_WT")) or [""]

        workplace_types = self._coerce_query_values(config.get("workplace_types"))
        if not workplace_types:
            return [""]

        mapped = {
            self._workplace_type_to_linkedin_filter(workplace_type)
            for workplace_type in workplace_types
        }
        mapped.discard("")
        if not mapped or {"1", "2", "3"}.issubset(mapped):
            return [""]
        return sorted(mapped)

    def _job_type_query_values(self, base_query, config):
        if "f_JT" in base_query:
            return [self._coerce_query_value(base_query["f_JT"])]
        if "f_JT" in config:
            return self._coerce_query_values(config.get("f_JT")) or [""]

        configured = (
            config.get("job_types")
            or config.get("job_type")
            or config.get("employment_types")
            or config.get("employment_type")
        )
        values = self._coerce_query_values(configured)
        if not values:
            return [""]

        mapped = {self._job_type_to_linkedin_filter(value) for value in values}
        mapped.discard("")
        return sorted(mapped) or [""]

    def _date_posted_query_value(self, base_query, config):
        if "f_TPR" in base_query:
            return self._coerce_query_value(base_query["f_TPR"])
        if "f_TPR" in config:
            return self._coerce_query_value(config.get("f_TPR"))
        return self._date_posted_to_linkedin_filter(
            self._first_config_value(
                config,
                "date_posted",
                "date_posted_filter",
                "posted_within",
            )
            or self.DEFAULT_DATE_POSTED
        )

    def _sort_by_query_value(self, base_query, config):
        if "sortBy" in base_query:
            return self._coerce_query_value(base_query["sortBy"])
        value = self._first_config_value(config, "sortBy", "sort_by", "sort")
        return self._normalize_sort_by(value or self.DEFAULT_SORT_BY)

    def _fetch_job_detail(self, job_id):
        self._reject_placeholder_job({"jobPostingId": job_id})
        self._detail_requests_made += 1
        detail_html = self._fetch_url(self.GUEST_JOB_URL.format(job_id=job_id))
        raw_job = self._parse_job_detail(detail_html)
        raw_job.setdefault("jobPostingId", job_id)
        raw_job.setdefault("jobUrl", self._canonical_job_url(job_id))
        self._reject_placeholder_job(raw_job)
        return raw_job

    def _fetch_url(self, url):
        if not url:
            return ""
        self._throttle_request()
        self._request_count += 1
        request = Request(str(url), headers=self.REQUEST_HEADERS)
        timeout = self._positive_int_config(
            "timeout_seconds", default=self.DEFAULT_TIMEOUT_SECONDS
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
        except HTTPError as exc:
            if exc.code in {426, 429}:
                self._mark_rate_limited(exc.code)
                raise LinkedInRateLimitError(
                    f"HTTP Error {exc.code}: LinkedIn limited this crawl. "
                    "The source was put on cooldown; reduce max_search_requests/"
                    "max_detail_requests or wait before retrying."
                ) from exc
            raise
        except (URLError, TimeoutError, OSError) as exc:
            raise LinkedInNetworkError(
                self._network_error_message(url, exc)
            ) from exc

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
                "employmentType": self._extract_job_type_label(block),
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
        employment_type = criteria.get(
            "employment type"
        ) or self._extract_detail_job_type(content)
        raw_job = {
            "jobTitle": self._extract_class_text(content, "top-card-layout__title")
            or self._extract_tag_text(content, "h1"),
            "companyName": self._extract_class_text(content, "topcard__org-name-link")
            or self._extract_class_text(content, "topcard__flavor--black-link"),
            "formattedLocation": self._extract_class_text(
                content,
                "topcard__flavor--bullet",
            ),
            "employmentType": employment_type,
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

    @classmethod
    def _extract_detail_job_type(cls, content):
        if not content:
            return ""
        top_card_content = re.split(
            r'class=["\'][^"\']*show-more-less-html__markup[^"\']*["\']',
            content,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return cls._extract_job_type_label(top_card_content)

    @classmethod
    def _extract_job_type_label(cls, content):
        text = cls._html_to_text(content or "")
        if not text:
            return ""
        for label, pattern in cls.JOB_TYPE_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return label
        return ""

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
    def _date_posted_to_linkedin_filter(cls, value):
        key = " ".join(str(value or "").casefold().replace("_", " ").split())
        if not key:
            return ""
        mapping = {
            "r86400": "r86400",
            "24h": "r86400",
            "24 hours": "r86400",
            "past 24 hours": "r86400",
            "last 24 hours": "r86400",
            "day": "r86400",
            "today": "r86400",
            "r604800": "r604800",
            "week": "r604800",
            "past week": "r604800",
            "last week": "r604800",
            "7 days": "r604800",
            "r2592000": "r2592000",
            "month": "r2592000",
            "past month": "r2592000",
            "last month": "r2592000",
            "30 days": "r2592000",
            "any": "",
            "any time": "",
            "all": "",
        }
        return mapping.get(key, str(value).strip())

    @staticmethod
    def _normalize_sort_by(value):
        key = " ".join(str(value or "").casefold().replace("_", " ").split())
        if key in {"dd", "date", "date posted", "newest", "newest first", "latest"}:
            return "DD"
        if key in {"r", "relevance", "relevant", "most relevant"}:
            return "R"
        text = str(value or "").strip().upper()
        return text if text in {"DD", "R"} else ""

    @classmethod
    def _network_error_message(cls, url, exc):
        host = urlparse(str(url or "")).netloc or "LinkedIn"
        reason = getattr(exc, "reason", exc)
        return (
            f"LinkedIn network request failed for {host}: {reason}. "
            "Check Docker/celery outbound network, DNS, VPN, and internet access."
        )

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
        value = config.get("fetch_details", True)
        if isinstance(value, str):
            return value.strip().casefold() not in {
                "0",
                "false",
                "no",
                "off",
                "none",
                "never",
            }
        return value is not False

    def _fetch_details_strategy(self):
        config = self._merged_config()
        if self._config_bool(
            config,
            ("fetch_details_for_new_only", "fetch_details_new_only"),
            default=False,
        ):
            return "new_only"

        value = (
            config.get("fetch_details_for")
            or config.get("fetch_details_strategy")
            or config.get("detail_fetch_strategy")
        )
        if value is None and isinstance(config.get("fetch_details"), str):
            value = config.get("fetch_details")

        key = str(value or "all").strip().casefold().replace("-", "_")
        aliases = {
            "all": "all",
            "always": "all",
            "new": "new_only",
            "new_only": "new_only",
            "new_jobs": "new_only",
            "new_or_missing": "new_or_missing",
            "new_or_missing_description": "new_or_missing",
            "missing": "new_or_missing",
            "missing_description": "new_or_missing",
            "missing_only": "new_or_missing",
        }
        return aliases.get(key, "all")

    def _should_fetch_detail_for_card(self, card):
        strategy = self._fetch_details_strategy()
        if strategy == "all":
            return True

        existing_job = self._existing_job_for_card(card)
        if existing_job is None:
            return True
        if strategy == "new_only":
            return False
        if strategy == "new_or_missing":
            return not (existing_job.description or "").strip()
        return True

    def _detail_request_available(self):
        max_detail_requests = self._positive_int_config(
            "max_detail_requests",
            default=self.DEFAULT_MAX_DETAIL_REQUESTS,
        )
        return self._detail_requests_made < max_detail_requests

    def _existing_job_for_card(self, card):
        from apps.jobs.models import JobPost

        external_id = (card.get("jobPostingId") or "").strip()
        source_url = (card.get("jobUrl") or "").strip()
        if not source_url and external_id:
            source_url = self._canonical_job_url(external_id)

        filters = None
        if external_id:
            filters = Q(external_id=external_id)
        if source_url:
            source_url_filter = Q(source_url=source_url)
            filters = (
                source_url_filter if filters is None else filters | source_url_filter
            )
        if filters is None:
            return None
        return JobPost.objects.filter(filters).only("id", "description").first()

    def _positive_int_config(self, key, default):
        value = self._merged_config().get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _positive_float_config(self, key, default):
        value = self._merged_config().get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _throttle_request(self):
        delay = self._positive_float_config("request_delay_seconds", default=0)
        if self._request_count and delay > 0:
            time.sleep(delay)

    def _rolling_search_urls(self, urls, max_search_requests):
        if not urls:
            return []
        if max_search_requests >= len(urls):
            return urls

        config = self._merged_config()
        if not self._config_bool(
            config,
            ("rolling_search", "rolling_search_enabled"),
            default=True,
        ):
            return urls[:max_search_requests]

        offset = self._rolling_search_offset(len(urls))
        selected = (urls[offset:] + urls[:offset])[:max_search_requests]
        next_offset = (offset + len(selected)) % len(urls)
        self._save_rolling_search_offset(next_offset, len(urls))
        return selected

    def _rolling_search_offset(self, total_urls):
        crawl_config = self._crawl_config()
        rolling_state = crawl_config.get("rolling_state")
        if not isinstance(rolling_state, dict):
            rolling_state = {}
        try:
            offset = int(rolling_state.get("linkedin_search_offset", 0))
        except (TypeError, ValueError):
            offset = 0
        return offset % total_urls if total_urls else 0

    def _save_rolling_search_offset(self, next_offset, total_urls):
        if not getattr(self.source, "pk", None):
            return
        crawl_config = self._crawl_config()
        rolling_state = crawl_config.get("rolling_state")
        if not isinstance(rolling_state, dict):
            rolling_state = {}
        rolling_state.update(
            {
                "linkedin_search_offset": next_offset,
                "linkedin_search_total": total_urls,
                "updated_at": timezone.now().isoformat(),
            }
        )
        crawl_config["rolling_state"] = rolling_state
        self.source.crawl_config = crawl_config
        self.source.save(update_fields=["crawl_config", "updated_at"])

    def _mark_rate_limited(self, status_code):
        if not getattr(self.source, "pk", None):
            return
        cooldown_minutes = self._positive_int_config(
            "rate_limit_cooldown_minutes",
            default=self.DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES,
        )
        crawl_config = self._crawl_config()
        crawl_config["rate_limited_until"] = (
            timezone.now() + timedelta(minutes=cooldown_minutes)
        ).isoformat()
        crawl_config["rate_limit_status_code"] = status_code
        self.source.crawl_config = crawl_config
        self.source.save(update_fields=["crawl_config", "updated_at"])

    def _merged_config(self):
        if self.source is None or isinstance(self.source, str):
            return {}
        config = {}
        config.update(getattr(self.source, "filter_config", None) or {})
        config.update(getattr(self.source, "crawl_config", None) or {})
        return config

    def _crawl_config(self):
        if self.source is None or isinstance(self.source, str):
            return {}
        return dict(getattr(self.source, "crawl_config", None) or {})

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
    def _coerce_query_values(cls, value):
        if value in (None, "", [], {}):
            return []
        if isinstance(value, str):
            raw_values = value.split(",") if "," in value else [value]
        elif isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = [value]

        values = []
        seen = set()
        for raw_value in raw_values:
            text = cls._coerce_query_value(raw_value)
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            values.append(text)
        return values

    @staticmethod
    def _config_bool(config, keys, default=False):
        for key in keys:
            if key not in config:
                continue
            value = config[key]
            if isinstance(value, bool):
                return value
            return str(value).strip().casefold() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _workplace_type_to_linkedin_filter(value):
        key = " ".join(str(value or "").casefold().replace("_", " ").split())
        aliases = {
            "on site": "1",
            "onsite": "1",
            "on-site": "1",
            "remote": "2",
            "hybrid": "3",
        }
        return aliases.get(key, "")

    @classmethod
    def _job_type_to_linkedin_filter(cls, value):
        key = " ".join(str(value or "").casefold().replace("_", " ").split())
        return cls.LINKEDIN_JOB_TYPE_FILTERS.get(key, "")

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
