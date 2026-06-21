from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (
    ApplicationViewSet,
    CompanyViewSet,
    CrawlRunViewSet,
    JobPostViewSet,
    JobSourceViewSet,
    SkillKeywordViewSet,
    analytics_application_comparison,
    analytics_companies,
    analytics_coverage,
    analytics_demand_ai_skills,
    analytics_demand_candidates,
    analytics_demand_categories,
    analytics_demand_cloud_skills,
    analytics_demand_data_skills,
    analytics_demand_emerging,
    analytics_demand_top_skills,
    analytics_demand_trending,
    analytics_gaps,
    analytics_job_categories,
    analytics_resume_gap,
    analytics_skills,
    analytics_trends,
    crawl_run,
    crawl_status,
    monitoring_logs,
    run_status,
)

router = DefaultRouter()
router.register("companies", CompanyViewSet, basename="api-company")
router.register("jobs", JobPostViewSet, basename="api-job")
router.register("applications", ApplicationViewSet, basename="api-application")
router.register("sources", JobSourceViewSet, basename="api-source")
router.register("crawl-runs", CrawlRunViewSet, basename="api-crawl-run")
router.register("skill-keywords", SkillKeywordViewSet, basename="api-skill-keyword")

urlpatterns = [
    path("analytics/skills/", analytics_skills, name="api-analytics-skills"),
    path(
        "analytics/companies/",
        analytics_companies,
        name="api-analytics-companies",
    ),
    path("analytics/trends/", analytics_trends, name="api-analytics-trends"),
    path("analytics/coverage/", analytics_coverage, name="api-analytics-coverage"),
    path("analytics/gaps/", analytics_gaps, name="api-analytics-gaps"),
    path(
        "analytics/job-categories/",
        analytics_job_categories,
        name="api-analytics-job-categories",
    ),
    path(
        "analytics/applications/<int:pk>/comparison/",
        analytics_application_comparison,
        name="api-analytics-application-comparison",
    ),
    path(
        "analytics/demand/top-skills/",
        analytics_demand_top_skills,
        name="api-analytics-demand-top-skills",
    ),
    path(
        "analytics/demand/emerging/",
        analytics_demand_emerging,
        name="api-analytics-demand-emerging",
    ),
    path(
        "analytics/demand/trending/",
        analytics_demand_trending,
        name="api-analytics-demand-trending",
    ),
    path(
        "analytics/demand/categories/",
        analytics_demand_categories,
        name="api-analytics-demand-categories",
    ),
    path(
        "analytics/demand/ai-skills/",
        analytics_demand_ai_skills,
        name="api-analytics-demand-ai-skills",
    ),
    path(
        "analytics/demand/cloud-skills/",
        analytics_demand_cloud_skills,
        name="api-analytics-demand-cloud-skills",
    ),
    path(
        "analytics/demand/data-skills/",
        analytics_demand_data_skills,
        name="api-analytics-demand-data-skills",
    ),
    path(
        "analytics/demand/candidates/",
        analytics_demand_candidates,
        name="api-analytics-demand-candidates",
    ),
    path(
        "analytics/resume-gap/",
        analytics_resume_gap,
        name="api-analytics-resume-gap",
    ),
    path("runs/<int:pk>/status/", run_status, name="api-run-status"),
    path("logs/", monitoring_logs, name="api-monitoring-logs"),
    path("crawl/run/", crawl_run, name="api-crawl-run"),
    path("crawl/<int:pk>/status/", crawl_status, name="api-crawl-status"),
    path("", include(router.urls)),
]
