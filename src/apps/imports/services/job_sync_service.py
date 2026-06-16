from django.db.models import Q
from django.utils import timezone

from apps.imports.models import PipelineLog
from apps.jobs.models import JobPost

from .company_upsert_service import CompanyUpsertService
from .job_normalizer import CanonicalJobPayload
from .monitoring_service import MonitoringService
from .source_detector import SourceDetector
from .sync_result import JobUpsertResult, SyncResult


class JobSyncService:
    CANONICAL_KEYS = {
        "source",
        "source_url",
        "external_id",
        "company_name",
        "title",
        "job_type",
        "employment_type",
        "remote_type",
        "location",
        "description",
        "sections",
        "posted_at",
        "metadata",
    }

    @classmethod
    def upsert_job(cls, canonical_job_payload):
        data = cls._canonical_job_data(canonical_job_payload)
        cls._validate_job_data(data)

        company_result = CompanyUpsertService.upsert(
            data["company_name"],
            cls._company_website(data),
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
                canonical_job_payload=data,
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
        return JobUpsertResult(job=job, created=False, canonical_job_payload=data)

    @classmethod
    def sync_company(cls, company, canonical_jobs=None, source=None):
        if canonical_jobs is None:
            return SyncResult()

        jobs_created = 0
        jobs_updated = 0
        job_results = []
        seen_job_ids = set()
        source_scope = cls._source_scope(source)

        for job_data in canonical_jobs:
            data = cls._canonical_job_data(job_data)
            if not data.get("company_name"):
                data["company_name"] = company.name
            source_scope.update(cls._source_scope(data.get("source")))

            result = cls.upsert_job(data)
            if result.created:
                jobs_created += 1
            else:
                jobs_updated += 1
            job_results.append(result)
            if result.job.company_id == company.id:
                seen_job_ids.add(result.job.id)

        jobs_closed = cls._close_missing_jobs(company, seen_job_ids, source_scope)

        result = SyncResult(
            jobs_created=jobs_created,
            jobs_updated=jobs_updated,
            jobs_closed=jobs_closed,
            job_results=job_results,
        )
        MonitoringService.log_event(
            step_name="company_sync",
            status=PipelineLog.StatusChoices.SUCCESS,
            message="Company sync completed.",
            service_name=cls.__name__,
            company=company,
            metadata={
                **result.as_dict(),
                "source_scope": sorted(source_scope),
                "jobs_seen": len(seen_job_ids),
            },
        )
        return result

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
    def _close_missing_jobs(cls, company, seen_job_ids, source_scope=None):
        source_scope = source_scope or set()
        queryset = (
            company.job_posts.filter(status=JobPost.StatusChoices.ACTIVE)
            .exclude(external_id="", source_url="")
            .exclude(id__in=seen_job_ids)
        )
        closed_count = 0
        synced_at = timezone.now()

        for job in queryset:
            if source_scope and not cls._job_matches_source_scope(job, source_scope):
                continue
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
        job_type = JobPost.normalize_job_type(
            data.get("employment_type") or data.get("job_type") or ""
        )
        return {
            "company": company,
            "title": data["title"],
            "source_url": data.get("source_url") or "",
            "external_id": data.get("external_id") or "",
            "source_type": JobPost.SourceType.URL,
            "status": JobPost.StatusChoices.ACTIVE,
            "location": data.get("location") or "",
            "remote_type": data.get("remote_type") or "",
            "job_type": job_type,
            "employment_type": job_type,
            "description": data.get("description") or "",
            "last_synced_at": synced_at,
        }

    @classmethod
    def _canonical_job_data(cls, canonical_job_payload):
        if isinstance(canonical_job_payload, CanonicalJobPayload):
            return canonical_job_payload.validate().as_dict()
        if not isinstance(canonical_job_payload, dict):
            raise TypeError("sync requires a CanonicalJobPayload or canonical dict.")

        unexpected_keys = set(canonical_job_payload) - cls.CANONICAL_KEYS
        if unexpected_keys:
            raise ValueError(
                "sync requires canonical job payload fields only; unexpected "
                f"field(s): {', '.join(sorted(unexpected_keys))}"
            )

        data = {
            "source": canonical_job_payload.get("source"),
            "source_url": canonical_job_payload.get("source_url"),
            "external_id": canonical_job_payload.get("external_id"),
            "company_name": canonical_job_payload.get("company_name"),
            "title": canonical_job_payload.get("title"),
            "job_type": canonical_job_payload.get("job_type"),
            "employment_type": canonical_job_payload.get("employment_type"),
            "remote_type": canonical_job_payload.get("remote_type"),
            "location": canonical_job_payload.get("location"),
            "description": canonical_job_payload.get("description"),
            "sections": canonical_job_payload.get("sections") or {},
            "posted_at": canonical_job_payload.get("posted_at"),
            "metadata": canonical_job_payload.get("metadata") or {},
        }
        CanonicalJobPayload(**data).validate()
        return data

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

    @staticmethod
    def _company_website(data):
        metadata = (
            data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        )
        company_metadata = metadata.get("company")
        if isinstance(company_metadata, dict):
            return company_metadata.get("website", "") or ""
        return metadata.get("company_website", "") or metadata.get("website", "") or ""

    @classmethod
    def _source_scope(cls, source):
        normalized = cls._normalize_source(source)
        return {normalized} if normalized else set()

    @staticmethod
    def _normalize_source(source):
        if source is None:
            return ""
        if not isinstance(source, str):
            source = SourceDetector.detect_parser_type(source)
        return str(source).strip().casefold().replace("-", "_")

    @classmethod
    def _job_matches_source_scope(cls, job, source_scope):
        if not job.source_url:
            return False
        detected_source = SourceDetector.detect_parser_type(job.source_url)
        return cls._normalize_source(detected_source) in source_scope
