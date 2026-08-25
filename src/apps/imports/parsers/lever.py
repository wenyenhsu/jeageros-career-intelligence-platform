import html
import json
import re
import time
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from .base import BaseParser


class LeverRateLimitError(RuntimeError):
    pass


class LeverNetworkError(RuntimeError):
    pass


class LeverPayloadError(ValueError):
    pass


class LeverParser(BaseParser):
    parser_type = "LEVER"
    DEFAULT_PAGE_SIZE = 100
    MAX_PAGE_SIZE = 100
    DEFAULT_MAX_PAGES = 1
    DEFAULT_MAX_SEARCH_REQUESTS = 3
    DEFAULT_TIMEOUT_SECONDS = 12
    DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES = 60
    JOB_API_HOSTS = {
        "jobs.lever.co": "api.lever.co",
        "jobs.eu.lever.co": "api.eu.lever.co",
    }
    API_JOB_HOSTS = {
        "api.lever.co": "jobs.lever.co",
        "api.eu.lever.co": "jobs.eu.lever.co",
    }
    API_FILTER_KEYS = {"location", "commitment", "team", "department", "level"}
    REQUEST_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    def __init__(self, source=None):
        super().__init__(source=source)
        self._request_count = 0

    def extract_jobs(self, listing_page):
        configured_jobs = self._configured_raw_jobs()
        if configured_jobs:
            return [self.extract_job(job) for job in configured_jobs]

        listing_url = getattr(listing_page, "url", "") or str(listing_page)
        context = self._url_context(listing_url)
        if not context.get("site"):
            raise ValueError(
                "Lever source URL must include a site slug, for example "
                "https://jobs.lever.co/acme."
            )
        if context.get("posting_id"):
            return self.extract_single_job(listing_url)

        page_size = min(
            self._positive_int_config("lever_page_size", self.DEFAULT_PAGE_SIZE),
            self.MAX_PAGE_SIZE,
        )
        page_limit = min(
            self._positive_int_config("max_pages", self.DEFAULT_MAX_PAGES),
            self._positive_int_config(
                "max_search_requests",
                self.DEFAULT_MAX_SEARCH_REQUESTS,
            ),
        )
        raw_jobs = []
        for page_number in range(page_limit):
            api_url = self._listing_api_url(
                context,
                skip=page_number * page_size,
                limit=page_size,
            )
            payload = self._fetch_json(api_url)
            if payload is None:
                break
            if not isinstance(payload, list):
                raise LeverPayloadError("Lever listing API did not return a JSON list.")

            page_jobs = [
                self._prepare_raw_job(job, context=context, api_url=api_url)
                for job in payload
                if isinstance(job, dict)
            ]
            raw_jobs.extend(page_jobs)
            if len(payload) < page_size:
                break

        return self._dedupe_jobs(raw_jobs)

    def extract_single_job(self, url):
        context = self._url_context(url)
        if not context.get("site") or not context.get("posting_id"):
            return []

        api_url = self._detail_api_url(context)
        payload = self._fetch_json(api_url)
        if not isinstance(payload, dict) or not payload.get("id"):
            raise ValueError(
                f"Lever job {context['posting_id']} did not return usable job data."
            )
        return [self._prepare_raw_job(payload, context=context, api_url=api_url)]

    def extract_job(self, payload):
        raw = super().extract_job(payload)
        if not isinstance(raw, dict):
            return raw
        context = self._url_context(self._source_url())
        return self._prepare_raw_job(raw, context=context, api_url="")

    def _prepare_raw_job(self, job, context, api_url):
        raw = dict(job)
        posting_id = str(
            raw.get("id")
            or raw.get("external_id")
            or raw.get("lever_id")
            or context.get("posting_id")
            or ""
        ).strip()
        hosted_url = str(
            raw.get("hostedUrl")
            or raw.get("hosted_url")
            or raw.get("source_url")
            or raw.get("url")
            or ""
        ).strip()
        if not context.get("site") and hosted_url:
            context = self._url_context(hosted_url)
        site = str(context.get("site") or raw.get("lever_site") or "").strip()
        if not hosted_url and site and posting_id:
            hosted_url = f"https://{context['job_host']}/{site}/{posting_id}"

        company_name = next(
            (
                " ".join(str(raw.get(key) or "").split()).strip()
                for key in ("company_name", "company", "companyName", "employer")
                if " ".join(str(raw.get(key) or "").split()).strip()
            ),
            "",
        ) or self._company_name(site)

        sections = self._extract_sections(raw)
        description = self._description_text(raw, sections)
        existing_sections = raw.get("sections")
        if isinstance(existing_sections, dict):
            sections = {**existing_sections, **sections}

        metadata = raw.get("metadata")
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        metadata.setdefault("source_parser", self.parser_type)
        metadata.setdefault("lever_site", site)
        metadata.setdefault("posting_status", "published")
        if api_url:
            metadata.setdefault("lever_api_url", api_url)
        for raw_key, metadata_key in (
            ("country", "country"),
            ("salaryRange", "salary_range"),
            ("salaryDescriptionPlain", "salary_description"),
        ):
            if raw.get(raw_key) not in (None, "", [], {}):
                metadata.setdefault(metadata_key, raw[raw_key])

        raw.update(
            {
                "source": "lever",
                "external_id": posting_id,
                "source_url": hosted_url,
                "leverCompanyName": company_name,
                "description": description,
                "sections": sections,
                "metadata": metadata,
            }
        )
        return raw

    @classmethod
    def _extract_sections(cls, raw):
        sections = {}
        lists = raw.get("lists")
        if isinstance(lists, list):
            for index, item in enumerate(lists, start=1):
                if not isinstance(item, dict):
                    continue
                heading = cls._plain_text(item.get("text")) or f"section_{index}"
                content = cls._plain_text(item.get("content"))
                if not content:
                    continue
                key = cls._section_key(heading)
                if key in sections:
                    sections[key] = f"{sections[key]}\n{content}"
                else:
                    sections[key] = content

        salary_description = cls._plain_text(raw.get("salaryDescriptionPlain"))
        if salary_description:
            sections.setdefault("compensation", salary_description)
        return sections

    @classmethod
    def _description_text(cls, raw, sections):
        description = cls._plain_text(raw.get("descriptionPlain"))
        if not description:
            description = cls._plain_text(raw.get("description"))
        if not description:
            opening = cls._plain_text(raw.get("openingPlain") or raw.get("opening"))
            body = cls._plain_text(
                raw.get("descriptionBodyPlain") or raw.get("descriptionBody")
            )
            description = "\n\n".join(part for part in (opening, body) if part)

        parts = [description] if description else []
        searchable = description.casefold() if description else ""
        for section_text in sections.values():
            if section_text.casefold() not in searchable:
                parts.append(section_text)
        additional = cls._plain_text(
            raw.get("additionalPlain") or raw.get("additional")
        )
        if additional and additional.casefold() not in searchable:
            parts.append(additional)
        return "\n\n".join(part for part in parts if part)

    @staticmethod
    def _section_key(heading):
        normalized = " ".join(str(heading or "").casefold().split())
        if "minimum" in normalized and (
            "qualification" in normalized or "requirement" in normalized
        ):
            return "minimum_qualifications"
        if "preferred" in normalized and (
            "qualification" in normalized or "requirement" in normalized
        ):
            return "preferred_qualifications"
        if "qualification" in normalized or "requirement" in normalized:
            return "requirements"
        if any(
            phrase in normalized
            for phrase in ("responsibil", "what you will do", "what you'll do")
        ):
            return "responsibilities"
        key = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        return key or "details"

    @staticmethod
    def _plain_text(value):
        text = str(value or "")
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
        text = re.sub(r"(?i)</\s*(li|p|div|h[1-6])\s*>", "\n", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text).replace("\xa0", " ")
        lines = [" ".join(line.split()) for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()

    def _listing_api_url(self, context, skip, limit):
        params = self._api_filters(context)
        params.update({"mode": "json", "skip": str(skip), "limit": str(limit)})
        return (
            f"https://{context['api_host']}/v0/postings/{context['site']}?"
            f"{urlencode(params, doseq=True)}"
        )

    @staticmethod
    def _detail_api_url(context):
        return (
            f"https://{context['api_host']}/v0/postings/"
            f"{context['site']}/{context['posting_id']}"
        )

    def _api_filters(self, context):
        filters = {}
        parsed_query = parse_qs(context.get("query") or "", keep_blank_values=False)
        for key in self.API_FILTER_KEYS:
            values = parsed_query.get(key)
            if values:
                filters[key] = values

        configured = self._crawl_config().get("lever_api_filters")
        if not isinstance(configured, dict):
            configured = self._crawl_config().get("api_filters")
        if isinstance(configured, dict):
            for key, value in configured.items():
                if key in self.API_FILTER_KEYS and value not in (None, "", [], {}):
                    filters[key] = value
        return filters

    @classmethod
    def _url_context(cls, url):
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").casefold()
        segments = [segment for segment in parsed.path.split("/") if segment]
        site = ""
        posting_id = ""

        if host in cls.JOB_API_HOSTS:
            site = segments[0] if segments else ""
            posting_id = segments[1] if len(segments) > 1 else ""
            api_host = cls.JOB_API_HOSTS[host]
            job_host = host
        elif host in cls.API_JOB_HOSTS:
            if len(segments) >= 3 and segments[:2] == ["v0", "postings"]:
                site = segments[2]
                posting_id = segments[3] if len(segments) > 3 else ""
            api_host = host
            job_host = cls.API_JOB_HOSTS[host]
        else:
            api_host = "api.lever.co"
            job_host = "jobs.lever.co"

        return {
            "site": site,
            "posting_id": posting_id,
            "api_host": api_host,
            "job_host": job_host,
            "query": parsed.query,
        }

    def _company_name(self, site):
        if not isinstance(self.source, str):
            for config in (
                getattr(self.source, "filter_config", None) or {},
                getattr(self.source, "crawl_config", None) or {},
            ):
                for key in ("company_name", "company", "employer"):
                    value = " ".join(str(config.get(key) or "").split()).strip()
                    if value:
                        return value
                companies = config.get("target_companies") or config.get("companies")
                if isinstance(companies, list) and companies:
                    value = " ".join(str(companies[0] or "").split()).strip()
                    if value:
                        return value
        return " ".join(re.sub(r"[-_]+", " ", site).split()).title()

    def _fetch_json(self, url):
        body = self._fetch_url(url)
        if body is None:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LeverPayloadError(
                f"Lever API returned invalid JSON for {url}."
            ) from exc

    def _fetch_url(self, url):
        self._throttle_request()
        self._request_count += 1
        timeout = self._positive_int_config(
            "timeout_seconds",
            self.DEFAULT_TIMEOUT_SECONDS,
        )
        request = Request(str(url), headers=self.REQUEST_HEADERS)
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return body.decode(charset, errors="replace")
        except HTTPError as exc:
            if exc.code in {429, 503}:
                self._mark_rate_limited(exc.code)
                raise LeverRateLimitError(
                    f"HTTP Error {exc.code}: Lever limited this crawl. "
                    "Reduce max_search_requests or wait before retrying."
                ) from exc
            if exc.code in {404, 410}:
                return None
            raise
        except (URLError, TimeoutError, OSError) as exc:
            raise LeverNetworkError(
                f"Network error fetching Lever API: {url} ({exc})"
            ) from exc

    def _dedupe_jobs(self, jobs):
        deduped = []
        seen = set()
        for job in jobs:
            key = (
                str(job.get("external_id") or job.get("id") or "").strip().casefold(),
                str(job.get("source_url") or job.get("hostedUrl") or "")
                .strip()
                .casefold(),
            )
            if not key[0] and not key[1]:
                deduped.append(job)
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped

    def _source_url(self):
        if isinstance(self.source, str):
            return self.source
        return getattr(self.source, "base_url", "") or ""

    def _crawl_config(self):
        if isinstance(self.source, str):
            return {}
        return getattr(self.source, "crawl_config", None) or {}

    def _mark_rate_limited(self, status_code):
        if not getattr(self.source, "pk", None):
            return
        from django.utils import timezone

        from apps.imports.models import JobSource

        cooldown_minutes = self._positive_int_config(
            "rate_limit_cooldown_minutes",
            self.DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES,
        )
        crawl_config = dict(self._crawl_config())
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
        value = self._crawl_config().get(key, default)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    def _positive_float_config(self, key, default):
        value = self._crawl_config().get(key, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default
