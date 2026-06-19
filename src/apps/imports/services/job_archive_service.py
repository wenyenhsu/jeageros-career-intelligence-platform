import calendar

from django.db import transaction
from django.utils import timezone

from apps.imports.models import JobArchiveRun, PipelineLog
from apps.jobs.models import JobPost

from .monitoring_service import MonitoringService


class JobArchiveService:
    MIN_MONTHS = 1
    MAX_MONTHS = 120

    @classmethod
    def archive_old_jobs(cls, age_months=3):
        age_months = cls._clean_age_months(age_months)
        now = timezone.now()
        cutoff_at = cls.subtract_months(now, age_months)
        jobs = list(
            JobPost.objects.select_related("company")
            .prefetch_related("skill_links__skill_set")
            .filter(created_at__lt=cutoff_at)
            .exclude(status=JobPost.StatusChoices.ARCHIVED)
            .order_by("created_at", "id")
        )
        payload = cls._build_payload(
            jobs=jobs,
            archived_at=now,
            cutoff_at=cutoff_at,
            age_months=age_months,
        )
        job_ids = [job.id for job in jobs]

        with transaction.atomic():
            archive_run = JobArchiveRun.objects.create(
                cutoff_at=cutoff_at,
                age_months=age_months,
                jobs_archived=len(job_ids),
                payload=payload,
                status=JobArchiveRun.StatusChoices.CREATED,
            )
            if job_ids:
                JobPost.objects.filter(id__in=job_ids).update(
                    status=JobPost.StatusChoices.ARCHIVED,
                    updated_at=now,
                )

        MonitoringService.log_event(
            step_name="job_archive",
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message=f"Archived {len(job_ids)} jobs older than {age_months} months.",
            service_name=__name__,
            metadata={
                "archive_run_id": archive_run.id,
                "age_months": age_months,
                "cutoff_at": cutoff_at.isoformat(),
                "jobs_archived": len(job_ids),
            },
        )
        return archive_run

    @classmethod
    def restore_archive(cls, archive_run):
        if archive_run.status == JobArchiveRun.StatusChoices.RESTORED:
            return {
                "archive_run": archive_run,
                "jobs_restored": archive_run.jobs_restored,
                "skipped_job_ids": (archive_run.payload or {}).get(
                    "skipped_job_ids",
                    [],
                ),
            }

        now = timezone.now()
        job_ids = [
            item.get("id")
            for item in (archive_run.payload or {}).get("jobs", [])
            if item.get("id")
        ]
        existing_ids = set(
            JobPost.objects.filter(
                id__in=job_ids,
                status=JobPost.StatusChoices.ARCHIVED,
            ).values_list("id", flat=True)
        )
        skipped_ids = [job_id for job_id in job_ids if job_id not in existing_ids]

        with transaction.atomic():
            restored_count = 0
            if existing_ids:
                restored_count = JobPost.objects.filter(id__in=existing_ids).update(
                    status=JobPost.StatusChoices.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            archive_run.jobs_restored = restored_count
            archive_run.restored_at = now
            archive_run.status = JobArchiveRun.StatusChoices.RESTORED
            archive_run.payload = {
                **(archive_run.payload or {}),
                "restored_at": now.isoformat(),
                "jobs_restored": restored_count,
                "skipped_job_ids": skipped_ids,
            }
            archive_run.save(
                update_fields=[
                    "jobs_restored",
                    "restored_at",
                    "status",
                    "payload",
                ]
            )

        MonitoringService.log_event(
            step_name="job_archive_restore",
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message=f"Restored {restored_count} archived jobs.",
            service_name=__name__,
            metadata={
                "archive_run_id": archive_run.id,
                "jobs_restored": restored_count,
                "skipped_job_ids": skipped_ids,
            },
        )
        return {
            "archive_run": archive_run,
            "jobs_restored": restored_count,
            "skipped_job_ids": skipped_ids,
        }

    @classmethod
    def subtract_months(cls, value, months):
        month = value.month - months
        year = value.year
        while month <= 0:
            month += 12
            year -= 1
        day = min(value.day, calendar.monthrange(year, month)[1])
        return value.replace(year=year, month=month, day=day)

    @classmethod
    def _clean_age_months(cls, age_months):
        try:
            age_months = int(age_months)
        except (TypeError, ValueError) as exc:
            raise ValueError("Archive age must be a whole number of months.") from exc
        if age_months < cls.MIN_MONTHS or age_months > cls.MAX_MONTHS:
            raise ValueError(
                f"Archive age must be between {cls.MIN_MONTHS} and {cls.MAX_MONTHS} months."
            )
        return age_months

    @classmethod
    def _build_payload(cls, jobs, archived_at, cutoff_at, age_months):
        return {
            "archive_version": 1,
            "archived_at": archived_at.isoformat(),
            "cutoff_at": cutoff_at.isoformat(),
            "age_months": age_months,
            "jobs": [cls._job_to_payload(job) for job in jobs],
        }

    @staticmethod
    def _job_to_payload(job):
        return {
            "id": job.id,
            "title": job.title,
            "company": {
                "id": job.company_id,
                "name": job.company.name if job.company_id else "",
            },
            "source_url": job.source_url,
            "external_id": job.external_id,
            "source_type": job.source_type,
            "status": job.status,
            "location": job.location,
            "remote_type": job.remote_type,
            "job_type": job.job_type,
            "employment_type": job.employment_type,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "description": job.description,
            "tags": job.tags,
            "last_synced_at": (
                job.last_synced_at.isoformat() if job.last_synced_at else None
            ),
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "skill_sets": [
                {
                    "id": link.skill_set_id,
                    "name": link.skill_set.name,
                    "score": link.score,
                    "source_type": link.source_type,
                    "metadata": link.extraction_metadata,
                }
                for link in job.skill_links.all()
            ],
        }
