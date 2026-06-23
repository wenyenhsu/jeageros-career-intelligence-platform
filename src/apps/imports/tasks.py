import logging

from celery import shared_task
from django.conf import settings

from .models import JobSource, PipelineLog
from .services import CrawlService, MonitoringService

logger = logging.getLogger(__name__)


@shared_task(name="apps.imports.tasks.crawl_all_sources")
def crawl_all_sources(crawl_run_id=None, source_ids=None):
    MonitoringService.log_event(
        step_name="celery_task",
        status=PipelineLog.StatusChoices.STARTED,
        message="crawl_all_sources task started.",
        service_name="apps.imports.tasks.crawl_all_sources",
        crawl_run_id=crawl_run_id,
        metadata={"source_ids": source_ids or []},
    )
    try:
        if source_ids:
            sources = JobSource.objects.filter(id__in=source_ids)
            summary = CrawlService.crawl_all_sources(
                sources,
                crawl_run_id=crawl_run_id,
            )
        else:
            summary = CrawlService.crawl_enabled_sources(crawl_run_id=crawl_run_id)
        logger.info(
            "Scheduled crawl summary: processed=%s skipped=%s created=%s updated=%s closed=%s errors=%s progress=%.2f%%",
            summary["sources_processed"],
            summary["sources_skipped"],
            summary["jobs_created"],
            summary["jobs_updated"],
            summary["jobs_closed"],
            summary["errors"],
            summary["progress_percentage"],
        )
        if summary.get("aborted"):
            MonitoringService.log_event(
                step_name="celery_task",
                status=PipelineLog.StatusChoices.FAILED,
                severity=PipelineLog.SeverityChoices.WARNING,
                message="crawl_all_sources task aborted.",
                service_name="apps.imports.tasks.crawl_all_sources",
                crawl_run_id=summary.get("crawl_run_id") or crawl_run_id,
                metadata=summary,
            )
        else:
            MonitoringService.log_success(
                step_name="celery_task",
                message="crawl_all_sources task finished.",
                service_name="apps.imports.tasks.crawl_all_sources",
                crawl_run_id=summary.get("crawl_run_id") or crawl_run_id,
                metadata=summary,
            )
            try:
                from apps.analytics.services.skill_demand_service import (
                    update_skill_demand,
                )

                demand_stats = update_skill_demand()
                summary["skill_demand_update"] = demand_stats
            except Exception as exc:
                logger.warning("Skill demand update after crawl failed: %s", exc)
            if settings.SKILL_EMBEDDING_SYNC_AFTER_CRAWL:
                try:
                    from apps.skills.tasks import schedule_skill_embedding_sync

                    embedding_result = schedule_skill_embedding_sync()
                    if embedding_result is not None:
                        summary["skill_embedding_sync"] = (
                            embedding_result
                            if isinstance(embedding_result, dict)
                            else {"task_id": getattr(embedding_result, "id", None)}
                        )
                except Exception as exc:
                    logger.warning("Skill embedding sync after crawl failed: %s", exc)
        return summary
    except Exception as exc:
        MonitoringService.log_failure(
            step_name="celery_task",
            message="crawl_all_sources task failed.",
            service_name="apps.imports.tasks.crawl_all_sources",
            crawl_run_id=crawl_run_id,
            error=exc,
        )
        raise


crawl_enabled_job_sources = crawl_all_sources
