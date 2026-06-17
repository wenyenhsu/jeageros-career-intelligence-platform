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
            "skill_snapshot": self._skill_snapshot(),
            "skill_coverage": self._skill_coverage(),
            "job_type_breakdown": self._job_type_breakdown(),
            "job_status_breakdown": self._job_status_breakdown(),
            "source_breakdown": self._source_breakdown(),
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
        total_skill_links = JobPostSkill.objects.count()
        average_score = JobPostSkill.objects.aggregate(score=Avg("score"))["score"]
        return {
            "total_jobs": total_jobs,
            "jobs_with_skills": jobs_with_skills,
            "jobs_without_skills": max(total_jobs - jobs_with_skills, 0),
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
    def _job_status_breakdown():
        return DashboardService._breakdown(
            JobPost.objects.values("status"),
            value_key="status",
            label_map=dict(JobPost.StatusChoices.choices),
            limit=5,
        )

    @staticmethod
    def _source_breakdown(limit=5):
        return DashboardService._breakdown(
            JobPost.objects.exclude(source_type="").values("source_type"),
            value_key="source_type",
            label_map=dict(JobPost.SourceType.choices),
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
