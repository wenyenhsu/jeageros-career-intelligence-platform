import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceJobStatusSignal:
    key: str
    value: Any
    category: str

    def as_dict(self):
        return asdict(self)


class SourceJobStatusService:
    CLOSED_TRUE_KEYS = {
        "closed_by_source",
        "is_closed",
        "job_closed",
        "job_expired",
        "job_removed",
        "no_longer_accepting",
        "no_longer_accepting_applications",
        "no_longer_recruiting",
        "not_accepting_applications",
        "posting_removed",
        "source_confirms_closed",
        "source_reports_closed",
    }
    CLOSED_FALSE_KEYS = {
        "accepting_applications",
        "is_accepting_applications",
        "is_active",
        "posting_active",
    }
    CLOSED_POSTING_STATUS_KEYS = {
        "availability",
        "job_status",
        "posting_status",
        "status",
    }
    CLOSED_POSTING_STATUS_VALUES = {
        "closed",
        "expired",
        "inactive",
        "no longer accepting",
        "no longer accepting applications",
        "no longer recruiting",
        "not accepting",
        "not accepting applications",
        "posting removed",
        "removed",
    }
    CLOSED_LINK_STATUS_KEYS = {
        "job_url_status",
        "link_status",
        "source_url_status",
        "url_status",
    }
    CLOSED_LINK_STATUS_VALUES = {"410", "gone"}
    PROMOTABLE_RAW_KEYS = (
        CLOSED_TRUE_KEYS
        | CLOSED_FALSE_KEYS
        | (CLOSED_POSTING_STATUS_KEYS - {"availability", "status"})
        | CLOSED_LINK_STATUS_KEYS
    )

    @classmethod
    def closed_signal(cls, metadata):
        if not isinstance(metadata, dict):
            return None

        for key, value in metadata.items():
            normalized_key = cls.normalize_key(key)
            if normalized_key in cls.CLOSED_TRUE_KEYS and cls._is_true(value):
                return SourceJobStatusSignal(
                    key=normalized_key,
                    value=value,
                    category="boolean_true",
                )
            if normalized_key in cls.CLOSED_FALSE_KEYS and cls._is_false(value):
                return SourceJobStatusSignal(
                    key=normalized_key,
                    value=value,
                    category="boolean_false",
                )
            if normalized_key in cls.CLOSED_POSTING_STATUS_KEYS:
                normalized_value = cls.normalize_value(value)
                if normalized_value in cls.CLOSED_POSTING_STATUS_VALUES:
                    return SourceJobStatusSignal(
                        key=normalized_key,
                        value=value,
                        category="posting_status",
                    )
            if normalized_key in cls.CLOSED_LINK_STATUS_KEYS:
                normalized_value = cls.normalize_value(value)
                if normalized_value in cls.CLOSED_LINK_STATUS_VALUES:
                    return SourceJobStatusSignal(
                        key=normalized_key,
                        value=value,
                        category="link_status",
                    )

        return None

    @classmethod
    def indicates_closed(cls, metadata):
        return cls.closed_signal(metadata) is not None

    @classmethod
    def promote_explicit_raw_metadata(cls, raw, metadata):
        promoted = dict(metadata or {})
        if not isinstance(raw, dict):
            return promoted

        normalized_items = {cls.normalize_key(key): value for key, value in raw.items()}
        normalized_metadata_keys = {cls.normalize_key(key) for key in promoted}
        for key in sorted(cls.PROMOTABLE_RAW_KEYS):
            if key in normalized_items and key not in normalized_metadata_keys:
                promoted[key] = normalized_items[key]
        return promoted

    @staticmethod
    def normalize_key(value):
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
        text = re.sub(r"[^a-zA-Z0-9]+", "_", text)
        return text.strip("_").casefold()

    @staticmethod
    def normalize_value(value):
        text = re.sub(r"[_-]+", " ", str(value or "").strip().casefold())
        return " ".join(text.split())

    @staticmethod
    def _is_true(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value == 1
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes"}
        return False

    @staticmethod
    def _is_false(value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value == 0
        if isinstance(value, str):
            return value.strip().casefold() in {"0", "false", "no"}
        return False
