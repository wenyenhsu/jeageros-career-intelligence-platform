import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class JobIdentity:
    canonical_source_url: str = ""
    source_key: str = ""
    normalized_external_id: str = ""


class JobIdentityService:
    TRACKING_QUERY_KEYS = {
        "lipi",
        "originalsubdomain",
        "ref",
        "refid",
        "trackingid",
        "trk",
        "trkinfo",
    }
    GREENHOUSE_HOSTS = {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "my.greenhouse.io",
    }
    LEVER_HOST_MAP = {
        "jobs.lever.co": "jobs.lever.co",
        "jobs.eu.lever.co": "jobs.eu.lever.co",
        "api.lever.co": "jobs.lever.co",
        "api.eu.lever.co": "jobs.eu.lever.co",
    }

    @classmethod
    def build(
        cls,
        *,
        source_url="",
        external_id="",
        source="",
        company_name="",
    ):
        return JobIdentity(
            canonical_source_url=cls.canonicalize_url(source_url),
            source_key=cls.source_key(
                source_url=source_url,
                source=source,
                company_name=company_name,
            ),
            normalized_external_id=cls.normalize_external_id(external_id),
        )

    @classmethod
    def canonicalize_url(cls, value):
        raw_url = str(value or "").strip()
        if not raw_url:
            return ""
        if "://" not in raw_url:
            raw_url = f"https://{raw_url}"

        parsed = urlsplit(raw_url)
        host = cls._normalized_host(parsed.hostname)
        if not host:
            return ""
        try:
            port = parsed.port
        except ValueError:
            return ""
        if port and port not in {80, 443}:
            host = f"{host}:{port}"

        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        path = path.rstrip("/") or "/"
        query_pairs = cls._identity_query_pairs(parsed.query)

        if cls._is_linkedin_host(host):
            host = "linkedin.com"
            job_id = cls._linkedin_job_id(path)
            if job_id:
                path = f"/jobs/view/{job_id}"
                query_pairs = []
        elif host in cls.GREENHOUSE_HOSTS:
            greenhouse_parts = cls._greenhouse_path_parts(path)
            if greenhouse_parts:
                board_token, job_id = greenhouse_parts
                host = "greenhouse.io"
                path = f"/{board_token}/jobs/{job_id}"
                query_pairs = []
        elif host in cls.LEVER_HOST_MAP:
            lever_parts = cls._lever_path_parts(host, path)
            if lever_parts:
                site, posting_id = lever_parts
                host = cls.LEVER_HOST_MAP[host]
                path = f"/{site}/{posting_id}"
                query_pairs = []

        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunsplit(("https", host, path, query, ""))

    @classmethod
    def source_key(cls, *, source_url="", source="", company_name=""):
        raw_url = str(source_url or "").strip()
        if raw_url and "://" not in raw_url:
            raw_url = f"https://{raw_url}"
        parsed = urlsplit(raw_url) if raw_url else None
        host = cls._normalized_host(parsed.hostname) if parsed else ""
        path = parsed.path if parsed else ""
        company_key = cls._slug(company_name)
        source_name = cls._slug(source)

        if cls._is_linkedin_host(host) or source_name == "linkedin":
            return "linkedin"
        if host in cls.GREENHOUSE_HOSTS:
            greenhouse_parts = cls._greenhouse_path_parts(path)
            board_token = greenhouse_parts[0] if greenhouse_parts else company_key
            return cls._namespaced("greenhouse", board_token or host)
        if host in cls.LEVER_HOST_MAP:
            lever_parts = cls._lever_path_parts(host, path)
            tenant = (
                lever_parts[0]
                if lever_parts
                else cls._lever_site_from_path(host, path)
            )
            tenant = tenant or company_key
            return cls._namespaced("lever", tenant or host)
        if host.endswith("handshake.com"):
            return "handshake"

        query_keys = (
            {
                key.casefold(): value
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            }
            if parsed
            else {}
        )
        if "gh_jid" in query_keys or source_name == "greenhouse":
            return cls._namespaced("greenhouse", company_key or host)

        existing_namespace = str(source or "").strip().casefold()
        if host:
            namespace = existing_namespace.partition(":")[0]
            if namespace in {"greenhouse", "lever"}:
                return cls._namespaced(namespace, company_key or host)
            return cls._namespaced(host, company_key)
        if ":" in existing_namespace:
            return existing_namespace
        if source_name:
            return cls._namespaced(source_name, company_key)
        if company_key:
            return cls._namespaced("company", company_key)
        return ""

    @staticmethod
    def normalize_external_id(value):
        return str(value or "").strip().casefold()

    @classmethod
    def _lever_path_parts(cls, host, path):
        segments = [segment for segment in str(path or "").split("/") if segment]
        if host in {"api.lever.co", "api.eu.lever.co"}:
            if len(segments) < 4 or segments[:2] != ["v0", "postings"]:
                return None
            return segments[2], segments[3]
        if len(segments) < 2:
            return None
        return segments[0], segments[1]

    @staticmethod
    def _lever_site_from_path(host, path):
        segments = [segment for segment in str(path or "").split("/") if segment]
        if host in {"api.lever.co", "api.eu.lever.co"}:
            if len(segments) >= 3 and segments[:2] == ["v0", "postings"]:
                return segments[2]
            return ""
        return segments[0] if segments else ""

    @classmethod
    def _identity_query_pairs(cls, query):
        pairs = []
        for key, value in parse_qsl(query or "", keep_blank_values=True):
            normalized_key = key.strip().casefold()
            if normalized_key.startswith("utm_"):
                continue
            if normalized_key in cls.TRACKING_QUERY_KEYS:
                continue
            pairs.append((key, value))
        return pairs

    @staticmethod
    def _linkedin_job_id(path):
        match = re.search(r"/jobs/view/([^/]+)", path or "", flags=re.IGNORECASE)
        if not match:
            return ""
        id_match = re.search(r"(\d+)$", match.group(1))
        return id_match.group(1) if id_match else ""

    @staticmethod
    def _greenhouse_path_parts(path):
        match = re.search(
            r"^/([^/]+)/jobs/(\d+)(?:/|$)",
            path or "",
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return match.group(1).casefold(), match.group(2)

    @staticmethod
    def _first_path_segment(path):
        return next((part.casefold() for part in (path or "").split("/") if part), "")

    @staticmethod
    def _normalized_host(host):
        normalized = str(host or "").strip().casefold().rstrip(".")
        return normalized[4:] if normalized.startswith("www.") else normalized

    @staticmethod
    def _is_linkedin_host(host):
        hostname = str(host or "").split(":", 1)[0]
        return hostname == "linkedin.com" or hostname.endswith(".linkedin.com")

    @staticmethod
    def _slug(value):
        text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold())
        return text.strip("-")

    @staticmethod
    def _namespaced(namespace, value):
        suffix = str(value or "").strip().casefold()
        return f"{namespace}:{suffix}" if suffix else str(namespace or "").casefold()
