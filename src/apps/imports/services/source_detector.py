from urllib.parse import urlparse


class SourceDetector:
    LINKEDIN = "LINKEDIN"
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    CAREER_SITE = "CAREER_SITE"
    GENERIC_HTML = "GENERIC_HTML"

    SPECIFIC_PARSER_TYPES = {
        LINKEDIN,
        GREENHOUSE,
        LEVER,
    }
    GENERIC_PARSER_TYPES = {
        CAREER_SITE,
        GENERIC_HTML,
    }
    DOMAIN_PARSER_TYPES = {
        LINKEDIN: ("linkedin.com",),
        GREENHOUSE: ("boards.greenhouse.io",),
        LEVER: ("jobs.lever.co",),
    }

    @classmethod
    def detect(cls, source):
        return cls.detect_parser_type(source)

    @classmethod
    def detect_parser_type(cls, source):
        url = cls._source_url(source)
        detected_type = cls.detect_url(url)
        if detected_type in cls.SPECIFIC_PARSER_TYPES:
            return detected_type

        resource_type = cls._source_resource(source)
        if resource_type in cls.SPECIFIC_PARSER_TYPES:
            return resource_type
        if resource_type in cls.GENERIC_PARSER_TYPES:
            return cls.CAREER_SITE
        if detected_type:
            return detected_type

        return cls.CAREER_SITE

    @classmethod
    def detect_url(cls, url):
        host = cls._host(url)
        if not host:
            return None

        for parser_type, domains in cls.DOMAIN_PARSER_TYPES.items():
            if any(cls._matches_domain(host, domain) for domain in domains):
                return parser_type

        return cls.CAREER_SITE

    @staticmethod
    def _source_url(source):
        if source is None:
            return ""
        if isinstance(source, str):
            return source
        return getattr(source, "base_url", "") or getattr(source, "url", "") or ""

    @staticmethod
    def _source_resource(source):
        if source is None or isinstance(source, str):
            return ""
        return (
            getattr(source, "resource", "") or getattr(source, "source_type", "") or ""
        )

    @classmethod
    def _host(cls, url):
        url = (url or "").strip()
        if not url:
            return ""
        if "://" not in url:
            url = f"https://{url}"

        parsed = urlparse(url)
        host = parsed.netloc.lower().split("@")[-1].split(":")[0].rstrip(".")
        if host.startswith("www."):
            return host[4:]
        return host

    @staticmethod
    def _matches_domain(host, domain):
        return host == domain or host.endswith(f".{domain}")
