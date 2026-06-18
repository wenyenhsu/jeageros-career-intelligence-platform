from django.db.models import Avg, Count
from django.utils import timezone

from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill


class DashboardService:
    recent_limit = 5

    def operational_summary(self):
        today = timezone.localdate()
        latest_crawl_run = CrawlRun.objects.first()
        source_counts = self._source_counts()
        recent_failures = PipelineLog.objects.filter(
            status=PipelineLog.StatusChoices.FAILED,
        )[: self.recent_limit]

        return {
            "kpis": self._kpis(today),
            "application_status_counts": self._application_status_counts(),
            "recent_jobs": self._recent_jobs(),
            "recent_applications": self._recent_applications(),
            "latest_crawl_run": latest_crawl_run,
            "source_counts": source_counts,
            "crawl_history": self._crawl_history(source_counts=source_counts),
            "skill_snapshot": self._skill_snapshot(),
            "skill_coverage": self._skill_coverage(),
            "job_type_breakdown": self._job_type_breakdown(),
            "location_snapshot": self._location_snapshot(),
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

    @staticmethod
    def _crawl_history(source_counts, limit=5):
        history = []
        for crawl_run in CrawlRun.objects.all()[:limit]:
            enabled_at_run = crawl_run.total_sources or source_counts["enabled"]
            history.append(
                {
                    "run": crawl_run,
                    "time": crawl_run.finished_at or crawl_run.started_at,
                    "enabled_sources": enabled_at_run,
                    "total_sources": source_counts["total"],
                    "processed_sources": crawl_run.processed_sources,
                    "jobs_created": crawl_run.jobs_created,
                    "jobs_updated": crawl_run.jobs_updated,
                    "jobs_closed": crawl_run.jobs_closed,
                    "errors": crawl_run.errors,
                    "status": crawl_run.status,
                    "status_label": crawl_run.get_status_display(),
                }
            )
        return history

    @staticmethod
    def _skill_snapshot(limit=6):
        rows = list(
            JobPostSkill.objects.select_related("skill_set")
            .values("skill_set__name")
            .annotate(
                total=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
            )
            .order_by("-total", "-average_score", "skill_set__name")[:limit]
        )
        top_total = rows[0]["total"] if rows else 0
        return [
            {
                "name": row["skill_set__name"],
                "total": row["total"],
                "average_score": round(float(row["average_score"] or 0), 1),
                "share": DashboardService._percentage(row["total"], top_total),
            }
            for row in rows
        ]

    @staticmethod
    def _skill_coverage():
        total_jobs = JobPost.objects.count()
        jobs_with_skills = (
            JobPostSkill.objects.values("job_post_id").distinct().count()
        )
        active_jobs = JobPost.objects.filter(
            status=JobPost.StatusChoices.ACTIVE,
        ).count()
        closed_jobs = JobPost.objects.filter(
            status=JobPost.StatusChoices.CLOSED,
        ).count()
        total_skill_links = JobPostSkill.objects.count()
        average_score = JobPostSkill.objects.aggregate(score=Avg("score"))["score"]
        return {
            "total_jobs": total_jobs,
            "jobs_with_skills": jobs_with_skills,
            "jobs_without_skills": max(total_jobs - jobs_with_skills, 0),
            "active_jobs": active_jobs,
            "closed_jobs": closed_jobs,
            "active_percent": DashboardService._percentage(active_jobs, total_jobs),
            "closed_percent": DashboardService._percentage(closed_jobs, total_jobs),
            "coverage_percent": DashboardService._percentage(
                jobs_with_skills,
                total_jobs,
            ),
            "total_skill_links": total_skill_links,
            "average_score": round(float(average_score or 0), 1),
        }

    @staticmethod
    def _job_type_breakdown(limit=5):
        return DashboardService._breakdown(
            JobPost.objects.exclude(job_type="").values("job_type"),
            value_key="job_type",
            label_map=JobPost.JOB_TYPE_LABELS,
            limit=limit,
        )

    @staticmethod
    def _location_snapshot(limit=5):
        return DashboardService._breakdown(
            JobPost.objects.exclude(location="").values("location"),
            value_key="location",
            limit=limit,
        )

    @staticmethod
    def _breakdown(queryset, value_key, label_map=None, limit=5):
        rows = list(
            queryset.annotate(total=Count("id")).order_by("-total", value_key)[:limit]
        )
        total = sum(row["total"] for row in rows)
        label_map = label_map or {}
        return [
            {
                "value": row[value_key] or "Unspecified",
                "label": label_map.get(row[value_key], row[value_key] or "Unspecified"),
                "total": row["total"],
                "share": DashboardService._percentage(row["total"], total),
            }
            for row in rows
        ]

    @staticmethod
    def _percentage(part, total):
        return round((part / total) * 100, 1) if total else 0
