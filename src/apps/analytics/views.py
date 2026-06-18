from itertools import groupby

from django.shortcuts import redirect, render

from apps.companies.models import Company

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
        resume_context = _resume_analysis_context(
            request,
            skill_service,
            filters=filters,
        )
        _store_resume_analysis_context(request, resume_context)
        return redirect("dashboard")

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
    }
    return render(request, "analytics/dashboard.html", context)


def _resume_analysis_context(request, skill_service, filters):
    resume_analysis = None
    resume_error = ""
    resume_text = ""
    resume_attachment_name = ""

    if request.method == "POST" and request.POST.get("action") == "resume_analysis":
        resume_text = request.POST.get("resume_text", "")
        resume_file = request.FILES.get("resume_file")
        if resume_file:
            resume_attachment_name = resume_file.name
        try:
            resume_service = ResumeAnalyticsService(skill_service=skill_service)
            if resume_file:
                resume_analysis = resume_service.analyze_resume_attachment(
                    resume_file,
                    filters=filters,
                )
            else:
                resume_analysis = resume_service.analyze_resume(
                    resume_text,
                    filters=filters,
                )
        except Exception as exc:
            resume_error = str(exc)

    return {
        "resume_analysis": resume_analysis,
        "resume_error": resume_error,
        "resume_text": resume_text,
        "resume_attachment_name": resume_attachment_name,
    }


def _store_resume_analysis_context(request, resume_context):
    request.session["resume_analysis_result"] = {
        "analysis": resume_context.get("resume_analysis"),
        "error": resume_context.get("resume_error", ""),
        "attachment_name": resume_context.get("resume_attachment_name", ""),
    }
    request.session.modified = True


def _resume_analysis_session_context(request):
    payload = request.session.get("resume_analysis_result") or {}
    return {
        "resume_analysis": payload.get("analysis"),
        "resume_error": payload.get("error", ""),
        "resume_attachment_name": payload.get("attachment_name", ""),
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
