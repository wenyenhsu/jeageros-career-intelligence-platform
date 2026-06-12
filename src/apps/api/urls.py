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
    analytics_gaps,
    analytics_job_categories,
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
    path("runs/<int:pk>/status/", run_status, name="api-run-status"),
    path("logs/", monitoring_logs, name="api-monitoring-logs"),
    path("crawl/run/", crawl_run, name="api-crawl-run"),
    path("crawl/<int:pk>/status/", crawl_status, name="api-crawl-status"),
    path("", include(router.urls)),
]
