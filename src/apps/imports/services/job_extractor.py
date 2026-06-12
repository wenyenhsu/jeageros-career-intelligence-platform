from dataclasses import dataclass, field
from typing import Any

from .source_detector import SourceDetector


@dataclass(frozen=True)
class ExtractedJob:
    title: str
    company_name: str
    source_url: str
    external_id: str = ""
    location: str = ""
    remote_type: str = ""
    employment_type: str = ""
    description: str = ""
    parser_type: str = SourceDetector.CAREER_SITE
    raw_data: dict[str, Any] = field(default_factory=dict)


class JobExtractor:
    parser_type = SourceDetector.CAREER_SITE

    def extract(self, payload):
        if isinstance(payload, dict):
            return dict(payload)
        if isinstance(payload, str):
            return {"url": payload}
        if isinstance(payload, ExtractedJob):
            return (
                dict(payload.raw_data) if payload.raw_data else dict(payload.__dict__)
            )
        raise TypeError(
            "JobExtractor payload must be a raw dict, URL string, or ExtractedJob."
        )

    def normalize(self, data):
        """Legacy compatibility shim. Use JobNormalizer for canonical payloads."""
        source_url = data.get("source_url") or data.get("url") or ""
        return ExtractedJob(
            title=data.get("title", ""),
            company_name=data.get("company_name") or data.get("company", ""),
            source_url=source_url,
            external_id=data.get("external_id", ""),
            location=data.get("location", ""),
            remote_type=data.get("remote_type", ""),
            employment_type=data.get("employment_type", ""),
            description=data.get("description", ""),
            parser_type=data.get("parser_type", self.parser_type),
            raw_data=dict(data),
        )
