import logging
import json
import traceback

from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Count

from apps.imports.models import CrawlRun, PipelineLog

logger = logging.getLogger(__name__)


class MonitoringService:
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
        return [cls.log_to_dict(log) for log in qs[:limit]]

    @classmethod
    def run_status(cls, crawl_run_id, recent_limit=20):
        crawl_run = CrawlRun.objects.get(id=crawl_run_id)
        recent_logs = cls.recent_logs(
            limit=recent_limit,
            crawl_run_id=crawl_run.id,
        )
        errors = PipelineLog.objects.filter(
            crawl_run=crawl_run,
            status=PipelineLog.StatusChoices.FAILED,
        )
        return {
            "status": crawl_run.status,
            "progress": crawl_run.progress_percentage,
            "crawl_run": crawl_run.as_progress_dict(),
            "recent_logs": recent_logs,
            "error_summary": {
                "count": errors.count(),
                "recent": [cls.log_to_dict(log) for log in errors[:5]],
            },
        }

    @classmethod
    def dashboard_summary(cls, recent_limit=20):
        latest_run = CrawlRun.objects.first()
        recent_failures = PipelineLog.objects.filter(
            status=PipelineLog.StatusChoices.FAILED
        ).select_related("source", "job", "company")[:recent_limit]
        top_error_sources = (
            PipelineLog.objects.filter(
                status=PipelineLog.StatusChoices.FAILED,
                source__isnull=False,
            )
            .values("source_id", "source__name")
            .annotate(total=Count("id"))
            .order_by("-total", "source__name")[:10]
        )
        return {
            "latest_run": latest_run.as_progress_dict() if latest_run else None,
            "recent_logs": cls.recent_logs(limit=recent_limit),
            "recent_failures": [cls.log_to_dict(log) for log in recent_failures],
            "top_error_sources": [
                {
                    "source_id": row["source_id"],
                    "source_name": row["source__name"],
                    "total": row["total"],
                }
                for row in top_error_sources
            ],
        }

    @staticmethod
    def log_to_dict(log):
        return {
            "id": log.id,
            "created_at": log.created_at.isoformat() if log.created_at else None,
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
