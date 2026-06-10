import logging
import time

from django.db.models import Avg, Count

from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService

from .skill_analytics_service import SkillAnalyticsService

logger = logging.getLogger(__name__)


class JobAnalyticsService:
    slow_query_seconds = 0.25
    allowed_category_fields = {
        "employment_type": "job_post__employment_type",
        "source_type": "job_post__source_type",
        "remote_type": "job_post__remote_type",
        "location": "job_post__location",
    }

    def __init__(self, skill_service=None):
        self.skill_service = skill_service or SkillAnalyticsService()

    def top_skills_by_job_category(
        self,
        category_field="employment_type",
        limit=10,
        filters=None,
    ):
        filters = self.skill_service.normalize_filters(filters)
        started = time.perf_counter()
        field_name = self.allowed_category_fields.get(
            category_field,
            self.allowed_category_fields["employment_type"],
        )
        rows = list(
            self.skill_service.filtered_job_skill_links(filters)
            .values(field_name, "skill_set_id", "skill_set__name")
            .annotate(
                count=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
            )
            .order_by(field_name, "-count", "-average_score", "skill_set__name")
        )

        per_category_counts = {}
        result = []
        for row in rows:
            category = row[field_name] or "Unspecified"
            per_category_counts.setdefault(category, 0)
            if per_category_counts[category] >= limit:
                continue
            per_category_counts[category] += 1
            result.append(
                {
                    "category_field": category_field,
                    "category": category,
                    "skillset_id": row["skill_set_id"],
                    "name": row["skill_set__name"],
                    "count": row["count"],
                    "average_score": round(float(row["average_score"] or 0), 2),
                }
            )

        self._log_query("top_skills_by_job_category", started, filters, len(result))
        return result

    def _log_query(self, name, started, filters, result_size):
        duration = time.perf_counter() - started
        log_method = logger.warning if duration >= self.slow_query_seconds else logger.info
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
