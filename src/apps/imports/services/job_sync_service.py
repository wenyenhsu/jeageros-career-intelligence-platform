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
    # Auto close detection is disabled; status is manual-only for now.
    # Restore the three categories below when re-enabling automatic closed/active sync.
    # CLOSED_METADATA_BOOLEAN_KEYS = {
    #     "closed_by_source",
    #     "is_closed",
    #     "job_closed",
    #     "job_removed",
    #     "job_expired",
    #     "job_url_invalid",
    #     "link_invalid",
    #     "no_longer_accepting",
    #     "no_longer_accepting_applications",
    #     "no_longer_recruiting",
    #     "not_accepting_applications",
    #     "posting_removed",
    #     "source_confirms_closed",
    #     "source_reports_closed",
    #     "source_url_invalid",
    #     "url_invalid",
    # }
    # CLOSED_POSTING_STATUS_KEYS = {
    #     "availability",
    #     "job_status",
    #     "posting_status",
    #     "status",
    # }
    # CLOSED_POSTING_STATUS_VALUES = {
    #     "closed",
    #     "expired",
    #     "inactive",
    #     "no longer accepting",
    #     "no longer accepting applications",
    #     "no longer recruiting",
    #     "not accepting",
    #     "not accepting applications",
    #     "posting removed",
    #     "removed",
    # }
    # CLOSED_LINK_STATUS_KEYS = {
    #     "job_url_status",
    #     "link_status",
    #     "source_url_status",
    #     "url_status",
    # }
    # CLOSED_LINK_STATUS_VALUES = {
    #     "404",
    #     "410",
    #     "gone",
    #     "invalid",
    #     "link invalid",
    #     "not found",
    #     "removed",
    #     "url invalid",
    # }
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

        previous_status = job.status
        fields = cls._preserve_existing_values(fields, job)
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
        closed = (
            previous_status != JobPost.StatusChoices.CLOSED
            and job.status == JobPost.StatusChoices.CLOSED
        )
        return JobUpsertResult(
            job=job,
            created=False,
            canonical_job_payload=data,
            closed=closed,
        )

    @classmethod
    def sync_company(cls, company, canonical_jobs=None, source=None):
        if canonical_jobs is None:
            return SyncResult()

        jobs_created = 0
        jobs_updated = 0
        jobs_closed = 0
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
                if result.closed:
                    jobs_closed += 1
            job_results.append(result)
            if result.job.company_id == company.id:
                seen_job_ids.add(result.job.id)

        jobs_closed += cls._record_missing_jobs_without_closing(
            company,
            seen_job_ids,
            source_scope,
        )

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
    def _record_missing_jobs_without_closing(
        cls,
        company,
        seen_job_ids,
        source_scope=None,
    ):
        source_scope = source_scope or set()
        queryset = (
            company.job_posts.filter(status=JobPost.StatusChoices.ACTIVE)
            .exclude(external_id="", source_url="")
            .exclude(id__in=seen_job_ids)
        )

        for job in queryset:
            if source_scope and not cls._job_matches_source_scope(job, source_scope):
                continue
            MonitoringService.log_event(
                step_name="job_close_detection",
                status=PipelineLog.StatusChoices.INFO,
                message=(
                    "Missing job left active; close requires an explicit source signal."
                ),
                service_name=cls.__name__,
                job=job,
                company=company,
                metadata={
                    "external_id": job.external_id,
                    "source_url": job.source_url,
                    "reason": "missing_from_latest_crawl",
                    "close_policy": "explicit_source_signal_required",
                },
            )

        return 0

    @classmethod
    def _job_fields(cls, data, company, synced_at):
        job_type = JobPost.normalize_job_type(
            data.get("employment_type") or data.get("job_type") or ""
        )
        return {
            "company": company,
            "title": data["title"],
            "source_url": data.get("source_url") or "",
            "external_id": data.get("external_id") or "",
            "source_type": JobPost.SourceType.URL,
            "status": cls._job_status_from_data(data),
            "location": data.get("location") or "",
            "remote_type": data.get("remote_type") or "",
            "job_type": job_type,
            "employment_type": job_type,
            "description": data.get("description") or "",
            "last_synced_at": synced_at,
        }

    @staticmethod
    def _preserve_existing_values(fields, job):
        preserved_fields = {
            "source_url",
            "external_id",
            "location",
            "remote_type",
            "job_type",
            "employment_type",
            "description",
        }
        fields = dict(fields)
        for field_name in preserved_fields:
            incoming_value = fields.get(field_name)
            existing_value = getattr(job, field_name, "")
            if incoming_value in (None, "") and existing_value not in (None, ""):
                fields[field_name] = existing_value
        # Manual status only until auto close detection is restored.
        fields["status"] = job.status
        return fields

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

    @classmethod
    def _job_status_from_data(cls, data):
        # New jobs default to ACTIVE; existing jobs keep manual status during sync.
        return JobPost.StatusChoices.ACTIVE

    # @classmethod
    # def _metadata_indicates_closed(cls, metadata):
    #     if not isinstance(metadata, dict):
    #         return False
    #
    #     for key, value in metadata.items():
    #         normalized_key = cls._normalize_metadata_key(key)
    #         if normalized_key in cls.CLOSED_METADATA_BOOLEAN_KEYS and cls._is_truthy(
    #             value
    #         ):
    #             return True
    #         if normalized_key in cls.CLOSED_POSTING_STATUS_KEYS:
    #             normalized_value = cls._normalize_metadata_value(value)
    #             if normalized_value in cls.CLOSED_POSTING_STATUS_VALUES:
    #                 return True
    #         if normalized_key in cls.CLOSED_LINK_STATUS_KEYS:
    #             normalized_value = cls._normalize_metadata_value(value)
    #             if normalized_value in cls.CLOSED_LINK_STATUS_VALUES:
    #                 return True
    #
    #     return False
    #
    # @staticmethod
    # def _normalize_metadata_key(value):
    #     return str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    #
    # @staticmethod
    # def _normalize_metadata_value(value):
    #     return " ".join(str(value).strip().casefold().replace("_", " ").split())
    #
    # @staticmethod
    # def _is_truthy(value):
    #     if isinstance(value, bool):
    #         return value
    #     if isinstance(value, str):
    #         return value.strip().casefold() in {"1", "true", "yes", "y"}
    #     return bool(value)

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
