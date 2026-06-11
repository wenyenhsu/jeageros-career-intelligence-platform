from django.db.models import Count
from django.utils import timezone

from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.jobs.models import JobPost


class DashboardService:
    recent_limit = 5

    def operational_summary(self):
        today = timezone.localdate()
        latest_crawl_run = CrawlRun.objects.first()
        recent_failures = PipelineLog.objects.filter(
            status=PipelineLog.StatusChoices.FAILED,
        )[: self.recent_limit]

        return {
            "kpis": self._kpis(today),
            "application_status_counts": self._application_status_counts(),
            "recent_jobs": self._recent_jobs(),
            "recent_applications": self._recent_applications(),
            "latest_crawl_run": latest_crawl_run,
            "source_counts": self._source_counts(),
            "pipeline": {
                "recent_failures": recent_failures,
                "recent_failure_count": len(recent_failures),
                "recent_logs": PipelineLog.objects.select_related(
                    "source",
                    "job",
                    "company",
                )[: self.recent_limit],
            },
        }

    def _kpis(self, today):
        return {
            "total_jobs": JobPost.objects.count(),
            "active_jobs": JobPost.objects.filter(
                status=JobPost.StatusChoices.ACTIVE,
            ).count(),
            "total_applications": Application.objects.count(),
            "applications_today": Application.objects.filter(
                applied_at__date=today,
            ).count(),
            "active_companies": Company.objects.filter(job_posts__isnull=False)
            .distinct()
            .count(),
            "enabled_sources": JobSource.objects.filter(enabled=True).count(),
        }

    def _application_status_counts(self):
        status_labels = dict(Application.Status.choices)
        rows = (
            Application.objects.values("status")
            .annotate(total=Count("id"))
            .order_by("status")
        )
        return [
            {
                "status": row["status"],
                "label": status_labels.get(row["status"], row["status"] or "Unknown"),
                "total": row["total"],
            }
            for row in rows
        ]

    def _recent_jobs(self):
        return JobPost.objects.select_related("company")[: self.recent_limit]

    def _recent_applications(self):
        return Application.objects.select_related(
            "job_post",
            "job_post__company",
            "user",
        )[: self.recent_limit]

    @staticmethod
    def _source_counts():
        enabled = JobSource.objects.filter(enabled=True).count()
        disabled = JobSource.objects.filter(enabled=False).count()
        return {
            "enabled": enabled,
            "disabled": disabled,
            "total": enabled + disabled,
        }
