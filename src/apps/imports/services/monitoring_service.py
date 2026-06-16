import logging
import json
import traceback

from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Avg, Count, Max
from django.utils import timezone
from django.utils.dateformat import format as date_format

from apps.imports.models import CrawlRun, PipelineLog

logger = logging.getLogger(__name__)


class MonitoringService:
    PIPELINE_STAGE_PROGRESS = {
        ("crawl_run", PipelineLog.StatusChoices.INFO): 3,
        ("celery_task", PipelineLog.StatusChoices.STARTED): 5,
        ("crawl_run", PipelineLog.StatusChoices.STARTED): 10,
        ("source_crawl", PipelineLog.StatusChoices.STARTED): 20,
        ("source_detection", PipelineLog.StatusChoices.SUCCESS): 30,
        ("listing_discovery", PipelineLog.StatusChoices.SUCCESS): 40,
        ("job_extraction", PipelineLog.StatusChoices.SUCCESS): 55,
        ("job_source_filter", PipelineLog.StatusChoices.INFO): 60,
        ("company_upsert", PipelineLog.StatusChoices.SUCCESS): 65,
        ("job_upsert", PipelineLog.StatusChoices.SUCCESS): 70,
        ("job_close_detection", PipelineLog.StatusChoices.SUCCESS): 72,
        ("company_sync", PipelineLog.StatusChoices.SUCCESS): 75,
        ("source_sync", PipelineLog.StatusChoices.SUCCESS): 80,
        ("ollama_extract", PipelineLog.StatusChoices.STARTED): 82,
        ("ollama_extract", PipelineLog.StatusChoices.SUCCESS): 85,
        ("ollama_verify", PipelineLog.StatusChoices.STARTED): 87,
        ("ollama_verify", PipelineLog.StatusChoices.SUCCESS): 90,
        ("skillset_mapping", PipelineLog.StatusChoices.SUCCESS): 92,
        ("skill_scoring", PipelineLog.StatusChoices.SUCCESS): 94,
        ("skill_attach", PipelineLog.StatusChoices.SUCCESS): 96,
        ("skill_pipeline", PipelineLog.StatusChoices.SUCCESS): 98,
        ("source_crawl", PipelineLog.StatusChoices.SUCCESS): 99,
        ("crawl_progress", PipelineLog.StatusChoices.INFO): 99,
        ("crawl_run", PipelineLog.StatusChoices.SUCCESS): 100,
        ("crawl_run", PipelineLog.StatusChoices.FAILED): 100,
    }

    @classmethod
    def log_event(
        cls,
        step_name,
        status=PipelineLog.StatusChoices.INFO,
        message="",
        severity=PipelineLog.SeverityChoices.INFO,
        service_name="",
        crawl_run=None,
        crawl_run_id=None,
        source=None,
        source_id=None,
        job=None,
        job_id=None,
        company=None,
        company_id=None,
        metadata=None,
        error=None,
        error_text="",
        duration_ms=None,
    ):
        metadata = cls._json_safe(metadata or {})
        error_text = error_text or cls._error_text(error)
        payload = {
            "service_name": service_name,
            "step_name": step_name,
            "status": status,
            "severity": severity,
            "message": message,
            "metadata": metadata,
            "error_text": error_text,
            "duration_ms": duration_ms,
        }
        if crawl_run is not None:
            payload["crawl_run"] = crawl_run
        elif crawl_run_id is not None:
            payload["crawl_run_id"] = crawl_run_id
        if source is not None:
            payload["source"] = source
        elif source_id is not None:
            payload["source_id"] = source_id
        if job is not None:
            payload["job"] = job
        elif job_id is not None:
            payload["job_id"] = job_id
        if company is not None:
            payload["company"] = company
        elif company_id is not None:
            payload["company_id"] = company_id

        log_method = getattr(logger, severity.lower(), logger.info)
        exc_info = (type(error), error, error.__traceback__) if error else None
        log_method(
            "%s %s: %s metadata=%s",
            step_name,
            status,
            message,
            metadata,
            exc_info=exc_info,
        )
        try:
            return PipelineLog.objects.create(**payload)
        except Exception:
            logger.exception(
                "Unable to persist pipeline log step=%s status=%s message=%s",
                step_name,
                status,
                message,
            )
            return None

    @classmethod
    def log_success(cls, step_name, message="", **kwargs):
        return cls.log_event(
            step_name=step_name,
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message=message,
            **kwargs,
        )

    @classmethod
    def log_failure(cls, step_name, message="", error=None, **kwargs):
        return cls.log_event(
            step_name=step_name,
            status=PipelineLog.StatusChoices.FAILED,
            severity=PipelineLog.SeverityChoices.ERROR,
            message=message,
            error=error,
            **kwargs,
        )

    @classmethod
    def recent_logs(
        cls,
        limit=50,
        status="",
        severity="",
        step_name="",
        source_id=None,
        crawl_run_id=None,
        job_id=None,
        company_id=None,
    ):
        qs = PipelineLog.objects.select_related(
            "crawl_run",
            "source",
            "job",
            "company",
        )
        if status:
            qs = qs.filter(status=status)
        if severity:
            qs = qs.filter(severity=severity)
        if step_name:
            qs = qs.filter(step_name=step_name)
        if source_id:
            qs = qs.filter(source_id=source_id)
        if crawl_run_id:
            qs = qs.filter(crawl_run_id=crawl_run_id)
        if job_id:
            qs = qs.filter(job_id=job_id)
        if company_id:
            qs = qs.filter(company_id=company_id)
        return [cls.log_to_dict(log) for log in qs[:limit]]

    @classmethod
    def run_status(cls, crawl_run_id, recent_limit=20):
        crawl_run = CrawlRun.objects.get(id=crawl_run_id)
        recent_logs = cls.recent_logs(
            limit=recent_limit,
            crawl_run_id=crawl_run.id,
        )
        display_progress = cls._display_progress_for_run(crawl_run, recent_logs)
        return {
            "status": crawl_run.status,
            "progress": crawl_run.progress_percentage,
            "display_progress": display_progress,
            "display_progress_label": cls._display_progress_label(
                crawl_run,
                display_progress,
            ),
            "crawl_run": crawl_run.as_progress_dict(),
            "current_step": cls._current_step_for_run(crawl_run),
            "step_summary": cls.step_summary(crawl_run_id=crawl_run.id),
            "recent_logs": recent_logs,
            "error_summary": cls.error_summary(crawl_run_id=crawl_run.id),
        }

    @classmethod
    def dashboard_summary(cls, recent_limit=20, crawl_run_id=None):
        selected_run = cls._crawl_run_for_filter(crawl_run_id)
        latest_run = selected_run or CrawlRun.objects.first()
        log_filters = {}
        if selected_run:
            log_filters["crawl_run_id"] = selected_run.id

        failure_qs = PipelineLog.objects.filter(
            status=PipelineLog.StatusChoices.FAILED,
            **log_filters,
        ).select_related("source", "job", "company")
        recent_failures = failure_qs[:recent_limit]
        top_error_sources = (
            failure_qs.filter(source__isnull=False)
            .values("source_id", "source__name")
            .annotate(total=Count("id"))
            .order_by("-total", "source__name")[:10]
        )
        return {
            "latest_run": latest_run.as_progress_dict() if latest_run else None,
            "step_summary": cls.step_summary(
                crawl_run_id=latest_run.id if latest_run else None
            ),
            "recent_logs": cls.recent_logs(
                limit=recent_limit,
                crawl_run_id=selected_run.id if selected_run else None,
            ),
            "recent_failures": [cls.log_to_dict(log) for log in recent_failures],
            "top_error_sources": [
                {
                    "source_id": row["source_id"],
                    "source_name": row["source__name"],
                    "total": row["total"],
                }
                for row in top_error_sources
            ],
            "selected_crawl_run_id": selected_run.id if selected_run else None,
            "invalid_crawl_run_id": bool(crawl_run_id and not selected_run),
        }

    @classmethod
    def step_summary(cls, crawl_run_id=None, limit=20):
        qs = PipelineLog.objects.all()
        if crawl_run_id:
            qs = qs.filter(crawl_run_id=crawl_run_id)

        rows = (
            qs.values("step_name", "status", "severity")
            .annotate(
                total=Count("id"),
                last_seen_at=Max("created_at"),
                average_duration_ms=Avg("duration_ms"),
            )
            .order_by("step_name", "status", "severity")[:limit]
        )
        return [
            {
                "step_name": row["step_name"],
                "status": row["status"],
                "severity": row["severity"],
                "total": row["total"],
                "last_seen_at": (
                    row["last_seen_at"].isoformat() if row["last_seen_at"] else None
                ),
                "average_duration_ms": cls._round_duration(row["average_duration_ms"]),
            }
            for row in rows
        ]

    @classmethod
    def error_summary(
        cls,
        crawl_run_id=None,
        source_id=None,
        job_id=None,
        company_id=None,
        recent_limit=5,
    ):
        qs = PipelineLog.objects.filter(status=PipelineLog.StatusChoices.FAILED)
        if crawl_run_id:
            qs = qs.filter(crawl_run_id=crawl_run_id)
        if source_id:
            qs = qs.filter(source_id=source_id)
        if job_id:
            qs = qs.filter(job_id=job_id)
        if company_id:
            qs = qs.filter(company_id=company_id)

        return {
            "count": qs.count(),
            "by_step": list(
                qs.values("step_name")
                .annotate(total=Count("id"))
                .order_by("-total", "step_name")
            ),
            "by_source": [
                {
                    "source_id": row["source_id"],
                    "source_name": row["source__name"],
                    "total": row["total"],
                }
                for row in qs.filter(source__isnull=False)
                .values("source_id", "source__name")
                .annotate(total=Count("id"))
                .order_by("-total", "source__name")
            ],
            "recent": [cls.log_to_dict(log) for log in qs[:recent_limit]],
        }

    @staticmethod
    def log_to_dict(log):
        created_at = MonitoringService._display_timestamp(log.created_at)
        error_reason = MonitoringService._error_reason(log)
        return {
            "id": log.id,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "created_at_datetime": created_at["datetime"],
            "created_at_display": created_at["display"],
            "created_at_title": created_at["title"],
            "service_name": log.service_name,
            "step_name": log.step_name,
            "status": log.status,
            "severity": log.severity,
            "crawl_run_id": log.crawl_run_id,
            "source_id": log.source_id,
            "source_name": log.source.name if log.source_id and log.source else "",
            "job_id": log.job_id,
            "company_id": log.company_id,
            "company_name": log.company.name if log.company_id and log.company else "",
            "message": log.message,
            "metadata": log.metadata,
            "error_text": log.error_text,
            "error_reason": error_reason,
            "duration_ms": log.duration_ms,
        }

    @staticmethod
    def _error_text(error):
        if error is None:
            return ""
        return "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )

    @staticmethod
    def _json_safe(value):
        try:
            return json.loads(json.dumps(value, cls=DjangoJSONEncoder, default=str))
        except TypeError:
            return {"value": str(value)}

    @staticmethod
    def _round_duration(value):
        return round(float(value), 2) if value is not None else None

    @staticmethod
    def _error_reason(log):
        metadata = log.metadata if isinstance(log.metadata, dict) else {}
        direct_error = metadata.get("error")
        if direct_error:
            return str(direct_error)

        failures = metadata.get("failures")
        if isinstance(failures, list):
            for failure in failures:
                if isinstance(failure, dict) and failure.get("error"):
                    return str(failure["error"])

        sources = metadata.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and source.get("error"):
                    return str(source["error"])

        error_text = str(log.error_text or "").strip()
        if error_text:
            lines = [line.strip() for line in error_text.splitlines() if line.strip()]
            return lines[-1] if lines else error_text

        return ""

    @staticmethod
    def _display_timestamp(value):
        if not value:
            return {"datetime": "", "display": "-", "title": ""}
        local_value = timezone.localtime(value)
        return {
            "datetime": local_value.isoformat(),
            "display": date_format(local_value, "M j, g:i A"),
            "title": date_format(local_value, "Y-m-d H:i:s T"),
        }

    @classmethod
    def _current_step_for_run(cls, crawl_run):
        if crawl_run.current_source:
            return {
                "step_name": "source_crawl",
                "message": f"Crawling {crawl_run.current_source}.",
                "source_name": crawl_run.current_source,
            }
        log = (
            PipelineLog.objects.filter(crawl_run=crawl_run)
            .only("step_name", "message", "status")
            .first()
        )
        if not log:
            return {}
        return {
            "step_name": log.step_name,
            "status": log.status,
            "message": log.message,
        }

    @staticmethod
    def _crawl_run_for_filter(crawl_run_id):
        if not crawl_run_id:
            return None
        try:
            crawl_run_id = int(crawl_run_id)
        except (TypeError, ValueError):
            return None
        return CrawlRun.objects.filter(id=crawl_run_id).first()

    @classmethod
    def _display_progress_for_run(cls, crawl_run, recent_logs):
        if crawl_run.status in {
            CrawlRun.StatusChoices.SUCCESS,
            CrawlRun.StatusChoices.FAILED,
        }:
            return 100

        source_count = crawl_run.total_sources or 1
        completed_progress = crawl_run.progress_percentage
        stage_progress = cls._pipeline_stage_progress(recent_logs)
        in_source_progress = stage_progress / source_count
        return round(min(99, completed_progress + in_source_progress), 2)

    @classmethod
    def _pipeline_stage_progress(cls, recent_logs):
        progress = 0
        for log in recent_logs:
            step_name = log.get("step_name")
            status = log.get("status")
            progress = max(
                progress,
                cls.PIPELINE_STAGE_PROGRESS.get((step_name, status), 0),
            )
        return progress

    @staticmethod
    def _display_progress_label(crawl_run, display_progress):
        progress_text = MonitoringService._format_percent(display_progress)
        if crawl_run.status in {
            CrawlRun.StatusChoices.SUCCESS,
            CrawlRun.StatusChoices.FAILED,
        }:
            return f"{progress_text}% complete"
        return f"{progress_text}% estimated pipeline progress"

    @staticmethod
    def _format_percent(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return "0"
        if value.is_integer():
            return str(int(value))
        return str(round(value, 2))
