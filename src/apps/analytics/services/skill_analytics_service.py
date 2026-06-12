import logging
import time
from datetime import timedelta

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.applications.models import Application
from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService
from apps.jobs.models import JobPost
from apps.skills.models import ApplicationSkill, JobPostSkill

logger = logging.getLogger(__name__)


class SkillAnalyticsService:
    slow_query_seconds = 0.25

    def top_skills(self, limit=10, filters=None):
        filters = self.normalize_filters(filters)
        started = time.perf_counter()
        rows = list(
            self.filtered_job_skill_links(filters)
            .values("skill_set_id", "skill_set__name")
            .annotate(
                count=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
                max_score=Max("score"),
            )
            .order_by("-count", "-average_score", "skill_set__name")[:limit]
        )
        result = [
            {
                "skillset_id": row["skill_set_id"],
                "name": row["skill_set__name"],
                "count": row["count"],
                "average_score": self._round_score(row["average_score"]),
                "max_score": row["max_score"],
            }
            for row in rows
        ]
        self._log_query("top_skills", started, filters, len(result))
        return result

    def skill_trends_by_month(self, limit=5, filters=None, skillset_ids=None):
        filters = self.normalize_filters(filters)
        started = time.perf_counter()
        qs = self.filtered_job_skill_links(filters)
        if skillset_ids is None:
            skillset_ids = [
                row["skillset_id"]
                for row in self.top_skills(limit=limit, filters=filters)
            ]
        if not skillset_ids:
            self._log_query("skill_trends_by_month", started, filters, 0)
            return []

        rows = list(
            qs.filter(skill_set_id__in=skillset_ids)
            .annotate(period=TruncMonth(self._date_field(filters["date_basis"])))
            .values("period", "skill_set_id", "skill_set__name")
            .annotate(
                count=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
            )
            .order_by("period", "skill_set__name")
        )
        result = [
            {
                "period": row["period"].strftime("%Y-%m") if row["period"] else "",
                "skillset_id": row["skill_set_id"],
                "name": row["skill_set__name"],
                "count": row["count"],
                "average_score": self._round_score(row["average_score"]),
            }
            for row in rows
        ]
        self._log_query("skill_trends_by_month", started, filters, len(result))
        return result

    def skill_coverage_summary(self, filters=None):
        filters = self.normalize_filters(filters)
        started = time.perf_counter()
        job_queryset = self.filtered_jobs(filters)
        link_queryset = self.filtered_job_skill_links(filters)
        total_jobs = job_queryset.count()
        jobs_with_scored_skills = link_queryset.values("job_post_id").distinct().count()
        score_summary = link_queryset.aggregate(
            total_skill_links=Count("id"),
            average_score=Avg("score"),
        )
        high_confidence_links = link_queryset.filter(score__gte=80).count()
        coverage_percent = (
            round((jobs_with_scored_skills / total_jobs) * 100, 2) if total_jobs else 0
        )
        result = {
            "total_jobs": total_jobs,
            "jobs_with_scored_skills": jobs_with_scored_skills,
            "coverage_percent": coverage_percent,
            "total_skill_links": score_summary["total_skill_links"] or 0,
            "average_score": self._round_score(score_summary["average_score"]),
            "high_confidence_links": high_confidence_links,
        }
        self._log_query("skill_coverage_summary", started, filters, 1)
        return result

    def skill_gap_analysis(self, company_id, limit=10, filters=None):
        filters = self.normalize_filters(filters)
        started = time.perf_counter()
        company_filters = {**filters, "company_id": company_id}
        target_rows = self.top_skills(limit=1000, filters=company_filters)
        target_counts = {row["skillset_id"]: row["count"] for row in target_rows}

        benchmark_rows = list(
            self.filtered_job_skill_links(filters)
            .exclude(job_post__company_id=company_id)
            .values("skill_set_id", "skill_set__name")
            .annotate(
                benchmark_count=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
            )
            .order_by("-benchmark_count", "-average_score", "skill_set__name")
        )
        gaps = []
        for row in benchmark_rows:
            target_count = target_counts.get(row["skill_set_id"], 0)
            gap = row["benchmark_count"] - target_count
            if gap <= 0:
                continue
            gaps.append(
                {
                    "skillset_id": row["skill_set_id"],
                    "name": row["skill_set__name"],
                    "target_count": target_count,
                    "benchmark_count": row["benchmark_count"],
                    "gap": gap,
                    "average_score": self._round_score(row["average_score"]),
                }
            )
        result = sorted(
            gaps,
            key=lambda item: (-item["gap"], -item["benchmark_count"], item["name"]),
        )[:limit]
        self._log_query("skill_gap_analysis", started, company_filters, len(result))
        return result

    def application_skill_comparison(self, application_id):
        started = time.perf_counter()
        application = Application.objects.select_related("job_post").get(
            id=application_id
        )
        job_skills = {
            link.skill_set_id: link.skill_set.name
            for link in JobPostSkill.objects.select_related("skill_set").filter(
                job_post=application.job_post
            )
        }
        application_skills = {
            link.skill_set_id: link.skill_set.name
            for link in ApplicationSkill.objects.select_related("skill_set").filter(
                application=application
            )
        }

        matched_ids = sorted(set(job_skills) & set(application_skills))
        missing_ids = sorted(set(job_skills) - set(application_skills))
        application_only_ids = sorted(set(application_skills) - set(job_skills))
        result = {
            "application_id": application.id,
            "job_post_id": application.job_post_id,
            "matched": [
                {"skillset_id": skill_id, "name": job_skills[skill_id]}
                for skill_id in matched_ids
            ],
            "missing_from_application": [
                {"skillset_id": skill_id, "name": job_skills[skill_id]}
                for skill_id in missing_ids
            ],
            "application_only": [
                {"skillset_id": skill_id, "name": application_skills[skill_id]}
                for skill_id in application_only_ids
            ],
        }
        self._log_query(
            "application_skill_comparison",
            started,
            {"application_id": application_id},
            len(result["matched"]) + len(result["missing_from_application"]),
        )
        return result

    def filtered_job_skill_links(self, filters=None):
        filters = self.normalize_filters(filters)
        qs = JobPostSkill.objects.select_related(
            "skill_set",
            "job_post",
            "job_post__company",
        )

        date_field = self._date_field(filters["date_basis"])
        if filters.get("start_date"):
            qs = qs.filter(**{f"{date_field}__date__gte": filters["start_date"]})
        if filters.get("end_date"):
            qs = qs.filter(**{f"{date_field}__date__lte": filters["end_date"]})
        if filters.get("company_id"):
            qs = qs.filter(job_post__company_id=filters["company_id"])
        if filters.get("company"):
            qs = qs.filter(job_post__company__name__icontains=filters["company"])
        if filters.get("source_type"):
            qs = qs.filter(job_post__source_type=filters["source_type"])
        if filters.get("canonical_source"):
            source_value = filters["canonical_source"]
            qs = qs.filter(
                Q(extraction_metadata__source__iexact=source_value)
                | Q(job_post__source_type__iexact=source_value)
            )
        if filters.get("location"):
            qs = qs.filter(job_post__location__icontains=filters["location"])
        if filters.get("employment_type"):
            qs = qs.filter(job_post__employment_type__iexact=filters["employment_type"])
        if filters.get("remote_type"):
            qs = qs.filter(job_post__remote_type__iexact=filters["remote_type"])
        if filters.get("score_min") is not None:
            qs = qs.filter(score__gte=filters["score_min"])
        if filters.get("score_max") is not None:
            qs = qs.filter(score__lte=filters["score_max"])
        return qs

    def filtered_jobs(self, filters=None):
        filters = self.normalize_filters(filters)
        qs = JobPost.objects.select_related("company").prefetch_related(
            "skill_sets",
            "skill_sets__keywords",
        )

        date_field = self._job_date_field(filters["date_basis"])
        if filters.get("start_date") and date_field:
            qs = qs.filter(**{f"{date_field}__date__gte": filters["start_date"]})
        if filters.get("end_date") and date_field:
            qs = qs.filter(**{f"{date_field}__date__lte": filters["end_date"]})
        if filters.get("company_id"):
            qs = qs.filter(company_id=filters["company_id"])
        if filters.get("company"):
            qs = qs.filter(company__name__icontains=filters["company"])
        if filters.get("source_type"):
            qs = qs.filter(source_type=filters["source_type"])
        if filters.get("canonical_source"):
            source_value = filters["canonical_source"]
            qs = qs.filter(
                Q(skill_links__extraction_metadata__source__iexact=source_value)
                | Q(source_type__iexact=source_value)
            )
        if filters.get("location"):
            qs = qs.filter(location__icontains=filters["location"])
        if filters.get("employment_type"):
            qs = qs.filter(employment_type__iexact=filters["employment_type"])
        if filters.get("remote_type"):
            qs = qs.filter(remote_type__iexact=filters["remote_type"])
        return qs.distinct()

    @classmethod
    def normalize_filters(cls, filters=None):
        filters = filters or {}
        getter = filters.get
        employment_type = cls._clean(
            getter("employment_type") or getter("job_type") or getter("category")
        )
        normalized = {
            "company_id": cls._to_int(getter("company_id")),
            "company": cls._clean(getter("company")),
            "source_type": cls._clean(getter("source_type")),
            "canonical_source": cls._clean(
                getter("canonical_source") or getter("source") or getter("resource")
            ),
            "location": cls._clean(getter("location")),
            "employment_type": JobPost.normalize_job_type(employment_type),
            "remote_type": cls._clean(getter("remote_type")),
            "start_date": cls._parse_date(
                getter("start_date") or getter("from") or getter("date_from")
            ),
            "end_date": cls._parse_date(
                getter("end_date") or getter("to") or getter("date_to")
            ),
            "date_basis": cls._normalize_date_basis(getter("date_basis")),
            "score_min": cls._to_int(getter("score_min") or getter("min_score")),
            "score_max": cls._to_int(getter("score_max") or getter("max_score")),
        }
        days = cls._to_int(getter("days") or getter("window_days"))
        if days and not normalized["start_date"]:
            normalized["start_date"] = timezone.localdate() - timedelta(days=days)
        return normalized

    @classmethod
    def _normalize_date_basis(cls, value):
        value = cls._clean(value).casefold().replace("-", "_")
        aliases = {
            "": "attachment",
            "attachment": "attachment",
            "skill": "attachment",
            "skill_attachment": "attachment",
            "job": "job_created",
            "job_created": "job_created",
            "created": "job_created",
            "sync": "last_synced",
            "synced": "last_synced",
            "last_synced": "last_synced",
        }
        return aliases.get(value, "attachment")

    @staticmethod
    def _date_field(date_basis):
        fields = {
            "attachment": "created_at",
            "job_created": "job_post__created_at",
            "last_synced": "job_post__last_synced_at",
        }
        return fields.get(date_basis, "created_at")

    @staticmethod
    def _job_date_field(date_basis):
        fields = {
            "job_created": "created_at",
            "last_synced": "last_synced_at",
        }
        return fields.get(date_basis)

    @staticmethod
    def _clean(value):
        return str(value).strip() if value not in (None, "") else ""

    @staticmethod
    def _to_int(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_date(value):
        if not value:
            return None
        return parse_date(str(value))

    @staticmethod
    def _round_score(value):
        return round(float(value or 0), 2)

    def _log_query(self, name, started, filters, result_size):
        duration = time.perf_counter() - started
        log_method = (
            logger.warning if duration >= self.slow_query_seconds else logger.info
        )
        log_method(
            "Analytics query %s completed in %.4fs filters=%s result_size=%s",
            name,
            duration,
            filters,
            result_size,
        )
        MonitoringService.log_event(
            step_name="analytics_query",
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=(
                PipelineLog.SeverityChoices.WARNING
                if duration >= self.slow_query_seconds
                else PipelineLog.SeverityChoices.INFO
            ),
            message=f"Analytics query {name} completed.",
            service_name=self.__class__.__name__,
            metadata={
                "query": name,
                "filters": filters,
                "result_size": result_size,
            },
            duration_ms=int(duration * 1000),
        )
