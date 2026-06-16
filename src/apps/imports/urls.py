from django.urls import path

from .views import (
    JobSourceCreateView,
    JobSourceDeleteView,
    JobSourceDetailView,
    JobSourceListView,
    JobSourceUpdateView,
    job_url_import,
    monitoring_dashboard,
    run_all_sources,
    run_source,
)

urlpatterns = [
    path("", JobSourceListView.as_view(), name="source-list"),
    path("create/", JobSourceCreateView.as_view(), name="source-create"),
    path("run/", run_all_sources, name="source-run-all"),
    path("<int:pk>/", JobSourceDetailView.as_view(), name="source-detail"),
    path("<int:pk>/edit/", JobSourceUpdateView.as_view(), name="source-update"),
    path("<int:pk>/delete/", JobSourceDeleteView.as_view(), name="source-delete"),
    path("<int:pk>/run/", run_source, name="source-run"),
    path("job-url/", job_url_import, name="job-url-import"),
    path("monitoring/", monitoring_dashboard, name="monitoring-dashboard"),
]
