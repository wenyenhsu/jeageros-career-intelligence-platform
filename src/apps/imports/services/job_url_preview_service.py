from dataclasses import dataclass
import re

from apps.jobs.models import JobPost

from .job_normalizer import CanonicalJobPayload, JobNormalizer
from .job_url_refresh_service import JobUrlRefreshService
from .parser_registry import ParserRegistry


@dataclass
class JobUrlPreviewResult:
    ok: bool = False
    company: str = ""
    title: str = ""
    location: str = ""
    job_type: str = ""
    description: str = ""
    existing_job_id: int | None = None
    error: str = ""

    def as_dict(self):
        return {
            "ok": self.ok,
            "company": self.company,
            "title": self.title,
            "location": self.location,
            "job_type": self.job_type,
            "description": self.description,
            "existing_job_id": self.existing_job_id,
            "error": self.error,
        }


class JobUrlPreviewService:
    EMPTY_URL_MESSAGE = "Enter a job URL."
    DRIVE_URL_MESSAGE = (
        "Use the Google Drive folder field for cover letter and resume."
    )
    FETCH_FAILED_MESSAGE = "Could not read this job URL."

    @classmethod
    def preview(cls, url):
        url = str(url or "").strip()
        if not url:
            return JobUrlPreviewResult(error=cls.EMPTY_URL_MESSAGE)
        if JobUrlRefreshService._is_drive_url(url):
            return JobUrlPreviewResult(error=cls.DRIVE_URL_MESSAGE)

        existing = (
            JobPost.objects.filter(source_url=url).select_related("company").first()
        )
        payload = cls._fetch_payload(url)
        if payload is None and existing is None:
            return JobUrlPreviewResult(error=cls.FETCH_FAILED_MESSAGE)

        company = cls._first_text(
            payload.get("company_name") if payload else "",
            getattr(getattr(existing, "company", None), "name", ""),
        )
        title = cls._first_text(
            payload.get("title") if payload else "",
            getattr(existing, "title", ""),
        )
        location = cls._first_text(
            payload.get("location") if payload else "",
            getattr(existing, "location", ""),
        )
        description = cls._first_multiline(
            payload.get("description") if payload else "",
            getattr(existing, "description", ""),
        )
        job_type = cls._normalize_job_type(
            (payload or {}).get("employment_type")
            or (payload or {}).get("job_type")
            or getattr(existing, "job_type", "")
            or getattr(existing, "employment_type", ""),
            title=title,
        )
        if not title and not company:
            return JobUrlPreviewResult(error=cls.FETCH_FAILED_MESSAGE)
        return JobUrlPreviewResult(
            ok=True,
            company=company,
            title=title,
            location=location,
            job_type=job_type,
            description=description,
            existing_job_id=existing.pk if existing else None,
        )

    @classmethod
    def _fetch_payload(cls, url):
        parser = ParserRegistry.get_parser_for_url(url)
        try:
            raw_jobs = parser.extract_single_job(url) or []
        except Exception:
            return None
        if not raw_jobs:
            return None
        try:
            payload = JobNormalizer.normalize(raw_jobs[0], source=url, validate=False)
        except Exception:
            return None
        if isinstance(payload, CanonicalJobPayload):
            return payload.as_dict()
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _normalize_job_type(cls, value, title=""):
        if re.search(r"\bintern(?:ship)?s?\b", str(title or ""), flags=re.I):
            return "Internship"
        normalized = JobPost.normalize_job_type(value)
        known = {choice for choice, _label in JobPost.JOB_TYPE_CHOICES}
        return normalized if normalized in known else ""

    @staticmethod
    def _first_text(*values):
        for value in values:
            text = " ".join(str(value or "").split()).strip()
            if text:
                return text
        return ""

    @staticmethod
    def _first_multiline(*values):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""
