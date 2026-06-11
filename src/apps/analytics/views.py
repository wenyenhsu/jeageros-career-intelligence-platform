from django.shortcuts import render
from apps.companies.models import Company

from .services import (
    CompanyAnalyticsService,
    DashboardService,
    JobAnalyticsService,
    SkillAnalyticsService,
)


def dashboard(request):
    context = DashboardService().operational_summary()
    return render(request, "dashboard/index.html", context)


def analytics_dashboard(request):
    filters = request.GET
    skill_service = SkillAnalyticsService()
    company_service = CompanyAnalyticsService(skill_service=skill_service)
    job_service = JobAnalyticsService(skill_service=skill_service)
    company_id = skill_service.normalize_filters(filters).get("company_id")
    context = {
        "filters": filters,
        "companies": Company.objects.order_by("name"),
        "top_skills": skill_service.top_skills(limit=8, filters=filters),
        "trends": skill_service.skill_trends_by_month(limit=5, filters=filters),
        "company_breakdown": company_service.company_skill_breakdown(
            limit=5,
            filters=filters,
        ),
        "job_categories": job_service.top_skills_by_job_category(
            limit=5,
            filters=filters,
        ),
        "skill_gaps": (
            company_service.skill_gap_analysis(company_id=company_id, filters=filters)
            if company_id
            else []
        ),
    }
    return render(request, "analytics/dashboard.html", context)


def skill_analytics(request):
    service = SkillAnalyticsService()
    context = {
        "filters": request.GET,
        "companies": Company.objects.order_by("name"),
        "top_skills": service.top_skills(limit=25, filters=request.GET),
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
