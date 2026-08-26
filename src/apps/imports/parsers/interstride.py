import html
import json
import re
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from .base import BaseParser


class InterstrideAuthError(RuntimeError):
    pass


class InterstrideRateLimitError(RuntimeError):
    pass


class InterstrideNetworkError(RuntimeError):
    pass


class InterstridePayloadError(ValueError):
    pass


class InterstrideParser(BaseParser):
    """Fetch raw jobs from Interstride's authenticated student jobs API.

    Interstride's web client sends the account session token directly in the
    ``Authorization`` header. The token is intentionally read only from Django
    settings/environment and must never be persisted in ``JobSource`` JSON.
    """

    parser_type = "INTERSTRIDE"
    DEFAULT_API_BASE_URL = "https://web.production.interstride.com/api/v1/"
    DEFAULT_PORTAL_URL = "https://student.interstride.com/"
    DEFAULT_TIMEOUT_SECONDS = 12
    DEFAULT_MAX_PAGES = 3
    DEFAULT_MAX_SEARCH_REQUESTS = 3
    DEFAULT_MAX_DETAIL_REQUESTS = 3
    DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES = 60
    REQUEST_HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=utf-8",
        "Origin": "https://student.interstride.com",
        "Referer": "https://student.interstride.com/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
    }
    DETAIL_PATH_PATTERN = re.compile(
        r"/jobs/(?:job-details|detail)/([^/?#]+)",
        flags=re.IGNORECASE,
    )

    def __init__(self, source=None):
        super().__init__(source=source)
        self._request_count = 0

    def extract_jobs(self, listing_page):
        configured_jobs = self._configured_raw_jobs()
        if configured_jobs:
            return [self.extract_job(job) for job in configured_jobs]

        listing_url = getattr(listing_page, "url", "") or str(listing_page)
        if self._job_id_from_url(listing_url):
            return self.extract_single_job(listing_url)

        self._require_auth_token()
        max_pages = self._positive_int_config(
            "max_pages",
            self.DEFAULT_MAX_PAGES,
        )
        max_search_requests = self._positive_int_config(
            "max_search_requests",
            self.DEFAULT_MAX_SEARCH_REQUESTS,
        )
        max_detail_requests = self._positive_int_config(
            "max_detail_requests",
            self.DEFAULT_MAX_DETAIL_REQUESTS,
        )
        queries = self._search_queries()
        finished_queries = set()
        search_requests = 0
        detail_requests = 0
        jobs = []

        for page in range(1, max_pages + 1):
            for query in queries:
                if query in finished_queries:
                    continue
                if search_requests >= max_search_requests:
                    break

                response = self._request_json(
                    "jobs/search",
                    method="POST",
                    payload=self._search_payload(query=query, page=page),
                )
                search_requests += 1
                records, total_pages = self._search_records(response)
                if not records or page >= total_pages:
                    finished_queries.add(query)

                for record in records:
                    prepared = self._prepare_raw_job(record)
                    if not self._usable_job(prepared):
                        continue
                    if (
                        detail_requests < max_detail_requests
                        and self._should_fetch_detail(prepared)
                    ):
                        job_id = prepared.get("external_id")
                        detail = self._fetch_detail(job_id)
                        detail_requests += 1
                        if detail:
                            prepared = self._prepare_raw_job(
                                {**record, **detail},
                            )
                    if self._usable_job(prepared):
                        jobs.append(prepared)

            if search_requests >= max_search_requests or len(finished_queries) == len(
                queries
            ):
                break

        return self._dedupe_jobs(jobs)

    def extract_single_job(self, url):
        job_id = self._job_id_from_url(url)
        if not job_id:
            return []
        self._require_auth_token()
        detail = self._fetch_detail(job_id)
        if not detail:
            return []
        prepared = self._prepare_raw_job(detail)
        return [prepared] if self._usable_job(prepared) else []

    def extract_job(self, payload):
        raw = super().extract_job(payload)
        return self._prepare_raw_job(raw)

    def _fetch_detail(self, job_id):
        if not job_id:
            return None
        response = self._request_json(f"jobs/{quote(str(job_id), safe='')}")
        return self._detail_record(response)

    def _request_json(self, path, method="GET", payload=None):
        token = self._require_auth_token()
        url = urljoin(self._api_base_url(), str(path).lstrip("/"))
        headers = {**self.REQUEST_HEADERS, "Authorization": token}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        self._throttle_request()
        self._request_count += 1
        request = Request(url, data=body, headers=headers, method=method)
        timeout = self._positive_int_config(
            "timeout_seconds",
            getattr(
                settings,
                "INTERSTRIDE_TIMEOUT_SECONDS",
                self.DEFAULT_TIMEOUT_SECONDS,
            ),
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                response_body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                decoded = response_body.decode(charset, errors="replace")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise InterstrideAuthError(
                    "Interstride authentication failed. Replace "
                    "INTERSTRIDE_AUTH_TOKEN in the server environment with a "
                    "current authorized-account token, then restart the web "
                    "and Celery worker services."
                ) from exc
            if exc.code in {429, 503}:
                self._mark_rate_limited(exc.code)
                raise InterstrideRateLimitError(
                    f"HTTP Error {exc.code}: Interstride limited this crawl. "
                    "The source was placed on cooldown."
                ) from exc
            if exc.code in {404, 410}:
                return None
            raise InterstrideNetworkError(
                f"Interstride API returned HTTP {exc.code} for {path}."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise InterstrideNetworkError(
                f"Network error fetching Interstride API path {path}: {exc}"
            ) from exc

        try:
            result = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise InterstridePayloadError(
                f"Interstride API returned invalid JSON for {path}."
            ) from exc
        if not isinstance(result, (dict, list)):
            raise InterstridePayloadError(
                f"Interstride API returned an unsupported payload for {path}."
            )
        if isinstance(result, dict) and result.get("success") is False:
            message = " ".join(str(result.get("message") or "request failed").split())
            raise InterstridePayloadError(f"Interstride API error: {message}")
        return result

    def _search_payload(self, query, page):
        config = self._merged_config()
        country = self._country_code(config)
        payload = {
            "job_region": "us" if country == "us" else "international",
            "search": query,
            "country": country,
            "page": page,
            "sort": self._sort_value(config.get("sort_by") or config.get("sort")),
            "job_search_type": config.get("job_search_type") or "approx",
        }

        visa = self._first_config_value(config, "interstride_visa", "visa")
        if visa is None and country == "us":
            visa = "all_sponsored_companies"
        if visa:
            payload["visa"] = visa

        for config_key, payload_key in (
            ("city", "city"),
            ("state", "state"),
            ("industry_name", "industry_name"),
            ("cip_code", "cip_code"),
            ("degree", "degree"),
            ("experience", "experience"),
            ("languages", "languages"),
            ("programs", "programs"),
        ):
            value = self._api_filter_value(config.get(config_key))
            if value:
                payload[payload_key] = value

        job_types = self._api_filter_value(
            config.get("job_types") or config.get("job_type")
        )
        if job_types:
            payload["job_type"] = job_types

        if self._config_bool(config.get("remote_only"), default=False):
            payload["work_type"] = "remote"
        else:
            workplace_types = self._api_filter_value(
                config.get("workplace_types") or config.get("work_type")
            )
            if workplace_types:
                payload["work_type"] = workplace_types

        publish_date = self._publish_date(config.get("date_posted"))
        if publish_date is not None:
            payload["publish_date"] = publish_date

        companies = self._coerce_values(
            config.get("target_companies") or config.get("companies")
        )
        if len(companies) == 1:
            payload["company_name"] = companies[0]
        return payload

    @classmethod
    def _search_records(cls, response):
        data = (
            response.get("data", response) if isinstance(response, dict) else response
        )
        if isinstance(data, list):
            return data, 1
        if not isinstance(data, dict):
            raise InterstridePayloadError(
                "Interstride search response did not contain a data object."
            )

        records = next(
            (
                data.get(key)
                for key in ("jobs", "results", "items")
                if isinstance(data.get(key), list)
            ),
            [],
        )
        total_pages = cls._positive_int(
            data.get("total_pages") or data.get("totalPages") or data.get("pages") or 1,
            default=1,
        )
        return records, total_pages

    @classmethod
    def _detail_record(cls, response):
        if response is None:
            return None
        data = (
            response.get("data", response) if isinstance(response, dict) else response
        )
        if not isinstance(data, dict):
            return None
        for key in ("job", "employer_job", "featured_job", "result"):
            if isinstance(data.get(key), dict):
                return {**data, **data[key]}
        return data

    def _prepare_raw_job(self, record):
        raw = self._flatten_record(record)
        job_id = self._first(
            raw,
            "job_key",
            "job_id",
            "id",
            "external_id",
            "featured_job_id",
            "employer_job_id",
        )
        title = self._first(raw, "job_title", "title", "position", "name")
        company_name = self._first(
            raw,
            "company_name",
            "company",
            "employer_name",
            "employer",
            "organization",
        )
        application_url = self._first(
            raw,
            "job_application_url",
            "application_url",
            "apply_url",
            "job_link",
            "url",
        )
        permalink = self._first(raw, "permalink", "interstride_url")
        source_url = self._source_job_url(job_id, permalink, application_url)
        description = self._plain_text(
            self._first(
                raw,
                "description",
                "job_description",
                "description_plain",
                "job_info",
                "content",
            )
        )
        sections = self._sections(raw)
        if not description and sections:
            description = "\n\n".join(sections.values())

        metadata = raw.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata.update(
            {
                "source_parser": self.parser_type,
                "interstride_job_key": str(job_id or ""),
            }
        )
        if application_url:
            metadata["application_url"] = str(application_url)
        for key in (
            "posting_status",
            "job_status",
            "is_active",
            "is_closed",
            "job_expired",
            "source_confirms_closed",
        ):
            if key in raw:
                metadata[key] = raw[key]

        return {
            "source": "interstride",
            "external_id": str(job_id or "").strip(),
            "source_url": source_url,
            "title": self._plain_text(title),
            "company_name": self._plain_text(company_name),
            "location": self._location(raw),
            "job_type": self._first(
                raw,
                "job_type",
                "employment_type",
                "employmentType",
                "type",
            ),
            "remote_type": self._remote_type(raw),
            "description": description,
            "sections": sections,
            "posted_at": self._first(
                raw,
                "publish_date",
                "published_at",
                "date_posted",
                "posted_at",
                "created_at",
            ),
            "metadata": metadata,
        }

    @classmethod
    def _flatten_record(cls, record):
        if not isinstance(record, dict):
            raise InterstridePayloadError("Interstride job record must be an object.")
        flattened = dict(record)
        for key in ("job_info", "api_response", "job"):
            nested = record.get(key)
            if isinstance(nested, dict):
                flattened.update(nested)
        return flattened

    @classmethod
    def _sections(cls, raw):
        sections = raw.get("sections")
        sections = dict(sections) if isinstance(sections, dict) else {}
        for key, aliases in {
            "responsibilities": ("responsibilities", "job_responsibilities"),
            "requirements": ("requirements", "qualifications"),
            "minimum_qualifications": ("minimum_qualifications",),
            "preferred_qualifications": ("preferred_qualifications",),
        }.items():
            value = cls._plain_text(cls._first(raw, *aliases))
            if value:
                sections[key] = value
        return {
            str(key): cls._plain_text(value)
            for key, value in sections.items()
            if cls._plain_text(value)
        }

    @classmethod
    def _location(cls, raw):
        location = cls._first(raw, "location", "formatted_location")
        if isinstance(location, dict):
            location = cls._first(location, "name", "display_name", "location")
        if isinstance(location, list):
            location = ", ".join(
                cls._plain_text(item) for item in location if cls._plain_text(item)
            )
        if location:
            return cls._plain_text(location)
        parts = [
            cls._plain_text(cls._first(raw, key))
            for key in ("city", "state", "country")
        ]
        return ", ".join(part for part in parts if part)

    @classmethod
    def _remote_type(cls, raw):
        value = cls._first(
            raw,
            "work_type",
            "workplace_type",
            "remote_type",
            "remote",
        )
        if isinstance(value, bool):
            return "Remote" if value else ""
        return value

    def _source_job_url(self, job_id, permalink, application_url):
        if permalink:
            resolved = urljoin(self.DEFAULT_PORTAL_URL, str(permalink))
            if self._is_interstride_url(resolved):
                return resolved
        if job_id:
            return urljoin(
                self.DEFAULT_PORTAL_URL,
                f"jobs/job-details/{quote(str(job_id), safe='')}",
            )
        return str(application_url or "").strip()

    @classmethod
    def _job_id_from_url(cls, url):
        url = str(url or "").strip()
        if not cls._is_interstride_url(url):
            return ""
        match = cls.DETAIL_PATH_PATTERN.search(urlparse(url).path)
        return match.group(1) if match else ""

    @staticmethod
    def _is_interstride_url(url):
        host = (urlparse(str(url or "")).hostname or "").casefold()
        return host == "interstride.com" or host.endswith(".interstride.com")

    @staticmethod
    def _usable_job(job):
        return bool(
            job.get("title")
            and job.get("company_name")
            and (job.get("source_url") or job.get("external_id"))
        )

    def _should_fetch_detail(self, job):
        value = self._merged_config().get("fetch_details", "new_or_missing")
        normalized = str(value).strip().casefold()
        if value is False or normalized in {"false", "0", "none"}:
            return False
        if normalized == "all":
            return True
        return not bool(job.get("description"))

    @staticmethod
    def _dedupe_jobs(jobs):
        deduped = []
        seen = set()
        for job in jobs:
            key = (
                str(job.get("external_id") or "").strip().casefold(),
                str(job.get("source_url") or "").strip().casefold(),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped

    def _require_auth_token(self):
        token = str(getattr(settings, "INTERSTRIDE_AUTH_TOKEN", "") or "").strip()
        if not token:
            raise InterstrideAuthError(
                "Interstride authentication is not configured. Set "
                "INTERSTRIDE_AUTH_TOKEN in the server environment from an "
                "authorized account, then restart the web and Celery worker "
                "services."
            )
        return token

    def _api_base_url(self):
        value = str(
            getattr(settings, "INTERSTRIDE_API_BASE_URL", self.DEFAULT_API_BASE_URL)
            or self.DEFAULT_API_BASE_URL
        ).strip()
        return f"{value.rstrip('/')}/"

    def _search_queries(self):
        config = self._merged_config()
        values = self._coerce_values(
            config.get("search_keywords")
            or config.get("search")
            or config.get("keyword")
        )
        return values or [""]

    def _country_code(self, config):
        explicit = self._first_config_value(
            config,
            "interstride_country",
            "country",
            "country_code",
        )
        if explicit:
            value = self._coerce_values(explicit)[0]
        else:
            locations = self._coerce_values(
                config.get("location") or config.get("locations")
            )
            value = locations[0] if locations else "us"
        normalized = " ".join(str(value).casefold().split())
        aliases = {
            "united states": "us",
            "united states of america": "us",
            "usa": "us",
            "u.s.": "us",
            "united kingdom": "gb",
            "uk": "gb",
            "great britain": "gb",
            "canada": "ca",
            "ireland": "ie",
        }
        return aliases.get(normalized, normalized if len(normalized) == 2 else "us")

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

    def _mark_rate_limited(self, status_code):
        if not getattr(self.source, "pk", None):
            return
        from apps.imports.models import JobSource

        cooldown_minutes = self._positive_int_config(
            "rate_limit_cooldown_minutes",
            self.DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES,
        )
        crawl_config = self._crawl_config()
        crawl_config["rate_limit_status_code"] = status_code
        crawl_config["rate_limited_until"] = (
            timezone.now() + timedelta(minutes=cooldown_minutes)
        ).isoformat()
        JobSource.objects.filter(pk=self.source.pk).update(crawl_config=crawl_config)
        self.source.crawl_config = crawl_config

    def _throttle_request(self):
        delay = self._positive_float_config("request_delay_seconds", 0)
        if self._request_count and delay > 0:
            time.sleep(delay)

    def _positive_int_config(self, key, default):
        return self._positive_int(self._merged_config().get(key, default), default)

    def _positive_float_config(self, key, default):
        value = self._merged_config().get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default

    @staticmethod
    def _positive_int(value, default):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    @staticmethod
    def _first_config_value(config, *keys):
        for key in keys:
            value = config.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    @staticmethod
    def _first(mapping, *keys):
        if not isinstance(mapping, dict):
            return None
        for key in keys:
            value = mapping.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    @classmethod
    def _coerce_values(cls, value):
        if value in (None, "", [], {}, ()):
            return []
        if isinstance(value, str):
            raw_values = value.split(",") if "," in value else [value]
        elif isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = [value]
        return [cls._plain_text(item) for item in raw_values if cls._plain_text(item)]

    @classmethod
    def _api_filter_value(cls, value):
        return ",".join(cls._coerce_values(value))

    @staticmethod
    def _sort_value(value):
        normalized = str(value or "date").strip().casefold()
        return {"dd": "date", "r": "relevance"}.get(normalized, normalized)

    @staticmethod
    def _publish_date(value):
        if value in (None, ""):
            return None
        return {
            "r86400": 1,
            "r604800": 7,
            "r2592000": 30,
        }.get(str(value).strip().casefold(), value)

    @staticmethod
    def _config_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on"}

    @classmethod
    def _plain_text(cls, value):
        if value is None:
            return ""
        if isinstance(value, dict):
            value = "\n".join(str(item) for item in value.values() if item)
        elif isinstance(value, (list, tuple, set)):
            value = "\n".join(str(item) for item in value if item)
        text = str(value)
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
        text = re.sub(r"(?i)</\s*(li|p|div|h[1-6])\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text).replace("\xa0", " ")
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()
