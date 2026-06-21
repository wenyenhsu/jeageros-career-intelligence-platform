from importlib import import_module
from itertools import groupby
import threading
from uuid import uuid4

from django.conf import settings
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import format_html

from apps.companies.models import Company
from apps.analytics.serialization import make_json_serializable
from apps.imports.models import PipelineLog
from apps.imports.services.monitoring_service import MonitoringService

from .services import (
    CompanyAnalyticsService,
    DashboardService,
    JobAnalyticsService,
    ResumeAnalyticsService,
    SkillAnalyticsService,
)


def dashboard(request):
    context = DashboardService().operational_summary()
    context.update(_resume_analysis_session_context(request))
    return render(request, "dashboard/index.html", context)


def analytics_dashboard(request):
    filters = request.GET
    skill_service = SkillAnalyticsService()
    company_service = CompanyAnalyticsService(skill_service=skill_service)
    job_service = JobAnalyticsService(skill_service=skill_service)
    if request.method == "POST" and request.POST.get("action") == "resume_analysis":
        resume_run_id = _queue_resume_analysis(request, filters=filters)
        monitoring_url = (
            f"{reverse('monitoring-dashboard')}?resume_run_id={resume_run_id}"
            "#analysis-pipeline"
        )
        status_url = (
            f"{reverse('resume-analysis-status')}?resume_run_id={resume_run_id}"
        )
        dashboard_url = f"{reverse('dashboard')}#resume-analysis-results"
        if _wants_json(request):
            return JsonResponse(
                {
                    "success": True,
                    "resume_run_id": resume_run_id,
                    "status_url": status_url,
                    "monitoring_url": monitoring_url,
                    "dashboard_url": dashboard_url,
                },
                status=202,
            )
        messages.info(
            request,
            format_html(
                'Resume analysis started. <a class="alert-link" href="{}">'
                "View pipeline status</a>.",
                monitoring_url,
            ),
        )
        return redirect(f"{reverse('analytics-dashboard')}#resume-analysis")

    company_id = skill_service.normalize_filters(filters).get("company_id")
    top_skills = skill_service.top_skills(limit=8, filters=filters)
    trends = skill_service.skill_trends_by_month(limit=5, filters=filters)
    company_breakdown = company_service.company_skill_breakdown(
        limit=5,
        filters=filters,
    )
    job_categories = job_service.top_skills_by_job_category(
        limit=5,
        filters=filters,
    )
    context = {
        "filters": filters,
        "companies": Company.objects.order_by("name"),
        "top_skills": top_skills,
        "top_skill_bars": _rows_with_share(top_skills),
        "trends": trends,
        "trend_periods": _trend_periods(trends),
        "coverage": skill_service.skill_coverage_summary(filters=filters),
        "company_breakdown": company_breakdown,
        "company_skill_groups": _group_rows(company_breakdown, "company"),
        "job_categories": job_categories,
        "job_category_groups": _group_rows(job_categories, "category"),
        "skill_gaps": (
            company_service.skill_gap_analysis(company_id=company_id, filters=filters)
            if company_id
            else []
        ),
        "resume_analysis": None,
        "resume_error": "",
        "resume_text": "",
        "resume_attachment_name": "",
        "resume_analysis_status": request.session.get("resume_analysis_status") or {},
    }
    return render(request, "analytics/dashboard.html", context)


def resume_analysis_status(request):
    resume_run_id = request.GET.get("resume_run_id") or request.session.get(
        "resume_analysis_run_id"
    )
    if not resume_run_id:
        return JsonResponse(
            {
                "success": False,
                "status": "",
                "progress": 0,
                "detail": "No resume analysis run is active.",
            },
            status=404,
        )

    pipeline = MonitoringService.analysis_pipeline(resume_run_id=resume_run_id)
    session_status = request.session.get("resume_analysis_status") or {}
    status = pipeline.get("status") or session_status.get("status") or ""
    result_payload = request.session.get("resume_analysis_result") or {}
    error = (
        session_status.get("error")
        or result_payload.get("error")
        or _analysis_pipeline_error(pipeline)
    )

    return JsonResponse(
        {
            "success": status != PipelineLog.StatusChoices.FAILED,
            "resume_run_id": resume_run_id,
            "status": status,
            "progress": pipeline.get("progress", 0),
            "current_step": _current_analysis_step(pipeline),
            "analysis_ready": bool(result_payload.get("analysis")),
            "error": error,
            "dashboard_url": f"{reverse('dashboard')}#resume-analysis-results",
            "monitoring_url": (
                f"{reverse('monitoring-dashboard')}?resume_run_id={resume_run_id}"
                "#analysis-pipeline"
            ),
            "pipeline": pipeline,
        }
    )


def _queue_resume_analysis(request, filters):
    resume_run_id = uuid4().hex
    resume_text = request.POST.get("resume_text", "")
    resume_file = request.FILES.get("resume_file")
    attachment = None
    attachment_name = ""
    if resume_file:
        attachment_name = resume_file.name
        attachment = {
            "name": resume_file.name,
            "content": resume_file.read(),
            "content_type": getattr(resume_file, "content_type", "") or "",
        }

    request.session["resume_analysis_run_id"] = resume_run_id
    request.session["resume_analysis_status"] = {
        "run_id": resume_run_id,
        "status": PipelineLog.StatusChoices.STARTED,
        "attachment_name": attachment_name,
    }
    request.session.modified = True
    request.session.save()

    MonitoringService.log_event(
        step_name="resume_analysis",
        status=PipelineLog.StatusChoices.STARTED,
        severity=PipelineLog.SeverityChoices.INFO,
        message="Resume analysis queued.",
        service_name=__name__,
        metadata={
            "pipeline_kind": "resume_analysis",
            "resume_run_id": resume_run_id,
            "attachment_name": attachment_name,
        },
    )

    args = (
        request.session.session_key,
        resume_run_id,
        resume_text,
        attachment,
        _serializable_filters(filters),
    )
    if getattr(settings, "RESUME_ANALYSIS_RUN_INLINE", False):
        payload = _run_resume_analysis_job(*args, close_connections=False)
        if payload:
            request.session["resume_analysis_result"] = payload["result"]
            request.session["resume_analysis_status"] = payload["status"]
            request.session["resume_analysis_run_id"] = resume_run_id
            request.session.modified = True
            request.session.save()
    else:
        thread = threading.Thread(
            target=_run_resume_analysis_job,
            args=args,
            name=f"resume-analysis-{resume_run_id[:8]}",
            daemon=True,
        )
        thread.start()
    return resume_run_id


def _run_resume_analysis_job(
    session_key,
    resume_run_id,
    resume_text,
    attachment,
    filters,
    close_connections=True,
):
    if close_connections:
        close_old_connections()
    try:
        skill_service = SkillAnalyticsService()
        resume_service = ResumeAnalyticsService(skill_service=skill_service)
        if attachment:
            uploaded_file = SimpleUploadedFile(
                attachment["name"],
                attachment["content"],
                content_type=attachment.get("content_type") or None,
            )
            resume_analysis = resume_service.analyze_resume_attachment(
                uploaded_file,
                filters=filters,
                run_id=resume_run_id,
            )
        else:
            resume_analysis = resume_service.analyze_resume(
                resume_text,
                filters=filters,
                run_id=resume_run_id,
            )
        resume_analysis.setdefault("metadata", {})
        resume_analysis["metadata"]["resume_run_id"] = resume_run_id
        MonitoringService.log_event(
            step_name="resume_analysis",
            status=PipelineLog.StatusChoices.SUCCESS,
            severity=PipelineLog.SeverityChoices.INFO,
            message="Resume analysis background job finished.",
            service_name=__name__,
            metadata=_analysis_metadata_for_log(resume_run_id, resume_analysis),
        )
        _store_resume_analysis_payload(
            session_key,
            resume_run_id,
            analysis=resume_analysis,
            error="",
            status=PipelineLog.StatusChoices.SUCCESS,
        )
        return _resume_analysis_session_payload(
            resume_run_id,
            analysis=resume_analysis,
            error="",
            status=PipelineLog.StatusChoices.SUCCESS,
        )
    except Exception as exc:
        MonitoringService.log_failure(
            step_name="resume_analysis",
            message="Resume analysis background job failed.",
            service_name=__name__,
            metadata={
                "pipeline_kind": "resume_analysis",
                "resume_run_id": resume_run_id,
                "error": str(exc),
            },
            error=exc,
        )
        _store_resume_analysis_payload(
            session_key,
            resume_run_id,
            analysis=None,
            error=str(exc),
            status=PipelineLog.StatusChoices.FAILED,
        )
        return _resume_analysis_session_payload(
            resume_run_id,
            analysis=None,
            error=str(exc),
            status=PipelineLog.StatusChoices.FAILED,
        )
    finally:
        if close_connections:
            close_old_connections()


def _store_resume_analysis_payload(
    session_key,
    resume_run_id,
    analysis,
    error,
    status,
):
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    session = SessionStore(session_key=session_key)
    payload = _resume_analysis_session_payload(
        resume_run_id,
        analysis=analysis,
        error=error,
        status=status,
    )
    session["resume_analysis_result"] = payload["result"]
    session["resume_analysis_run_id"] = resume_run_id
    session["resume_analysis_status"] = payload["status"]
    session.save()


def _resume_analysis_session_payload(
    resume_run_id,
    analysis,
    error,
    status,
):
    attachment_name = ""
    if analysis:
        analysis = make_json_serializable(analysis)
        attachment_name = (analysis.get("metadata") or {}).get("attachment_name", "")
    return {
        "result": {
            "analysis": analysis,
            "error": error,
            "attachment_name": attachment_name,
        },
        "status": {
            "run_id": resume_run_id,
            "status": status,
            "error": error,
            "attachment_name": attachment_name,
        },
    }


def _analysis_metadata_for_log(resume_run_id, resume_analysis):
    metadata = dict(resume_analysis.get("metadata") or {})
    market_fit = resume_analysis.get("market_fit") or {}
    metadata.update(
        {
            "pipeline_kind": "resume_analysis",
            "resume_run_id": resume_run_id,
            "pipeline_steps": resume_analysis.get("pipeline_steps") or [],
            "market_fit_percent": market_fit.get("fit_percent", 0),
        }
    )
    return metadata


def _serializable_filters(filters):
    return {key: filters.get(key) for key in filters}


def _wants_json(request):
    requested_with = request.headers.get("X-Requested-With", "")
    accept = request.headers.get("Accept", "")
    return (
        requested_with.lower() == "xmlhttprequest"
        or "application/json" in accept.lower()
    )


def _current_analysis_step(pipeline):
    steps = pipeline.get("steps") or []
    for step in steps:
        if step.get("status") == PipelineLog.StatusChoices.STARTED:
            return step
    for step in steps:
        if step.get("status") == "PENDING":
            return step
    for step in reversed(steps):
        if step.get("status") in {
            PipelineLog.StatusChoices.SUCCESS,
            PipelineLog.StatusChoices.FAILED,
        }:
            return step
    return {}


def _analysis_pipeline_error(pipeline):
    for step in pipeline.get("steps") or []:
        if step.get("status") == PipelineLog.StatusChoices.FAILED:
            return step.get("message", "")
    return ""


def _resume_analysis_session_context(request):
    payload = request.session.get("resume_analysis_result") or {}
    status = request.session.get("resume_analysis_status") or {}
    return {
        "resume_analysis": payload.get("analysis"),
        "resume_error": payload.get("error", ""),
        "resume_attachment_name": payload.get("attachment_name", ""),
        "resume_analysis_status": status,
        "resume_analysis_run_id": status.get("run_id")
        or request.session.get("resume_analysis_run_id", ""),
    }


def skill_analytics(request):
    service = SkillAnalyticsService()
    context = {
        "filters": request.GET,
        "companies": Company.objects.order_by("name"),
        "top_skills": service.top_skills(limit=25, filters=request.GET),
        "coverage": service.skill_coverage_summary(filters=request.GET),
    }
    return render(request, "analytics/skills.html", context)


def company_analytics(request):
    skill_service = SkillAnalyticsService()
    service = CompanyAnalyticsService(skill_service=skill_service)
    company_id = skill_service.normalize_filters(request.GET).get("company_id")
    context = {
        "filters": request.GET,
        "companies": Company.objects.order_by("name"),
        "company_breakdown": service.company_skill_breakdown(
            company_id=company_id,
            limit=15,
            filters=request.GET,
        ),
        "skill_gaps": (
            service.skill_gap_analysis(company_id=company_id, filters=request.GET)
            if company_id
            else []
        ),
    }
    return render(request, "analytics/companies.html", context)


def trend_analytics(request):
    service = SkillAnalyticsService()
    context = {
        "filters": request.GET,
        "companies": Company.objects.order_by("name"),
        "trends": service.skill_trends_by_month(limit=10, filters=request.GET),
    }
    return render(request, "analytics/trends.html", context)


def _rows_with_share(rows, count_key="count"):
    top_count = max((row.get(count_key) or 0 for row in rows), default=0)
    return [
        {
            **row,
            "share": round(((row.get(count_key) or 0) / top_count) * 100, 1)
            if top_count
            else 0,
        }
        for row in rows
    ]


def _group_rows(rows, group_key):
    grouped = []
    sorted_rows = sorted(rows, key=lambda row: row.get(group_key) or "Unspecified")
    for group_name, group_rows in groupby(
        sorted_rows,
        key=lambda row: row.get(group_key) or "Unspecified",
    ):
        group_items = _rows_with_share(list(group_rows))
        grouped.append(
            {
                "name": group_name,
                "total": sum(item.get("count") or 0 for item in group_items),
                "items": group_items,
            }
        )
    return grouped


def _trend_periods(rows):
    periods = []
    seen = set()
    for row in rows:
        period = row.get("period")
        if not period or period in seen:
            continue
        seen.add(period)
        periods.append(period)
    return periods
