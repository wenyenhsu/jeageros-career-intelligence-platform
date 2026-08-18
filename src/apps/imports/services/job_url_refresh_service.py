from dataclasses import dataclass, field

from django.conf import settings

from apps.imports.models import PipelineLog
from apps.jobs.models import JobPost

from .job_normalizer import CanonicalJobPayload, JobNormalizer
from .job_sync_service import JobSyncService
from .monitoring_service import MonitoringService
from .parser_registry import ParserRegistry
from .skill_pipeline_service import SkillPipelineService


class JobUrlRefreshError(ValueError):
    pass


@dataclass
class JobUrlRefreshResult:
    job: object
    fetched: bool = False
    skipped: bool = False
    skills_attached: int = 0
    error: str = ""
    updated_fields: list = field(default_factory=list)

    def as_dict(self):
        return {
            "job_id": getattr(self.job, "id", None),
            "fetched": self.fetched,
            "skipped": self.skipped,
            "skills_attached": self.skills_attached,
            "error": self.error,
            "updated_fields": list(self.updated_fields),
            "success": not self.error,
        }


class JobUrlRefreshService:
    UNSUPPORTED_MESSAGE = "This URL type does not support single-job fetch yet."
    PRESERVED_FIELDS = (
        "title",
        "location",
        "remote_type",
        "job_type",
        "employment_type",
        "description",
        "starts_on",
        "ends_on",
        "start_precision",
        "end_precision",
        "season",
        "duration_weeks",
        "schedule_raw",
    )

    @classmethod
    def needs_refresh(cls, job):
        if not cls._source_url(job):
            return False
        has_location = not cls._is_blank(getattr(job, "location", ""))
        has_skills = job.skill_links.exists()
        return not (has_location and has_skills)

    @classmethod
    def refresh(cls, job):
        if job is None or not getattr(job, "pk", None):
            raise JobUrlRefreshError("A saved job is required.")

        MonitoringService.log_event(
            step_name="job_url_refresh",
            status=PipelineLog.StatusChoices.STARTED,
            message="Refreshing job details from source URL.",
            service_name=cls.__name__,
            job=job,
            company=job.company,
            metadata={"source_url": cls._source_url(job)},
        )

        if not cls.needs_refresh(job):
            MonitoringService.log_success(
                step_name="job_url_refresh",
                message="Skipped URL refresh; location and skills are already present.",
                service_name=cls.__name__,
                job=job,
                company=job.company,
            )
            return JobUrlRefreshResult(job=job, skipped=True)

        try:
            payload = cls._fetch_canonical_payload(job)
            merged = cls._merge_existing(job, payload)
            upsert_result = JobSyncService.upsert_job(merged, job=job)
            job = upsert_result.job
            skills_attached = cls._run_skill_pipeline(job, merged)
        except Exception as exc:
            MonitoringService.log_failure(
                step_name="job_url_refresh",
                message="Failed to refresh job details from source URL.",
                service_name=cls.__name__,
                job=job,
                company=getattr(job, "company", None),
                error=exc,
                metadata={"source_url": cls._source_url(job)},
            )
            return JobUrlRefreshResult(job=job, error=str(exc))

        MonitoringService.log_success(
            step_name="job_url_refresh",
            message="Refreshed job details from source URL.",
            service_name=cls.__name__,
            job=job,
            company=job.company,
            metadata={
                "source_url": job.source_url,
                "skills_attached": skills_attached,
            },
        )
        return JobUrlRefreshResult(
            job=job,
            fetched=True,
            skills_attached=skills_attached,
        )

    @classmethod
    def _fetch_canonical_payload(cls, job):
        url = cls._source_url(job)
        parser = ParserRegistry.get_parser_for_url(url)
        raw_jobs = parser.extract_single_job(url)
        if not raw_jobs:
            raise JobUrlRefreshError(cls.UNSUPPORTED_MESSAGE)
        payload = JobNormalizer.normalize(raw_jobs[0], source=url)
        return payload.as_dict() if isinstance(payload, CanonicalJobPayload) else payload

    @classmethod
    def _merge_existing(cls, job, payload):
        data = dict(payload or {})
        data["company_name"] = job.company.name
        data["source_url"] = job.source_url or data.get("source_url") or ""
        if job.external_id:
            data["external_id"] = job.external_id
        for field_name in cls.PRESERVED_FIELDS:
            existing = getattr(job, field_name, None)
            if cls._is_blank(existing):
                continue
            if field_name in {"starts_on", "ends_on", "duration_weeks"}:
                data[field_name] = existing.isoformat() if hasattr(existing, "isoformat") else existing
            else:
                data[field_name] = existing
        if job.job_type or job.employment_type:
            job_type = job.job_type or job.employment_type
            data["job_type"] = job_type
            data["employment_type"] = job_type
        return data

    @classmethod
    def _run_skill_pipeline(cls, job, canonical_job_payload):
        job = (
            JobPost.objects.select_related("company")
            .prefetch_related("skill_links")
            .get(pk=job.pk)
        )
        if job.skill_links.exists():
            return 0
        if cls._is_blank(job.description) and cls._is_blank(
            (canonical_job_payload or {}).get("description")
        ):
            return 0
        if not settings.CRAWL_SKILL_PIPELINE_ENABLED:
            return 0
        result = SkillPipelineService().process_job_post(
            job_post=job,
            canonical_job_payload=canonical_job_payload,
            auto_create=settings.CRAWL_SKILL_AUTO_CREATE,
        )
        if not result.success:
            raise JobUrlRefreshError(result.error or "Skill pipeline failed.")
        return result.attached_count

    @staticmethod
    def _source_url(job):
        return (getattr(job, "source_url", "") or "").strip()

    @staticmethod
    def _is_blank(value):
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        return False
