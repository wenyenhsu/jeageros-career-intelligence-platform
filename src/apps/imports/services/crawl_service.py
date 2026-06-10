import logging
import time
from collections import defaultdict

from django.utils import timezone

from apps.imports.models import CrawlRun, JobSource, PipelineLog

from .company_upsert_service import CompanyUpsertService
from .job_extractor import ExtractedJob
from .job_sync_service import JobSyncService
from .monitoring_service import MonitoringService
from .parser_registry import ParserRegistry
from .source_detector import SourceDetector

logger = logging.getLogger(__name__)


class CrawlService:
    @classmethod
    def crawl_enabled_sources(cls, progress_callback=None, crawl_run_id=None):
        summary = cls.crawl_all_sources(
            JobSource.objects.filter(enabled=True),
            progress_callback=progress_callback,
            crawl_run_id=crawl_run_id,
        )
        summary["sources_skipped"] += JobSource.objects.filter(enabled=False).count()
        return summary

    @classmethod
    def crawl_all_sources(cls, sources=None, progress_callback=None, crawl_run_id=None):
        sources = list(sources if sources is not None else JobSource.objects.all())
        crawl_run = cls._start_crawl_run(
            total_sources=len(sources),
            crawl_run_id=crawl_run_id,
        )
        MonitoringService.log_event(
            step_name="crawl_run",
            status=PipelineLog.StatusChoices.STARTED,
            message="Crawl run started.",
            service_name=cls.__name__,
            crawl_run=crawl_run,
            metadata={"total_sources": len(sources)},
        )
        summary = cls._empty_run_summary(crawl_run)

        if not sources:
            cls._finish_crawl_run(crawl_run, summary)
            summary["progress"] = crawl_run.as_progress_dict()
            cls._emit_progress(crawl_run, progress_callback)
            return summary

        for source in sources:
            cls._set_current_source(crawl_run, source)
            source_summary = cls.crawl_source(source, crawl_run=crawl_run)
            summary["sources"].append(source_summary)
            if source_summary["status"] == "skipped":
                summary["sources_skipped"] += 1
            elif source_summary["status"] == "failed":
                summary["success"] = False
                summary["failures"].append(source_summary)
                summary["errors"] += 1
            else:
                summary["sources_processed"] += 1
                summary["jobs_created"] += source_summary["jobs_created"]
                summary["jobs_updated"] += source_summary["jobs_updated"]
                summary["jobs_closed"] += source_summary["jobs_closed"]

            cls._update_crawl_run_progress(crawl_run, source_summary, summary)
            summary["progress"] = crawl_run.as_progress_dict()
            cls._emit_progress(crawl_run, progress_callback)

        cls._finish_crawl_run(crawl_run, summary)
        summary["progress"] = crawl_run.as_progress_dict()
        cls._emit_progress(crawl_run, progress_callback)
        return summary

    @classmethod
    def crawl_source(cls, source, crawl_run=None):
        source_summary = cls._empty_source_summary(source)
        if not source.enabled:
            logger.info("Skipping disabled job source: %s", source.name)
            MonitoringService.log_event(
                step_name="source_crawl",
                status=PipelineLog.StatusChoices.SKIPPED,
                message="Job source is disabled.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
            )
            source_summary["status"] = "skipped"
            return source_summary

        started = time.perf_counter()
        MonitoringService.log_event(
            step_name="source_crawl",
            status=PipelineLog.StatusChoices.STARTED,
            message=f"Started crawling {source.name}.",
            service_name=cls.__name__,
            crawl_run=crawl_run,
            source=source,
        )
        try:
            parser_type = SourceDetector.detect_parser_type(source)
            source_summary["parser_type"] = parser_type
            logger.info("Crawling job source %s (%s)", source.name, parser_type)
            MonitoringService.log_success(
                step_name="source_detection",
                message=f"Detected parser type {parser_type}.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
                metadata={"parser_type": parser_type},
            )

            parser = ParserRegistry.get_parser(parser_type, source=source)
            listing_pages = parser.find_listing_pages()
            source_summary["listing_pages"] = len(listing_pages)
            MonitoringService.log_success(
                step_name="listing_discovery",
                message=f"Discovered {len(listing_pages)} listing pages.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
                metadata={"listing_pages": len(listing_pages)},
            )

            normalized_jobs = []
            for listing_page in listing_pages:
                extracted_jobs = parser.extract_jobs(listing_page)
                normalized_page_jobs = cls._normalize_jobs(extracted_jobs)
                normalized_jobs.extend(normalized_page_jobs)
                MonitoringService.log_success(
                    step_name="job_extraction",
                    message=f"Extracted {len(normalized_page_jobs)} jobs from listing page.",
                    service_name=cls.__name__,
                    crawl_run=crawl_run,
                    source=source,
                    metadata={
                        "listing_url": listing_page.url,
                        "jobs_found": len(normalized_page_jobs),
                    },
                )

            source_summary["jobs_found"] = len(normalized_jobs)
            sync_summary = cls._sync_jobs_for_source(source, normalized_jobs)
            source_summary.update(sync_summary)
            source_summary["status"] = "processed"
            MonitoringService.log_success(
                step_name="source_sync",
                message="Synchronized extracted jobs.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
                metadata=sync_summary,
            )

            source.last_crawled_at = timezone.now()
            source.save(update_fields=["last_crawled_at", "updated_at"])

            logger.info(
                "Crawl completed for %s: created=%s updated=%s closed=%s",
                source.name,
                source_summary["jobs_created"],
                source_summary["jobs_updated"],
                source_summary["jobs_closed"],
            )
            MonitoringService.log_success(
                step_name="source_crawl",
                message=f"Finished crawling {source.name}.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
                metadata=source_summary,
                duration_ms=cls._duration_ms(started),
            )
            return source_summary
        except Exception as exc:
            source_summary["status"] = "failed"
            source_summary["error"] = str(exc)
            logger.exception("Crawl failed for job source %s", source.name)
            MonitoringService.log_failure(
                step_name="source_crawl",
                message=f"Crawl failed for {source.name}.",
                service_name=cls.__name__,
                crawl_run=crawl_run,
                source=source,
                metadata=source_summary,
                error=exc,
                duration_ms=cls._duration_ms(started),
            )
            return source_summary

    @classmethod
    def _sync_jobs_for_source(cls, source, normalized_jobs):
        totals = {
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_closed": 0,
        }
        jobs_by_company = defaultdict(list)

        for job_data in normalized_jobs:
            company_name = (job_data.get("company_name") or "").strip()
            if company_name:
                jobs_by_company[company_name].append(job_data)

        for company_name in cls._target_company_names(source):
            jobs_by_company.setdefault(company_name, [])

        for company_name, company_jobs in jobs_by_company.items():
            company_result = CompanyUpsertService.upsert(company_name)
            result = JobSyncService.sync_company(company_result.company, company_jobs)
            totals["jobs_created"] += result.jobs_created
            totals["jobs_updated"] += result.jobs_updated
            totals["jobs_closed"] += result.jobs_closed

        return totals

    @staticmethod
    def _normalize_jobs(extracted_jobs):
        if isinstance(extracted_jobs, (ExtractedJob, dict)):
            extracted_jobs = [extracted_jobs]

        normalized_jobs = []
        for job in extracted_jobs or []:
            if isinstance(job, ExtractedJob):
                normalized_jobs.append(
                    {
                        "title": job.title,
                        "company_name": job.company_name,
                        "source_url": job.source_url,
                        "external_id": job.external_id,
                        "location": job.location,
                        "employment_type": job.employment_type,
                        "description": job.description,
                    }
                )
            else:
                normalized_jobs.append(dict(job))
        return normalized_jobs

    @classmethod
    def _target_company_names(cls, source):
        names = []
        for config in (source.filter_config or {}, source.crawl_config or {}):
            for key in ("target_companies", "companies", "company_names"):
                names.extend(cls._coerce_company_names(config.get(key)))
            names.extend(cls._coerce_company_names(config.get("company_name")))
        return list(dict.fromkeys(names))

    @staticmethod
    def _coerce_company_names(value):
        if not value:
            return []
        if isinstance(value, str):
            return [name.strip() for name in value.split(",") if name.strip()]
        return [str(name).strip() for name in value if str(name).strip()]

    @staticmethod
    def _empty_run_summary(crawl_run):
        return {
            "success": True,
            "crawl_run_id": crawl_run.id,
            "progress_percentage": 0,
            "sources_processed": 0,
            "sources_skipped": 0,
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_closed": 0,
            "errors": 0,
            "failures": [],
            "sources": [],
            "progress": {},
        }

    @staticmethod
    def _empty_source_summary(source):
        return {
            "source_id": source.id,
            "source_name": source.name,
            "status": "pending",
            "parser_type": "",
            "listing_pages": 0,
            "jobs_found": 0,
            "jobs_created": 0,
            "jobs_updated": 0,
            "jobs_closed": 0,
            "error": "",
        }

    @classmethod
    def _start_crawl_run(cls, total_sources, crawl_run_id=None):
        if crawl_run_id:
            crawl_run = CrawlRun.objects.get(id=crawl_run_id)
            crawl_run.total_sources = total_sources
            crawl_run.processed_sources = 0
            crawl_run.success_count = 0
            crawl_run.failure_count = 0
            crawl_run.jobs_created = 0
            crawl_run.jobs_updated = 0
            crawl_run.jobs_closed = 0
            crawl_run.errors = 0
            crawl_run.current_source = ""
            crawl_run.finished_at = None
            crawl_run.status = CrawlRun.StatusChoices.RUNNING
            crawl_run.summary = {}
            crawl_run.save(
                update_fields=[
                    "total_sources",
                    "processed_sources",
                    "success_count",
                    "failure_count",
                    "jobs_created",
                    "jobs_updated",
                    "jobs_closed",
                    "errors",
                    "current_source",
                    "finished_at",
                    "status",
                    "summary",
                ]
            )
            return crawl_run

        return CrawlRun.objects.create(
            total_sources=total_sources,
            status=CrawlRun.StatusChoices.RUNNING,
        )

    @classmethod
    def _set_current_source(cls, crawl_run, source):
        crawl_run.current_source = source.name
        crawl_run.save(update_fields=["current_source"])
        logger.info(
            "Crawl progress: %s/%s sources (%.2f%%), current=%s",
            crawl_run.processed_sources,
            crawl_run.total_sources,
            crawl_run.progress_percentage,
            source.name,
        )

    @classmethod
    def _update_crawl_run_progress(cls, crawl_run, source_summary, run_summary):
        crawl_run.processed_sources += 1
        if source_summary["status"] == "processed":
            crawl_run.success_count += 1
        elif source_summary["status"] == "failed":
            crawl_run.failure_count += 1

        crawl_run.jobs_created = run_summary["jobs_created"]
        crawl_run.jobs_updated = run_summary["jobs_updated"]
        crawl_run.jobs_closed = run_summary["jobs_closed"]
        crawl_run.errors = run_summary["errors"]
        crawl_run.summary = run_summary
        crawl_run.save(
            update_fields=[
                "processed_sources",
                "success_count",
                "failure_count",
                "jobs_created",
                "jobs_updated",
                "jobs_closed",
                "errors",
                "summary",
            ]
        )
        run_summary["crawl_run_id"] = crawl_run.id
        run_summary["progress_percentage"] = crawl_run.progress_percentage

        logger.info(
            "Crawl progress: %s/%s sources (%.2f%%), successes=%s failures=%s created=%s updated=%s closed=%s errors=%s",
            crawl_run.processed_sources,
            crawl_run.total_sources,
            crawl_run.progress_percentage,
            crawl_run.success_count,
            crawl_run.failure_count,
            crawl_run.jobs_created,
            crawl_run.jobs_updated,
            crawl_run.jobs_closed,
            crawl_run.errors,
        )
        MonitoringService.log_event(
            step_name="crawl_progress",
            status=PipelineLog.StatusChoices.INFO,
            message="Crawl run progress updated.",
            service_name=cls.__name__,
            crawl_run=crawl_run,
            metadata=crawl_run.as_progress_dict(),
        )

    @classmethod
    def _finish_crawl_run(cls, crawl_run, summary):
        crawl_run.finished_at = timezone.now()
        crawl_run.current_source = ""
        crawl_run.status = (
            CrawlRun.StatusChoices.SUCCESS
            if summary["success"]
            else CrawlRun.StatusChoices.FAILED
        )
        crawl_run.jobs_created = summary["jobs_created"]
        crawl_run.jobs_updated = summary["jobs_updated"]
        crawl_run.jobs_closed = summary["jobs_closed"]
        crawl_run.errors = summary["errors"]
        crawl_run.summary = summary
        crawl_run.save(
            update_fields=[
                "finished_at",
                "current_source",
                "status",
                "jobs_created",
                "jobs_updated",
                "jobs_closed",
                "errors",
                "summary",
            ]
        )
        summary["crawl_run_id"] = crawl_run.id
        summary["progress_percentage"] = crawl_run.progress_percentage
        MonitoringService.log_event(
            step_name="crawl_run",
            status=(
                PipelineLog.StatusChoices.SUCCESS
                if summary["success"]
                else PipelineLog.StatusChoices.FAILED
            ),
            severity=(
                PipelineLog.SeverityChoices.INFO
                if summary["success"]
                else PipelineLog.SeverityChoices.ERROR
            ),
            message="Crawl run finished.",
            service_name=cls.__name__,
            crawl_run=crawl_run,
            metadata=summary,
        )

    @staticmethod
    def _emit_progress(crawl_run, progress_callback):
        if progress_callback:
            progress_callback(crawl_run.as_progress_dict())

    @staticmethod
    def _duration_ms(started):
        return int((time.perf_counter() - started) * 1000)
