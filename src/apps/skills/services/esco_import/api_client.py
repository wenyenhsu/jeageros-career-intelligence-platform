import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class EscoApiError(Exception):
    pass


class EscoApiClient:
    BASE_URL = "https://ec.europa.eu/esco/api"
    SKILLS_SCHEME = "http://data.europa.eu/esco/concept-scheme/skills"
    SKILLS_HIERARCHY_SCHEME = "http://data.europa.eu/esco/concept-scheme/skills-hierarchy"
    DEFAULT_LIMIT = 100
    MAX_RETRIES = 3

    def __init__(self, language: str = "en", timeout: int = 60):
        self.language = language
        self.timeout = timeout

    def iter_scheme_skills(self, scheme_uri: str, limit: int | None = None):
        page_limit = limit or self.DEFAULT_LIMIT
        offset = 0
        total = None

        while total is None or offset < total:
            payload = self._fetch_json(
                "resource/skill",
                {
                    "isInScheme": scheme_uri,
                    "language": self.language,
                    "offset": offset,
                    "limit": page_limit,
                },
            )
            total = payload.get("total", 0)
            embedded = payload.get("_embedded", {})
            items = [
                embedded[key]
                for key in embedded
                if key.startswith("http://data.europa.eu/esco/")
            ]
            if not items:
                break
            yield items
            offset += page_limit

    def fetch_skill(self, uri: str) -> dict:
        return self._fetch_json(
            "resource/skill",
            {"uri": uri, "language": self.language},
        )

    def _fetch_json(self, path: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}/{path}?{query}"
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code >= 500 and attempt < self.MAX_RETRIES:
                    time.sleep(attempt)
                    continue
                raise EscoApiError(f"ESCO API HTTP {exc.code} for {url}") from exc
            except urllib.error.URLError as exc:
                if attempt < self.MAX_RETRIES:
                    time.sleep(attempt)
                    continue
                raise EscoApiError(f"ESCO API request failed for {url}: {exc}") from exc

    @staticmethod
    def pick_english_label(label_map: dict | None) -> str:
        if not label_map:
            return ""
        for key in ("en", "en-us", "en-gb"):
            value = label_map.get(key)
            if value:
                return str(value).strip()
        for value in label_map.values():
            if value:
                return str(value).strip()
        return ""

    @staticmethod
    def pick_english_description(description_map: dict | None) -> str:
        if not description_map:
            return ""
        for key in ("en", "en-us", "en-gb"):
            entry = description_map.get(key)
            if isinstance(entry, dict):
                literal = entry.get("literal")
                if literal:
                    return str(literal).strip()
            elif entry:
                return str(entry).strip()
        for entry in description_map.values():
            if isinstance(entry, dict) and entry.get("literal"):
                return str(entry["literal"]).strip()
        return ""

    @staticmethod
    def pick_english_alt_labels(alt_map: dict | None) -> list[str]:
        if not alt_map:
            return []
        for key in ("en", "en-us", "en-gb"):
            values = alt_map.get(key)
            if isinstance(values, list):
                return [str(value).strip() for value in values if str(value).strip()]
        for values in alt_map.values():
            if isinstance(values, list):
                return [str(value).strip() for value in values if str(value).strip()]
        return []

    @staticmethod
    def link_uris(links: dict | None, keys: tuple[str, ...]) -> list[str]:
        if not links:
            return []
        uris = []
        for key in keys:
            for item in links.get(key, []) or []:
                uri = item.get("uri")
                if uri:
                    uris.append(uri)
        return uris
