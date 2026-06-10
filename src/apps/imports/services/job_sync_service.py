from django.db.models import Q
from django.utils import timezone

from apps.imports.models import PipelineLog
from apps.jobs.models import JobPost

from .company_upsert_service import CompanyUpsertService
from .job_extractor import ExtractedJob
from .monitoring_service import MonitoringService
from .sync_result import JobUpsertResult, SyncResult


class JobSyncService:
    @classmethod
    def upsert_job(cls, normalized_job_data):
        data = cls._normalize_job_data(normalized_job_data)
        cls._validate_job_data(data)

        company_result = CompanyUpsertService.upsert(
            data["company_name"],
            data.get("company_website") or data.get("website", ""),
        )
        job = cls._find_existing_job(
            external_id=data.get("external_id", ""),
            source_url=data.get("source_url", ""),
        )
        synced_at = timezone.now()
        fields = cls._job_fields(data, company_result.company, synced_at)

        if job is None:
            job = JobPost.objects.create(**fields)
            MonitoringService.log_success(
                step_name="job_upsert",
                message="Created job during sync.",
                service_name=cls.__name__,
                job=job,
                company=job.company,
                metadata={
                    "created": True,
                    "external_id": job.external_id,
                    "source_url": job.source_url,
                },
            )
            return JobUpsertResult(
                job=job,
                created=True,
            )

        changed_fields = []
        for field_name, value in fields.items():
            if getattr(job, field_name) != value:
                setattr(job, field_name, value)
                changed_fields.append(field_name)

        if changed_fields:
            job.save(update_fields=[*changed_fields, "updated_at"])

        MonitoringService.log_event(
            step_name="job_upsert",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Updated existing job during sync.",
            service_name=cls.__name__,
            job=job,
            company=job.company,
            metadata={
                "created": False,
                "external_id": job.external_id,
                "source_url": job.source_url,
                "updated_fields": changed_fields,
            },
        )
        return JobUpsertResult(job=job, created=False)

    @classmethod
    def sync_company(cls, company, normalized_jobs=None):
        if normalized_jobs is None:
            return SyncResult()

        jobs_created = 0
        jobs_updated = 0
        seen_job_ids = set()

        for job_data in normalized_jobs:
            data = cls._normalize_job_data(job_data)
            if not data.get("company_name"):
                data["company_name"] = company.name

            result = cls.upsert_job(data)
            if result.created:
                jobs_created += 1
            else:
                jobs_updated += 1
            if result.job.company_id == company.id:
                seen_job_ids.add(result.job.id)

        jobs_closed = cls._close_missing_jobs(company, seen_job_ids)

        return SyncResult(
            jobs_created=jobs_created,
            jobs_updated=jobs_updated,
            jobs_closed=jobs_closed,
        )

    @classmethod
    def _find_existing_job(cls, external_id="", source_url=""):
        filters = None
        if external_id:
            filters = Q(external_id=external_id)
        if source_url:
            source_url_filter = Q(source_url=source_url)
            filters = (
                source_url_filter if filters is None else filters | source_url_filter
            )
        if filters is None:
            return None
        return JobPost.objects.filter(filters).select_related("company").first()

    @classmethod
    def _close_missing_jobs(cls, company, seen_job_ids):
        queryset = (
            company.job_posts.filter(status=JobPost.StatusChoices.ACTIVE)
            .exclude(external_id="", source_url="")
            .exclude(id__in=seen_job_ids)
        )
        closed_count = 0
        synced_at = timezone.now()

        for job in queryset:
            job.status = JobPost.StatusChoices.CLOSED
            job.last_synced_at = synced_at
            job.save(update_fields=["status", "last_synced_at", "updated_at"])
            closed_count += 1
            MonitoringService.log_event(
                step_name="job_close_detection",
                status=PipelineLog.StatusChoices.SUCCESS,
                message="Marked missing job as closed.",
                service_name=cls.__name__,
                job=job,
                company=company,
                metadata={
                    "external_id": job.external_id,
                    "source_url": job.source_url,
                },
            )

        return closed_count

    @staticmethod
    def _job_fields(data, company, synced_at):
        return {
            "company": company,
            "title": data["title"],
            "source_url": data.get("source_url", ""),
            "external_id": data.get("external_id", ""),
            "source_type": JobPost.SourceType.URL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": data.get("location", ""),
            "employment_type": data.get("employment_type", ""),
            "description": data.get("description", ""),
            "last_synced_at": synced_at,
        }

    @staticmethod
    def _normalize_job_data(normalized_job_data):
        if isinstance(normalized_job_data, ExtractedJob):
            return {
                "title": normalized_job_data.title,
                "company_name": normalized_job_data.company_name,
                "source_url": normalized_job_data.source_url,
                "external_id": normalized_job_data.external_id,
                "location": normalized_job_data.location,
                "employment_type": normalized_job_data.employment_type,
                "description": normalized_job_data.description,
            }
        return dict(normalized_job_data or {})

    @staticmethod
    def _validate_job_data(data):
        if not (data.get("title") or "").strip():
            raise ValueError("title is required.")
        if not (data.get("company_name") or "").strip():
            raise ValueError("company_name is required.")
        if not (
            (data.get("external_id") or "").strip()
            or (data.get("source_url") or "").strip()
        ):
            raise ValueError("external_id or source_url is required.")
