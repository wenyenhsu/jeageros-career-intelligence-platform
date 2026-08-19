from django.urls import path
from apps.imports.views import MissingSkillJobListView, run_missing_skill_analysis

from .views import (
    analytics_dashboard,
    company_analytics,
    dashboard,
    resume_analysis_status,
    skill_analytics,
    trend_analytics,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("analytics/", analytics_dashboard, name="analytics-dashboard"),
    path(
        "analytics/resume/status/",
        resume_analysis_status,
        name="resume-analysis-status",
    ),
    path("analytics/skills/", skill_analytics, name="analytics-skills"),
    path("analytics/companies/", company_analytics, name="analytics-companies"),
    path("analytics/trends/", trend_analytics, name="analytics-trends"),
    path(
        "analytics/missing-skills/",
        MissingSkillJobListView.as_view(),
        name="analytics-missing-skills",
    ),
    path(
        "analytics/missing-skills/run/",
        run_missing_skill_analysis,
        name="analytics-missing-skills-run",
    ),
]
