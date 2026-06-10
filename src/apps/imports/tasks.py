import logging

from celery import shared_task

from .models import PipelineLog
from .services import CrawlService, MonitoringService

logger = logging.getLogger(__name__)


@shared_task(name="apps.imports.tasks.crawl_all_sources")
def crawl_all_sources(crawl_run_id=None):
    MonitoringService.log_event(
        step_name="celery_task",
        status=PipelineLog.StatusChoices.STARTED,
        message="crawl_all_sources task started.",
        service_name="apps.imports.tasks.crawl_all_sources",
        crawl_run_id=crawl_run_id,
    )
    try:
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
        MonitoringService.log_success(
            step_name="celery_task",
            message="crawl_all_sources task finished.",
            service_name="apps.imports.tasks.crawl_all_sources",
            crawl_run_id=summary.get("crawl_run_id") or crawl_run_id,
            metadata=summary,
        )
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
