import logging
import time

from django.db.models import Avg, Count

from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService

from .skill_analytics_service import SkillAnalyticsService

logger = logging.getLogger(__name__)


class CompanyAnalyticsService:
    slow_query_seconds = 0.25

    def __init__(self, skill_service=None):
        self.skill_service = skill_service or SkillAnalyticsService()

    def company_skill_breakdown(self, company_id=None, limit=10, filters=None):
        filters = self.skill_service.normalize_filters(filters)
        if company_id:
            filters = {**filters, "company_id": company_id}

        started = time.perf_counter()
        rows = list(
            self.skill_service.filtered_job_skill_links(filters)
            .values(
                "job_post__company_id",
                "job_post__company__name",
                "skill_set_id",
                "skill_set__name",
            )
            .annotate(
                count=Count("job_post_id", distinct=True),
                average_score=Avg("score"),
            )
            .order_by(
                "job_post__company__name",
                "-count",
                "-average_score",
                "skill_set__name",
            )
        )

        per_company_counts = {}
        result = []
        for row in rows:
            company_key = row["job_post__company_id"]
            per_company_counts.setdefault(company_key, 0)
            if per_company_counts[company_key] >= limit:
                continue
            per_company_counts[company_key] += 1
            result.append(
                {
                    "company_id": row["job_post__company_id"],
                    "company": row["job_post__company__name"],
                    "skillset_id": row["skill_set_id"],
                    "name": row["skill_set__name"],
                    "count": row["count"],
                    "average_score": round(float(row["average_score"] or 0), 2),
                }
            )

        self._log_query("company_skill_breakdown", started, filters, len(result))
        return result

    def skill_gap_analysis(self, company_id, limit=10, filters=None):
        return self.skill_service.skill_gap_analysis(
            company_id=company_id,
            limit=limit,
            filters=filters,
        )

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
