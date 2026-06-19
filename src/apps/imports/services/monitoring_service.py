import logging
import json
import traceback

from django.core.serializers.json import DjangoJSONEncoder

from django.db.models import Avg, Count, Max
from django.utils import timezone
from django.utils.dateformat import format as date_format

from apps.imports.models import CrawlRun, JobArchiveRun, PipelineLog

logger = logging.getLogger(__name__)


class MonitoringService:
    RESUME_PIPELINE_STEPS = (
        ("text_extraction", "Text extraction"),
        ("ollama_extract", "Ollama Extract"),
        ("ollama_verify", "Ollama Verify"),
        ("skillset_mapping", "SkillSet mapping"),
        ("job_match", "Job match"),
        ("market_fit", "Market fit"),
    )
    FLOW_METRIC_KEYS = (
        ("jobs_created", "Created"),
        ("jobs_updated", "Updated"),
        ("jobs_closed", "Closed"),
        ("errors", "Errors"),
        ("jobs_filtered", "Filtered"),
        ("jobs_deduped", "Deduped"),
        ("skill_pipeline_jobs_processed", "Skill jobs"),
        ("skills_attached", "Skills attached"),
        ("skill_pipeline_failures", "Skill failures"),
    )
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
    TERMINAL_RUN_STATUSES = {
        CrawlRun.StatusChoices.SUCCESS,
        CrawlRun.StatusChoices.FAILED,
        CrawlRun.StatusChoices.ABORTED,
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
        return cls._logs_to_dicts(list(qs[:limit]))

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
    def dashboard_summary(cls, recent_limit=20, crawl_run_id=None, resume_run_id=None):
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
            "latest_run": cls._crawl_run_to_dict(latest_run) if latest_run else None,
            "step_summary": cls.step_summary(
                crawl_run_id=latest_run.id if latest_run else None
            ),
            "recent_logs": cls.recent_logs(
                limit=recent_limit,
                crawl_run_id=selected_run.id if selected_run else None,
            ),
            "analysis_pipeline": cls.analysis_pipeline(resume_run_id=resume_run_id),
            "job_archives": cls.job_archives(limit=10),
            "recent_failures": cls._logs_to_dicts(list(recent_failures)),
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
    def job_archives(cls, limit=10):
        return [
            cls._job_archive_to_dict(archive_run)
            for archive_run in JobArchiveRun.objects.all()[:limit]
        ]

    @classmethod
    def analysis_pipeline(cls, resume_run_id=None):
        qs = PipelineLog.objects.filter(metadata__pipeline_kind="resume_analysis")
        if resume_run_id:
            qs = qs.filter(metadata__resume_run_id=resume_run_id)
            latest_log = qs.first()
        else:
            latest_log = next(
                (
                    log
                    for log in qs[:50]
                    if isinstance(log.metadata, dict)
                    and log.metadata.get("resume_run_id")
                ),
                None,
            )
        if not latest_log:
            return {}

        run_id = resume_run_id or (latest_log.metadata or {}).get("resume_run_id")
        if not run_id:
            return {}

        logs = list(
            PipelineLog.objects.filter(
                metadata__pipeline_kind="resume_analysis",
                metadata__resume_run_id=run_id,
            ).order_by("created_at")
        )
        if not logs:
            return {}

        step_logs = {}
        terminal_log = None
        for log in logs:
            metadata = log.metadata if isinstance(log.metadata, dict) else {}
            step_key = metadata.get("pipeline_step_key")
            if step_key:
                step_logs[step_key] = log
            if log.step_name == "resume_analysis" and log.status in {
                PipelineLog.StatusChoices.SUCCESS,
                PipelineLog.StatusChoices.FAILED,
            }:
                terminal_log = log

        metadata_source = terminal_log or logs[-1]
        metadata = (
            metadata_source.metadata if isinstance(metadata_source.metadata, dict) else {}
        )
        fallback_steps = {
            step.get("key"): step
            for step in metadata.get("pipeline_steps", [])
            if isinstance(step, dict) and step.get("key")
        }
        steps = []
        finished_count = 0
        for key, label in cls.RESUME_PIPELINE_STEPS:
            log = step_logs.get(key)
            fallback = fallback_steps.get(key)
            if log:
                row = cls.log_to_dict(log)
                step_metadata = row.get("metadata") or {}
                status = row["status"]
                duration_display = row["duration_display"]
                message = row["message"]
                count = step_metadata.get("count")
            elif fallback:
                status = cls._resume_pipeline_step_status(fallback.get("status"))
                duration_display = fallback.get("duration_display", "")
                message = fallback.get("message", "")
                count = fallback.get("count")
            else:
                status = "PENDING"
                duration_display = ""
                message = "Waiting for this step."
                count = None

            if status in {
                PipelineLog.StatusChoices.SUCCESS,
                PipelineLog.StatusChoices.FAILED,
            }:
                finished_count += 1

            steps.append(
                {
                    "key": key,
                    "label": label,
                    "status": status,
                    "duration_display": duration_display,
                    "message": message,
                    "count": count,
                }
            )

        status = PipelineLog.StatusChoices.STARTED
        if terminal_log:
            status = terminal_log.status
        elif any(step["status"] == PipelineLog.StatusChoices.FAILED for step in steps):
            status = PipelineLog.StatusChoices.FAILED

        started_at = cls._display_timestamp(logs[0].created_at)
        finished_at = cls._display_timestamp(
            terminal_log.created_at if terminal_log else None
        )
        total_steps = len(cls.RESUME_PIPELINE_STEPS) or 1
        progress = (
            100 if terminal_log else round((finished_count / total_steps) * 100, 2)
        )
        market_fit = metadata.get("market_fit_percent")
        if market_fit is None:
            market_fit = (
                metadata.get("market_fit", {}).get("fit_percent", 0)
                if isinstance(metadata.get("market_fit"), dict)
                else 0
            )

        return {
            "run_id": run_id,
            "status": status,
            "progress": progress,
            "started_at_datetime": started_at["datetime"],
            "started_at_display": started_at["display"],
            "started_at_title": started_at["title"],
            "finished_at_datetime": finished_at["datetime"],
            "finished_at_display": finished_at["display"],
            "finished_at_title": finished_at["title"],
            "steps": steps,
            "summary": {
                "candidate_count": metadata.get("candidate_count", 0),
                "verified_count": metadata.get("verified_count", 0),
                "mapped_count": metadata.get("mapped_count", 0),
                "unmapped_count": metadata.get("unmapped_count", 0),
                "job_match_count": metadata.get("job_match_count", 0),
                "market_fit_percent": market_fit,
            },
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
                "last_seen_display": cls._display_timestamp(
                    row["last_seen_at"]
                )["display"],
                "average_duration_ms": cls._round_duration(row["average_duration_ms"]),
                "average_duration_display": cls._format_duration(
                    row["average_duration_ms"]
                ),
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
            "recent": cls._logs_to_dicts(list(qs[:recent_limit])),
        }

    @staticmethod
    def log_to_dict(log):
        created_at = MonitoringService._display_timestamp(log.created_at)
        error_reason = MonitoringService._error_reason(log)
        duration_display = MonitoringService._format_duration(log.duration_ms)
        metric_summary = MonitoringService._metric_summary(log)
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
            "duration_display": duration_display,
            "flow_duration_ms": log.duration_ms,
            "flow_duration_display": duration_display,
            "flow_duration_label": "Duration" if duration_display else "",
            "metric_summary": metric_summary,
            "metric_summary_text": MonitoringService._metric_summary_text(
                metric_summary
            ),
        }

    @staticmethod
    def _crawl_run_to_dict(crawl_run):
        payload = crawl_run.as_progress_dict()
        started_at = MonitoringService._display_timestamp(crawl_run.started_at)
        finished_at = MonitoringService._display_timestamp(crawl_run.finished_at)
        payload.update(
            {
                "started_at_datetime": started_at["datetime"],
                "started_at_display": started_at["display"],
                "started_at_title": started_at["title"],
                "finished_at_datetime": finished_at["datetime"],
                "finished_at_display": finished_at["display"],
                "finished_at_title": finished_at["title"],
            }
        )
        return payload

    @staticmethod
    def _job_archive_to_dict(archive_run):
        created_at = MonitoringService._display_timestamp(archive_run.created_at)
        cutoff_at = MonitoringService._display_timestamp(archive_run.cutoff_at)
        restored_at = MonitoringService._display_timestamp(archive_run.restored_at)
        return {
            "id": archive_run.id,
            "created_at_datetime": created_at["datetime"],
            "created_at_display": created_at["display"],
            "created_at_title": created_at["title"],
            "cutoff_at_datetime": cutoff_at["datetime"],
            "cutoff_at_display": cutoff_at["display"],
            "cutoff_at_title": cutoff_at["title"],
            "restored_at_datetime": restored_at["datetime"],
            "restored_at_display": restored_at["display"],
            "restored_at_title": restored_at["title"],
            "age_months": archive_run.age_months,
            "jobs_archived": archive_run.jobs_archived,
            "jobs_restored": archive_run.jobs_restored,
            "status": archive_run.status,
            "can_restore": (
                archive_run.status != JobArchiveRun.StatusChoices.RESTORED
                and archive_run.jobs_archived > 0
            ),
        }

    @classmethod
    def _logs_to_dicts(cls, logs):
        flow_durations = cls._flow_durations_for_logs(logs)
        rows = []
        for log in logs:
            row = cls.log_to_dict(log)
            flow_duration = flow_durations.get(log.id)
            if flow_duration:
                row.update(flow_duration)
            rows.append(row)
        return rows

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

    @classmethod
    def _flow_durations_for_logs(cls, logs):
        flow_durations = {}
        previous_log = None
        for log in reversed(logs):
            if log.duration_ms is not None:
                duration_ms = log.duration_ms
                label = "Duration"
            elif (
                previous_log
                and log.created_at
                and previous_log.created_at
                and log.crawl_run_id
                and log.crawl_run_id == previous_log.crawl_run_id
            ):
                duration_ms = int(
                    (log.created_at - previous_log.created_at).total_seconds() * 1000
                )
                label = "Since previous"
            else:
                duration_ms = 0 if log.created_at else None
                label = "Since previous" if log.created_at else ""

            flow_durations[log.id] = {
                "flow_duration_ms": duration_ms,
                "flow_duration_display": cls._format_duration(duration_ms),
                "flow_duration_label": label,
            }
            previous_log = log
        return flow_durations

    @classmethod
    def _metric_summary(cls, log):
        metadata = log.metadata if isinstance(log.metadata, dict) else {}
        has_run_metrics = any(key in metadata for key, _label in cls.FLOW_METRIC_KEYS)
        if log.status == PipelineLog.StatusChoices.FAILED and "errors" not in metadata:
            has_run_metrics = True

        if not has_run_metrics:
            return []

        metrics = []
        for key, label in cls.FLOW_METRIC_KEYS:
            value = metadata.get(key)
            if key == "errors" and value is None:
                value = 1 if log.status == PipelineLog.StatusChoices.FAILED else 0
            if value is None:
                if key in {"jobs_created", "jobs_updated", "jobs_closed", "errors"}:
                    value = 0
                else:
                    continue
            metrics.append({"key": key, "label": label, "value": value})
        return metrics

    @staticmethod
    def _metric_summary_text(metrics):
        return ", ".join(
            f"{metric['label']}: {metric['value']}" for metric in metrics
        )

    @staticmethod
    def _format_duration(value_ms):
        if value_ms is None:
            return ""
        try:
            total_seconds = max(0, int(round(float(value_ms) / 1000)))
        except (TypeError, ValueError):
            return ""
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

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
        if crawl_run.status in cls.TERMINAL_RUN_STATUSES:
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
        if crawl_run.status in MonitoringService.TERMINAL_RUN_STATUSES:
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

    @staticmethod
    def _resume_pipeline_step_status(status):
        if status == "success":
            return PipelineLog.StatusChoices.SUCCESS
        if status == "failed":
            return PipelineLog.StatusChoices.FAILED
        return PipelineLog.StatusChoices.INFO
