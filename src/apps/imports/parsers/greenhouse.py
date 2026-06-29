import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import BaseParser


class GreenhouseRateLimitError(RuntimeError):
    pass


class GreenhouseNetworkError(RuntimeError):
    pass


class GreenhouseParser(BaseParser):
    """Aggregate Greenhouse jobs across public board tokens (MyGreenhouse-style search).

    MyGreenhouse's authenticated search API is not public. This parser queries the
    public Job Board API for configured board tokens and applies keyword/job-type
    filters locally, similar to how LinkedIn sources are configured.
    """

    parser_type = "GREENHOUSE"
    MYGREENHOUSE_BASE_URL = "https://my.greenhouse.io/"
    BOARD_API_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    DEFAULT_TIMEOUT_SECONDS = 12
    DEFAULT_MAX_SEARCH_REQUESTS = 8
    DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES = 60
    DEFAULT_BOARD_TOKENS = (
        "stripe",
        "databricks",
        "anthropic",
        "coinbase",
        "discord",
        "airbnb",
        "reddit",
        "cloudflare",
        "vercel",
        "cohere",
        "lyft",
        "doordash",
        "shopify",
        "uber",
    )
    JOB_TYPE_PATTERNS = (
        ("Full-time", r"\bfull[\s-]?time\b"),
        ("Part-time", r"\bpart[\s-]?time\b"),
        ("Internship", r"\bintern(ship)?\b|\bco[\s-]?op\b"),
        ("Contract", r"\bcontract(or)?\b"),
        ("Temporary", r"\btemp(orary)?\b"),
    )
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

        raw_jobs = []
        for board_token in self._selected_board_tokens():
            board_jobs = self._fetch_board_jobs(board_token)
            raw_jobs.extend(board_jobs)
        return self._dedupe_jobs(raw_jobs)

    def extract_job(self, payload):
        raw = super().extract_job(payload)
        if isinstance(raw, dict):
            raw.setdefault("source", "greenhouse")
            if raw.get("content") and not raw.get("description"):
                raw["description"] = self._decode_html(raw.get("content"))
        return raw

    def _fetch_board_jobs(self, board_token):
        include_content = self._fetch_details_enabled()
        url = self.BOARD_API_URL.format(token=board_token)
        if include_content:
            url = f"{url}?content=true"
        try:
            payload = self._fetch_json(url)
        except GreenhouseRateLimitError:
            raise
        except Exception:
            return []

        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        if not isinstance(jobs, list):
            return []

        raw_jobs = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            raw_job = self._normalize_board_job(job, board_token)
            if self._matches_parser_filters(raw_job):
                raw_jobs.append(raw_job)
        return raw_jobs

    def _normalize_board_job(self, job, board_token):
        location = job.get("location")
        if isinstance(location, dict):
            location_name = location.get("name")
        else:
            location_name = location

        company_name = job.get("company_name") or board_token.replace("-", " ").title()
        content = job.get("content") or ""
        description = self._decode_html(content) if content else ""

        raw_job = {
            "source": "greenhouse",
            "id": job.get("id"),
            "external_id": str(job.get("id") or ""),
            "title": job.get("title"),
            "company_name": company_name,
            "absolute_url": job.get("absolute_url"),
            "location": location_name,
            "content": content,
            "description": description,
            "updated_at": job.get("updated_at"),
            "first_published": job.get("first_published"),
            "metadata": {
                "board_token": board_token,
                "internal_job_id": job.get("internal_job_id"),
                "requisition_id": job.get("requisition_id"),
                "departments": job.get("departments"),
                "offices": job.get("offices"),
            },
        }
        raw_job["job_type"] = self._infer_job_type(raw_job)
        return raw_job

    def _matches_parser_filters(self, raw_job):
        keywords = self._search_keywords()
        if keywords:
            title = str(raw_job.get("title") or "").casefold()
            if not any(keyword.casefold() in title for keyword in keywords):
                return False

        job_types = self._configured_job_types()
        if job_types:
            inferred = (raw_job.get("job_type") or "").casefold()
            allowed = {value.casefold() for value in job_types}
            if inferred and inferred not in allowed:
                return False

        if self._config_bool(self._merged_config(), ("remote_only",), default=False):
            location_text = str(raw_job.get("location") or "").casefold()
            if "remote" not in location_text:
                return False

        date_posted = self._date_posted_cutoff()
        if date_posted:
            posted_at = self._parse_datetime(
                raw_job.get("first_published") or raw_job.get("updated_at")
            )
            if posted_at and posted_at < date_posted:
                return False

        return True

    def _selected_board_tokens(self):
        tokens = self._board_tokens()
        max_requests = self._positive_int_config(
            "max_search_requests",
            default=self.DEFAULT_MAX_SEARCH_REQUESTS,
        )
        return self._rolling_board_tokens(tokens, max_requests)

    def _board_tokens(self):
        config = self._merged_config()
        for key in ("board_tokens", "boards", "companies"):
            values = self._coerce_values(config.get(key))
            if values:
                return values

        filter_config = getattr(self.source, "filter_config", None) or {}
        for key in ("board_tokens", "boards"):
            values = self._coerce_values(filter_config.get(key))
            if values:
                return values

        target_companies = self._coerce_values(filter_config.get("target_companies"))
        if target_companies:
            return [self._company_to_board_token(name) for name in target_companies]

        return list(self.DEFAULT_BOARD_TOKENS)

    def _rolling_board_tokens(self, tokens, max_requests):
        if not tokens:
            return []
        if max_requests >= len(tokens):
            return tokens

        config = self._merged_config()
        if not self._config_bool(
            config,
            ("rolling_search", "rolling_search_enabled"),
            default=True,
        ):
            return tokens[:max_requests]

        offset = self._rolling_board_offset(len(tokens))
        selected = (tokens[offset:] + tokens[:offset])[:max_requests]
        next_offset = (offset + len(selected)) % len(tokens)
        self._save_rolling_board_offset(next_offset, len(tokens))
        return selected

    def _search_keywords(self):
        config = self._merged_config()
        filter_config = getattr(self.source, "filter_config", None) or {}
        for source_config in (filter_config, config):
            for key in ("search_keywords", "keywords", "keyword", "query"):
                values = self._coerce_values(source_config.get(key))
                if values:
                    return values
        return []

    def _configured_job_types(self):
        filter_config = getattr(self.source, "filter_config", None) or {}
        config = self._merged_config()
        for source_config in (filter_config, config):
            for key in ("job_types", "job_type", "employment_types"):
                values = self._coerce_values(source_config.get(key))
                if values:
                    return values
        return []

    def _fetch_json(self, url):
        body = self._fetch_url(url)
        if not body:
            return {}
        return json.loads(body)

    def _fetch_url(self, url):
        if not url:
            return ""
        self._throttle_request()
        self._request_count += 1
        timeout = self._positive_int_config(
            "timeout_seconds", default=self.DEFAULT_TIMEOUT_SECONDS
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
                raise GreenhouseRateLimitError(
                    f"HTTP Error {exc.code}: Greenhouse limited this crawl. "
                    "Reduce max_search_requests or wait before retrying."
                ) from exc
            if exc.code == 404:
                return ""
            raise
        except (URLError, TimeoutError, OSError) as exc:
            raise GreenhouseNetworkError(
                f"Network error fetching Greenhouse board: {url} ({exc})"
            ) from exc

    def _infer_job_type(self, raw_job):
        config = self._merged_config()
        default_job_type = config.get("default_job_type")
        if default_job_type:
            return default_job_type

        searchable = self._searchable_text(raw_job)
        for label, pattern in self.JOB_TYPE_PATTERNS:
            if re.search(pattern, searchable, flags=re.IGNORECASE):
                return label
        return ""

    def _searchable_text(self, raw_job):
        parts = (
            raw_job.get("title"),
            raw_job.get("description"),
            raw_job.get("location"),
            raw_job.get("company_name"),
        )
        return " ".join(str(part or "") for part in parts).casefold()

    def _date_posted_cutoff(self):
        config = self._merged_config()
        value = config.get("date_posted") or config.get("posted_within")
        if not value:
            return None

        normalized = str(value).strip().casefold().replace(" ", "_")
        windows = {
            "r86400": timedelta(days=1),
            "past_24_hours": timedelta(days=1),
            "r604800": timedelta(days=7),
            "past_week": timedelta(days=7),
            "r2592000": timedelta(days=30),
            "past_month": timedelta(days=30),
        }
        delta = windows.get(normalized)
        if delta is None:
            return None
        return datetime.now(timezone.utc) - delta

    @staticmethod
    def _decode_html(value):
        text = html.unescape(str(value or ""))
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _company_to_board_token(name):
        token = re.sub(r"[^a-z0-9]+", "", str(name or "").casefold())
        return token or str(name or "").strip()

    @staticmethod
    def _parse_datetime(value):
        if not value:
            return None
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _dedupe_jobs(self, jobs):
        deduped = []
        seen = set()
        for job in jobs:
            key = (
                str(job.get("external_id") or job.get("id") or "").strip(),
                str(job.get("absolute_url") or "").strip().casefold(),
            )
            if not key[0] and not key[1]:
                deduped.append(job)
                continue
            if key in seen:
                continue
            seen.add(key)
            deduped.append(job)
        return deduped

    def _fetch_details_enabled(self):
        config = self._merged_config()
        value = config.get("fetch_details")
        if value in (False, "false", "0", 0):
            return False
        return True

    def _merged_config(self):
        crawl_config = getattr(self.source, "crawl_config", None) or {}
        return dict(crawl_config)

    def _crawl_config(self):
        return getattr(self.source, "crawl_config", None) or {}

    def _rolling_board_offset(self, total_tokens):
        rolling_state = self._crawl_config().get("rolling_state")
        if not isinstance(rolling_state, dict):
            rolling_state = {}
        try:
            offset = int(rolling_state.get("greenhouse_board_offset", 0))
        except (TypeError, ValueError):
            offset = 0
        return offset % total_tokens if total_tokens else 0

    def _save_rolling_board_offset(self, next_offset, total_tokens):
        if not getattr(self.source, "pk", None):
            return
        from apps.imports.models import JobSource

        crawl_config = dict(self._crawl_config())
        rolling_state = crawl_config.get("rolling_state")
        if not isinstance(rolling_state, dict):
            rolling_state = {}
        rolling_state["greenhouse_board_offset"] = next_offset % max(total_tokens, 1)
        rolling_state["greenhouse_board_total"] = total_tokens
        crawl_config["rolling_state"] = rolling_state
        JobSource.objects.filter(pk=self.source.pk).update(crawl_config=crawl_config)
        self.source.crawl_config = crawl_config

    def _mark_rate_limited(self, status_code):
        if not getattr(self.source, "pk", None):
            return
        from django.utils import timezone as django_timezone

        from apps.imports.models import JobSource

        cooldown_minutes = self._positive_int_config(
            "rate_limit_cooldown_minutes",
            default=self.DEFAULT_RATE_LIMIT_COOLDOWN_MINUTES,
        )
        crawl_config = dict(self._crawl_config())
        crawl_config["rate_limit_status_code"] = status_code
        crawl_config["rate_limited_until"] = (
            django_timezone.now() + timedelta(minutes=cooldown_minutes)
        ).isoformat()
        JobSource.objects.filter(pk=self.source.pk).update(crawl_config=crawl_config)
        self.source.crawl_config = crawl_config

    def _throttle_request(self):
        delay = self._positive_float_config("request_delay_seconds", default=0)
        if self._request_count and delay > 0:
            time.sleep(delay)

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

    @staticmethod
    def _coerce_values(value):
        if value in (None, "", [], {}):
            return []
        if isinstance(value, str):
            raw_values = value.replace("\n", ",").split(",")
        elif isinstance(value, (list, tuple, set)):
            raw_values = value
        else:
            raw_values = [value]

        values = []
        seen = set()
        for raw_value in raw_values:
            text = " ".join(str(raw_value or "").split()).strip()
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
            value = config.get(key)
            if isinstance(value, bool):
                return value
            normalized = str(value or "").strip().casefold()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default
