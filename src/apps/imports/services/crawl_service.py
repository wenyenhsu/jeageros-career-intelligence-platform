import logging
import re
import time
from collections import defaultdict
from urllib.parse import urlparse

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.jobs.models import JobPost

from .company_upsert_service import CompanyUpsertService
from .job_normalizer import JobNormalizer
from .job_sync_service import JobSyncService
from .monitoring_service import MonitoringService
from .parser_registry import ParserRegistry
from .skill_pipeline_service import SkillPipelineService
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
                summary["skill_pipeline_jobs_processed"] += source_summary[
                    "skill_pipeline_jobs_processed"
                ]
                summary["skill_pipeline_failures"] += source_summary[
                    "skill_pipeline_failures"
                ]
                summary["skills_attached"] += source_summary["skills_attached"]

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
            jobs_filtered = 0
            for listing_page in listing_pages:
                raw_jobs = parser.extract_jobs(listing_page)
                normalized_page_jobs = cls._normalize_jobs(
                    raw_jobs,
                    source=source,
                    parser_type=parser_type,
                )
                filtered_page_jobs, filtered_out_count = (
                    cls._filter_normalized_jobs_for_source(
                        normalized_page_jobs,
                        source=source,
                    )
                )
                jobs_filtered += filtered_out_count
                normalized_jobs.extend(filtered_page_jobs)
                MonitoringService.log_success(
                    step_name="job_extraction",
                    message=f"Extracted {len(filtered_page_jobs)} jobs from listing page.",
                    service_name=cls.__name__,
                    crawl_run=crawl_run,
                    source=source,
                    metadata={
                        "listing_url": listing_page.url,
                        "raw_jobs_found": len(raw_jobs or []),
                        "canonical_jobs": len(normalized_page_jobs),
                        "canonical_jobs_after_filters": len(filtered_page_jobs),
                        "jobs_filtered": filtered_out_count,
                    },
                )

            source_summary["jobs_found"] = len(normalized_jobs)
            source_summary["jobs_filtered"] = jobs_filtered
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
            "skill_pipeline_jobs_processed": 0,
            "skill_pipeline_failures": 0,
            "skills_attached": 0,
        }
        jobs_by_company = defaultdict(list)
        processed_skill_job_ids = set()

        for job_data in normalized_jobs:
            company_name = (job_data.get("company_name") or "").strip()
            if company_name:
                jobs_by_company[company_name].append(job_data)

        for company_name in cls._target_company_names(source):
            jobs_by_company.setdefault(company_name, [])

        for company_name, company_jobs in jobs_by_company.items():
            company_result = CompanyUpsertService.upsert(company_name)
            result = JobSyncService.sync_company(
                company_result.company,
                company_jobs,
                source=source,
            )
            totals["jobs_created"] += result.jobs_created
            totals["jobs_updated"] += result.jobs_updated
            totals["jobs_closed"] += result.jobs_closed
            skill_totals = cls._run_skill_pipeline_for_results(
                result.job_results,
                source=source,
            )
            processed_skill_job_ids.update(
                job_result.job.id
                for job_result in result.job_results
                if job_result.job is not None
            )
            totals["skill_pipeline_jobs_processed"] += skill_totals[
                "skill_pipeline_jobs_processed"
            ]
            totals["skill_pipeline_failures"] += skill_totals[
                "skill_pipeline_failures"
            ]
            totals["skills_attached"] += skill_totals["skills_attached"]

        existing_skill_totals = cls._run_skill_pipeline_for_existing_source_jobs(
            source,
            exclude_job_ids=processed_skill_job_ids,
        )
        totals["skill_pipeline_jobs_processed"] += existing_skill_totals[
            "skill_pipeline_jobs_processed"
        ]
        totals["skill_pipeline_failures"] += existing_skill_totals[
            "skill_pipeline_failures"
        ]
        totals["skills_attached"] += existing_skill_totals["skills_attached"]

        return totals

    @classmethod
    def _run_skill_pipeline_for_results(cls, job_results, source):
        totals = {
            "skill_pipeline_jobs_processed": 0,
            "skill_pipeline_failures": 0,
            "skills_attached": 0,
        }
        if not cls._skill_pipeline_enabled(source):
            return totals

        service = SkillPipelineService()
        auto_create = cls._skill_auto_create_enabled(source)
        for result in job_results:
            if not result.job or not result.canonical_job_payload:
                continue
            if cls._job_already_has_skills(result.job):
                continue
            pipeline_result = service.process_job_post(
                job_post=result.job,
                canonical_job_payload=result.canonical_job_payload,
                auto_create=auto_create,
            )
            totals["skill_pipeline_jobs_processed"] += 1
            if not pipeline_result.success:
                totals["skill_pipeline_failures"] += 1
                continue
            totals["skills_attached"] += pipeline_result.attached_count
        return totals

    @staticmethod
    def _job_already_has_skills(job):
        return job.skill_links.exists()

    @classmethod
    def _run_skill_pipeline_for_existing_source_jobs(cls, source, exclude_job_ids=None):
        totals = {
            "skill_pipeline_jobs_processed": 0,
            "skill_pipeline_failures": 0,
            "skills_attached": 0,
        }
        if not cls._skill_pipeline_enabled(source):
            return totals

        jobs = cls._existing_source_jobs_missing_skills(
            source,
            exclude_job_ids=exclude_job_ids or set(),
        )
        service = SkillPipelineService()
        auto_create = cls._skill_auto_create_enabled(source)
        for job in jobs:
            pipeline_result = service.process_job_post(
                job_post=job,
                canonical_job_payload=cls._canonical_payload_from_job(job, source),
                auto_create=auto_create,
            )
            totals["skill_pipeline_jobs_processed"] += 1
            if not pipeline_result.success:
                totals["skill_pipeline_failures"] += 1
                continue
            totals["skills_attached"] += pipeline_result.attached_count
        return totals

    @classmethod
    def _existing_source_jobs_missing_skills(cls, source, exclude_job_ids=None):
        queryset = (
            JobPost.objects.select_related("company")
            .prefetch_related("skill_sets", "skill_sets__keywords")
            .filter(skill_links__isnull=True)
            .exclude(status=JobPost.StatusChoices.ARCHIVED)
            .distinct()
        )
        if exclude_job_ids:
            queryset = queryset.exclude(id__in=exclude_job_ids)

        scope_filter = cls._existing_job_scope_filter(source)
        if scope_filter is None:
            return queryset.none()
        return queryset.filter(scope_filter)

    @classmethod
    def _existing_job_scope_filter(cls, source):
        filters = Q()
        has_filter = False

        hostname = cls._source_hostname(source)
        if hostname:
            filters |= Q(source_url__icontains=hostname)
            if hostname.startswith("www."):
                filters |= Q(source_url__icontains=hostname[4:])
            else:
                filters |= Q(source_url__icontains=f"www.{hostname}")
            has_filter = True

        company_filter = None
        for company_name in cls._target_company_names(source):
            condition = Q(company__name__iexact=company_name)
            company_filter = (
                condition if company_filter is None else company_filter | condition
            )
        if company_filter is not None:
            filters |= company_filter
            has_filter = True

        return filters if has_filter else None

    @staticmethod
    def _source_hostname(source):
        base_url = getattr(source, "base_url", "") or ""
        if not base_url:
            return ""
        return (urlparse(base_url).hostname or "").casefold()

    @staticmethod
    def _canonical_payload_from_job(job, source):
        return {
            "source": getattr(source, "resource", "") or "job_source",
            "source_url": job.source_url or "",
            "external_id": job.external_id or str(job.pk),
            "company_name": job.company.name,
            "title": job.title,
            "job_type": job.job_type,
            "employment_type": job.employment_type,
            "remote_type": job.remote_type,
            "location": job.location,
            "description": job.description,
            "sections": {"description": job.description} if job.description else {},
            "posted_at": None,
            "metadata": {
                "job_post_id": job.pk,
                "job_source_id": getattr(source, "pk", None),
                "skill_pipeline_scope": "existing_source_job",
            },
        }

    @staticmethod
    def _normalize_jobs(raw_jobs, source=None, parser_type=""):
        canonical_jobs = JobNormalizer.normalize_many(
            raw_jobs,
            source=source or parser_type,
        )
        return [job.as_dict() for job in canonical_jobs]

    @classmethod
    def _filter_normalized_jobs_for_source(cls, normalized_jobs, source):
        filtered = []
        filtered_out_count = 0
        for job_data in normalized_jobs:
            if cls._job_matches_source_filters(job_data, source):
                filtered.append(job_data)
            else:
                filtered_out_count += 1
                logger.info(
                    "Filtered job outside JobSource config: source=%s title=%s company=%s",
                    getattr(source, "name", ""),
                    job_data.get("title", ""),
                    job_data.get("company_name", ""),
                )
        if filtered_out_count:
            MonitoringService.log_event(
                step_name="job_source_filter",
                status=PipelineLog.StatusChoices.INFO,
                message="Filtered jobs outside JobSource config.",
                service_name=cls.__name__,
                source=source,
                metadata={
                    "jobs_before": len(normalized_jobs),
                    "jobs_after": len(filtered),
                    "jobs_filtered": filtered_out_count,
                    "target_companies": cls._target_company_names(source),
                },
            )
        return filtered, filtered_out_count

    @classmethod
    def _job_matches_source_filters(cls, job_data, source):
        target_companies = cls._normalized_company_names(cls._target_company_names(source))
        if target_companies:
            company_name = cls._normalize_company_name(job_data.get("company_name"))
            if company_name not in target_companies:
                return False

        config = cls._merged_source_config(source)
        searchable_text = cls._job_searchable_text(job_data)

        include_keywords = cls._coerce_text_values(
            config.get("include_keywords")
            or config.get("keywords")
            or config.get("keyword")
        )
        if include_keywords and not any(
            keyword.casefold() in searchable_text for keyword in include_keywords
        ):
            return False

        exclude_keywords = cls._coerce_text_values(config.get("exclude_keywords"))
        if exclude_keywords and any(
            keyword.casefold() in searchable_text for keyword in exclude_keywords
        ):
            return False

        if not cls._job_matches_location_filter(job_data, config):
            return False

        if not cls._job_matches_workplace_filter(job_data, config):
            return False

        if not cls._job_matches_job_type_filter(job_data, config):
            return False

        return True

    @classmethod
    def _target_company_names(cls, source):
        names = []
        for config in (source.filter_config or {}, source.crawl_config or {}):
            for key in ("target_companies", "companies", "company_names"):
                names.extend(cls._coerce_company_names(config.get(key)))
            names.extend(cls._coerce_company_names(config.get("company_name")))
        return list(dict.fromkeys(names))

    @classmethod
    def _merged_source_config(cls, source):
        if source is None or isinstance(source, str):
            return {}
        config = {}
        config.update(getattr(source, "filter_config", None) or {})
        config.update(getattr(source, "crawl_config", None) or {})
        return config

    @staticmethod
    def _normalized_company_names(names):
        return {CrawlService._normalize_company_name(name) for name in names if name}

    @staticmethod
    def _normalize_company_name(name):
        text = " ".join(str(name or "").split()).strip().casefold()
        for suffix in (", inc.", " inc.", ", llc", " llc", " ltd.", " ltd"):
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
        return text

    @classmethod
    def _job_searchable_text(cls, job_data):
        sections = job_data.get("sections") if isinstance(job_data.get("sections"), dict) else {}
        parts = [
            job_data.get("title"),
            job_data.get("company_name"),
            job_data.get("location"),
            job_data.get("description"),
            *sections.values(),
        ]
        return " ".join(str(part or "") for part in parts).casefold()

    @classmethod
    def _job_matches_location_filter(cls, job_data, config):
        locations = cls._coerce_text_values(
            config.get("locations") or config.get("location")
        )
        if not locations:
            return True

        normalized_locations = {
            " ".join(location.casefold().replace("_", " ").split())
            for location in locations
        }
        if normalized_locations & {"united states", "us", "usa", "u.s.", "u.s.a."}:
            return True

        job_location = str(job_data.get("location") or "").casefold()
        if not job_location:
            return False

        return any(
            cls._location_value_matches_job_location(location, job_location)
            for location in normalized_locations
        )

    @staticmethod
    def _location_value_matches_job_location(location, job_location):
        if not location:
            return False
        if len(location) == 2:
            return bool(
                re.search(
                    rf"(^|[,\s]){re.escape(location)}($|[,\s(])",
                    job_location,
                )
            )
        return location in job_location

    @classmethod
    def _job_matches_workplace_filter(cls, job_data, config):
        if cls._config_bool(config, ("remote_only",), default=False):
            workplace_types = ["remote"]
        else:
            workplace_types = cls._coerce_text_values(config.get("workplace_types"))
        if not workplace_types:
            return True

        normalized_types = {
            cls._normalize_workplace_type(workplace_type)
            for workplace_type in workplace_types
        }
        normalized_types.discard("")
        if not normalized_types or {"remote", "hybrid", "on-site"}.issubset(
            normalized_types
        ):
            return True

        text = " ".join(
            str(value or "")
            for value in (
                job_data.get("remote_type"),
                job_data.get("location"),
                job_data.get("description"),
            )
        ).casefold()
        if "remote" in normalized_types and "remote" in text:
            return True
        if "hybrid" in normalized_types and "hybrid" in text:
            return True
        if "on-site" in normalized_types:
            return not ("remote" in text or "hybrid" in text)
        return False

    @classmethod
    def _job_matches_job_type_filter(cls, job_data, config):
        configured_types = cls._coerce_text_values(
            config.get("job_types")
            or config.get("job_type")
            or config.get("employment_types")
            or config.get("employment_type")
        )
        if not configured_types:
            return True

        allowed_types = {
            cls._normalize_job_type_filter(job_type)
            for job_type in configured_types
        }
        allowed_types.discard("")
        if not allowed_types:
            return True

        job_types = {
            cls._normalize_job_type_filter(job_data.get("employment_type")),
            cls._normalize_job_type_filter(job_data.get("job_type")),
        }
        job_types.discard("")
        return bool(job_types & allowed_types)

    @staticmethod
    def _normalize_job_type_filter(value):
        normalized = JobNormalizer.normalize_job_type(value)
        return normalized or ""

    @staticmethod
    def _normalize_workplace_type(value):
        key = " ".join(str(value or "").casefold().replace("_", " ").split())
        if key in {"remote", "work from home", "wfh"}:
            return "remote"
        if key == "hybrid":
            return "hybrid"
        if key in {"on site", "onsite", "on-site", "office", "in office"}:
            return "on-site"
        return ""

    @staticmethod
    def _coerce_text_values(value):
        if not value:
            return []
        if isinstance(value, str):
            raw_values = [item.strip() for item in value.split(",")]
        else:
            raw_values = [str(item).strip() for item in value]
        return [value for value in raw_values if value]

    @classmethod
    def _skill_pipeline_enabled(cls, source):
        config = cls._merged_source_config(source)
        return cls._config_bool(
            config,
            ("enable_skill_pipeline", "skill_pipeline_enabled", "extract_skills"),
            default=settings.CRAWL_SKILL_PIPELINE_ENABLED,
        )

    @classmethod
    def _skill_auto_create_enabled(cls, source):
        config = cls._merged_source_config(source)
        return cls._config_bool(
            config,
            ("auto_create_skills", "skill_auto_create"),
            default=settings.CRAWL_SKILL_AUTO_CREATE,
        )

    @staticmethod
    def _config_bool(config, keys, default=False):
        for key in keys:
            if key not in config:
                continue
            value = config[key]
            if isinstance(value, bool):
                return value
            return str(value).strip().casefold() in {"1", "true", "yes", "on"}
        return default

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
            "skill_pipeline_jobs_processed": 0,
            "skill_pipeline_failures": 0,
            "skills_attached": 0,
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
            "jobs_filtered": 0,
            "skill_pipeline_jobs_processed": 0,
            "skill_pipeline_failures": 0,
            "skills_attached": 0,
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
