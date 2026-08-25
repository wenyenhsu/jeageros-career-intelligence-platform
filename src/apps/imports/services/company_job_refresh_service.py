from dataclasses import dataclass, field

from apps.imports.models import PipelineLog
from apps.jobs.models import JobPost

from .job_url_refresh_service import JobUrlRefreshService
from .monitoring_service import MonitoringService


@dataclass
class CompanyJobRefreshQueueResult:
    total_jobs: int = 0
    queued_jobs: int = 0
    skipped_without_url: int = 0
    skipped_unsupported_url: int = 0
    skipped_archived: int = 0
    failed_jobs: int = 0
    queued_job_ids: list[int] = field(default_factory=list)

    @property
    def skipped_jobs(self):
        return (
            self.skipped_without_url
            + self.skipped_unsupported_url
            + self.skipped_archived
        )

    def as_dict(self):
        return {
            "total_jobs": self.total_jobs,
            "queued_jobs": self.queued_jobs,
            "skipped_jobs": self.skipped_jobs,
            "skipped_without_url": self.skipped_without_url,
            "skipped_unsupported_url": self.skipped_unsupported_url,
            "skipped_archived": self.skipped_archived,
            "failed_jobs": self.failed_jobs,
            "queued_job_ids": list(self.queued_job_ids),
        }


class CompanyJobRefreshService:
    @classmethod
    def queue(cls, company):
        from apps.imports.tasks import refresh_job_from_url

        jobs = list(company.job_posts.only("id", "source_url", "status").order_by("id"))
        result = CompanyJobRefreshQueueResult(total_jobs=len(jobs))

        for job in jobs:
            if job.status == JobPost.StatusChoices.ARCHIVED:
                result.skipped_archived += 1
                continue
            if not (job.source_url or "").strip():
                result.skipped_without_url += 1
                continue
            if not JobUrlRefreshService.supports_refresh(job):
                result.skipped_unsupported_url += 1
                continue

            try:
                refresh_job_from_url.delay(job.id, force=True)
            except Exception as exc:
                result.failed_jobs += 1
                MonitoringService.log_failure(
                    step_name="company_job_refresh_queue_item",
                    message="Failed to queue a company job refresh task.",
                    service_name=cls.__name__,
                    job=job,
                    company=company,
                    error=exc,
                    metadata={"force": True},
                )
                continue

            result.queued_jobs += 1
            result.queued_job_ids.append(job.id)

        status = (
            PipelineLog.StatusChoices.FAILED
            if result.failed_jobs
            else PipelineLog.StatusChoices.SUCCESS
        )
        severity = (
            PipelineLog.SeverityChoices.WARNING
            if result.failed_jobs
            else PipelineLog.SeverityChoices.INFO
        )
        MonitoringService.log_event(
            step_name="company_job_refresh_queue",
            status=status,
            severity=severity,
            message="Company job refresh tasks queued.",
            service_name=cls.__name__,
            company=company,
            metadata=result.as_dict(),
        )
        return result
