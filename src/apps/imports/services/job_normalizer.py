import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from .source_detector import SourceDetector


@dataclass(frozen=True)
class CanonicalJobPayload:
    source: str | None
    source_url: str | None
    external_id: str | None
    company_name: str | None
    title: str | None
    job_type: str | None
    employment_type: str | None
    remote_type: str | None
    location: str | None
    description: str | None
    sections: dict[str, str | None] = field(default_factory=dict)
    posted_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return asdict(self)

    def get(self, key, default=None):
        return self.as_dict().get(key, default)

    def validate(self):
        missing = []
        if not self.title:
            missing.append("title")
        if not self.company_name:
            missing.append("company_name")
        if not (self.source_url or self.external_id):
            missing.append("source_url_or_external_id")
        if missing:
            raise ValueError(
                "Canonical job payload missing required field(s): " + ", ".join(missing)
            )
        return self


class JobNormalizer:
    EMPTY_VALUES = {
        "",
        "-",
        "--",
        "—",
        "n/a",
        "na",
        "none",
        "null",
        "not applicable",
        "not specified",
        "unknown",
        "undefined",
    }
    JOB_TYPE_ALIASES = {
        "full time": "FULL_TIME",
        "full-time": "FULL_TIME",
        "fulltime": "FULL_TIME",
        "full_time": "FULL_TIME",
        "permanent": "FULL_TIME",
        "part time": "PART_TIME",
        "part-time": "PART_TIME",
        "parttime": "PART_TIME",
        "part_time": "PART_TIME",
        "intern": "INTERNSHIP",
        "internship": "INTERNSHIP",
        "co op": "INTERNSHIP",
        "co-op": "INTERNSHIP",
        "contract": "CONTRACT",
        "contractor": "CONTRACT",
        "temporary": "TEMPORARY",
        "temp": "TEMPORARY",
    }
    SECTION_KEYS = {
        "about": ("about", "about_role", "aboutRole"),
        "responsibilities": (
            "responsibilities",
            "what_you_will_do",
            "whatYouWillDo",
        ),
        "requirements": ("requirements", "qualifications", "required_skills"),
        "minimum_qualifications": (
            "minimum_qualifications",
            "minimumQualifications",
            "minimum_qualification",
        ),
        "preferred_qualifications": (
            "preferred_qualifications",
            "preferredQualifications",
            "preferred_qualification",
        ),
    }

    FIELD_ALIASES = {
        "source_url": (
            "source_url",
            "url",
            "jobUrl",
            "job_url",
            "absolute_url",
            "hostedUrl",
            "hosted_url",
            "apply_url",
            "jobPostingUrl",
            "link",
        ),
        "external_id": (
            "external_id",
            "id",
            "job_id",
            "jobId",
            "jobPostingId",
            "gh_jid",
            "lever_id",
        ),
        "company_name": (
            "company_name",
            "company",
            "companyName",
            "organization",
            "employer",
            "employerName",
            "employer_name",
        ),
        "title": (
            "title",
            "jobTitle",
            "job_title",
            "position",
            "positionTitle",
            "name",
            "text",
        ),
        "job_type": ("job_type", "jobType", "employmentType", "type"),
        "employment_type": (
            "employment_type",
            "employmentType",
            "commitment",
            "job_type",
            "jobType",
            "type",
        ),
        "remote_type": (
            "remote_type",
            "remoteType",
            "workplaceType",
            "workplace_type",
            "workplace",
            "remote",
        ),
        "location": (
            "location",
            "formattedLocation",
            "formatted_location",
            "workplaceLocation",
            "workplace_location",
            "locations",
        ),
        "description": (
            "description",
            "descriptionPlain",
            "description_plain",
            "jobDescription",
            "job_description",
            "content",
            "body",
        ),
        "posted_at": (
            "posted_at",
            "postedAt",
            "datePosted",
            "created_at",
            "published_at",
            "first_published",
        ),
    }

    @classmethod
    def normalize(cls, raw_payload, source=None, validate=True):
        raw = cls._coerce_raw_payload(raw_payload)
        source_type = cls._normalize_source(
            cls._first_value(raw, ("source", "parser_type")) or source
        )
        sections = cls._normalize_sections(raw)
        description = cls._clean_text(
            cls._first_value(raw, cls.FIELD_ALIASES["description"])
        )
        if description is None:
            description = cls._description_from_sections(sections)
        title = cls._clean_text(cls._first_value(raw, cls.FIELD_ALIASES["title"]))

        job_type = cls.normalize_job_type(
            cls._first_value(raw, cls.FIELD_ALIASES["job_type"])
            or cls._category_value(raw, "commitment")
        )
        if job_type is None:
            job_type = cls._infer_job_type(
                raw=raw,
                title=title,
                description=description,
                sections=sections,
                source=source,
            )
        employment_type = cls.normalize_job_type(
            cls._first_value(raw, cls.FIELD_ALIASES["employment_type"])
            or cls._category_value(raw, "commitment")
            or job_type
        )

        payload = CanonicalJobPayload(
            source=source_type,
            source_url=cls._clean_text(
                cls._first_value(raw, cls.FIELD_ALIASES["source_url"])
            ),
            external_id=cls._clean_text(
                cls._first_value(raw, cls.FIELD_ALIASES["external_id"])
            ),
            company_name=cls._company_name(raw, source),
            title=title,
            job_type=job_type,
            employment_type=employment_type,
            remote_type=cls.normalize_location(
                cls._first_value(raw, cls.FIELD_ALIASES["remote_type"])
            ),
            location=cls.normalize_location(
                cls._first_value(raw, cls.FIELD_ALIASES["location"])
                or cls._category_value(raw, "location")
            ),
            description=description,
            sections=sections,
            posted_at=cls._normalize_date(
                cls._first_value(raw, cls.FIELD_ALIASES["posted_at"])
            ),
            metadata=cls._metadata(raw, source_type),
        )
        return payload.validate() if validate else payload

    @classmethod
    def normalize_many(cls, raw_payloads, source=None, validate=True):
        if raw_payloads is None:
            return []
        if isinstance(raw_payloads, (dict, CanonicalJobPayload)):
            raw_payloads = [raw_payloads]
        return [
            cls.normalize(raw_payload, source=source, validate=validate)
            for raw_payload in raw_payloads
        ]

    @classmethod
    def normalize_job_type(cls, value):
        text = cls._clean_text(value)
        if text is None:
            return None
        key = text.casefold().replace("_", " ").replace("/", " ").replace(".", " ")
        key = " ".join(key.split())
        return cls.JOB_TYPE_ALIASES.get(
            key, text.upper().replace(" ", "_").replace("-", "_")
        )

    @classmethod
    def _infer_job_type(cls, raw, title, description, sections, source):
        configured_default = cls._default_job_type_from_source(source)
        searchable_text = " ".join(
            str(part or "")
            for part in (
                title,
                description,
                *(sections or {}).values(),
            )
        ).casefold()

        inference_patterns = (
            (r"\b(intern|internship|co[\s-]?op)\b", "INTERNSHIP"),
            (r"\b(part[\s-]?time)\b", "PART_TIME"),
            (r"\b(contract|contractor)\b", "CONTRACT"),
            (r"\b(temp|temporary)\b", "TEMPORARY"),
            (r"\b(full[\s-]?time|fulltime)\b", "FULL_TIME"),
        )
        for pattern, normalized in inference_patterns:
            if re.search(pattern, searchable_text):
                return normalized

        raw_metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        metadata_default = cls.normalize_job_type(
            raw_metadata.get("default_job_type")
            or raw_metadata.get("default_employment_type")
        )
        return metadata_default or configured_default

    @classmethod
    def _default_job_type_from_source(cls, source):
        for config in cls._source_configs(source):
            configured = cls.normalize_job_type(
                config.get("default_job_type")
                or config.get("default_employment_type")
            )
            if configured:
                return configured
        return None

    @classmethod
    def normalize_location(cls, value):
        text = cls._clean_text(cls._coerce_location_value(value))
        if text is None:
            return None

        key = text.casefold().replace("_", " ")
        key = " ".join(key.split())
        if key in {"remote", "work from home", "wfh", "home based", "home-based"}:
            return "Remote"
        if "work from home" in key or key.startswith("remote"):
            return "Remote"
        if key in {"hybrid", "hybrid remote"}:
            return "Hybrid"
        if key in {"onsite", "on site", "on-site", "in office", "office"}:
            return "On-site"
        return text

    @classmethod
    def _normalize_sections(cls, raw):
        configured = (
            raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
        )
        sections = {
            key: cls._clean_text(value)
            for key, value in configured.items()
            if cls._clean_text(value) is not None
        }
        for canonical_key, aliases in cls.SECTION_KEYS.items():
            value = cls._clean_text(cls._first_value(raw, aliases))
            if value is not None:
                sections[canonical_key] = value
        return sections

    @classmethod
    def _description_from_sections(cls, sections):
        values = [value for value in sections.values() if value]
        return "\n\n".join(values) if values else None

    @classmethod
    def _company_name(cls, raw, source):
        company_name = cls._clean_text(
            cls._first_value(raw, cls.FIELD_ALIASES["company_name"])
        )
        if company_name:
            return company_name

        for config in cls._source_configs(source):
            for key in ("company_name", "company", "employer"):
                company_name = cls._clean_text(config.get(key))
                if company_name:
                    return company_name
            companies = config.get("target_companies") or config.get("companies")
            if isinstance(companies, list) and companies:
                company_name = cls._clean_text(companies[0])
                if company_name:
                    return company_name

        return cls._clean_text(getattr(source, "name", None))

    @classmethod
    def _metadata(cls, raw, source_type):
        metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
        metadata = dict(metadata)
        metadata.setdefault("source", source_type)
        metadata.setdefault("raw_payload", raw)
        return metadata

    @classmethod
    def _first_value(cls, raw, keys):
        for key in keys:
            if key in raw:
                value = raw[key]
                if cls._clean_text(value) is not None or isinstance(
                    value, (dict, list)
                ):
                    return value
        return None

    @staticmethod
    def _category_value(raw, key):
        categories = raw.get("categories")
        if isinstance(categories, dict):
            return categories.get(key)
        return None

    @classmethod
    def _coerce_raw_payload(cls, raw_payload):
        if isinstance(raw_payload, CanonicalJobPayload):
            return raw_payload.as_dict()
        if hasattr(raw_payload, "raw_data") and getattr(raw_payload, "raw_data"):
            return dict(raw_payload.raw_data)
        if hasattr(raw_payload, "as_dict"):
            return dict(raw_payload.as_dict())
        if isinstance(raw_payload, dict):
            return dict(raw_payload)
        raise TypeError("JobNormalizer expects a raw dict or canonical payload.")

    @classmethod
    def _coerce_location_value(cls, value):
        if isinstance(value, dict):
            for key in ("name", "location", "city", "display_name"):
                if key in value:
                    return value[key]
            return None
        if isinstance(value, list):
            cleaned = [
                cls._clean_text(cls._coerce_location_value(item)) for item in value
            ]
            cleaned = [item for item in cleaned if item]
            return ", ".join(cleaned) if cleaned else None
        if isinstance(value, bool):
            return "Remote" if value else None
        return value

    @classmethod
    def _normalize_date(cls, value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        value = cls._clean_text(value)
        if value is None:
            return None
        return value

    @classmethod
    def _clean_text(cls, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        text = " ".join(str(value).split()).strip()
        if text.casefold() in cls.EMPTY_VALUES:
            return None
        return text

    @staticmethod
    def _source_configs(source):
        if source is None or isinstance(source, str):
            return []
        return [
            getattr(source, "filter_config", None) or {},
            getattr(source, "crawl_config", None) or {},
        ]

    @classmethod
    def _normalize_source(cls, source):
        if source is None:
            return None
        if not isinstance(source, str):
            source = SourceDetector.detect_parser_type(source)
        source = cls._clean_text(source)
        if source is None:
            return None
        return source.casefold().replace("-", "_")
