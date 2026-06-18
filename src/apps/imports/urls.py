from django.urls import path

from .views import (
    JobSourceCreateView,
    JobSourceDeleteView,
    JobSourceDetailView,
    JobSourceHelpView,
    JobSourceListView,
    JobSourceUpdateView,
    MonitoringHelpView,
    abort_crawl_run,
    crawl_run_status,
    job_url_import,
    monitoring_dashboard,
    run_all_sources,
    run_source,
)

urlpatterns = [
    path("", JobSourceListView.as_view(), name="source-list"),
    path("help/", JobSourceHelpView.as_view(), name="source-help"),
    path("create/", JobSourceCreateView.as_view(), name="source-create"),
    path("run/", run_all_sources, name="source-run-all"),
    path("runs/<int:pk>/abort/", abort_crawl_run, name="source-run-abort"),
    path("runs/<int:pk>/status/", crawl_run_status, name="source-run-status"),
    path("monitoring/help/", MonitoringHelpView.as_view(), name="monitoring-help"),
    path("monitoring/", monitoring_dashboard, name="monitoring-dashboard"),
    path("<int:pk>/", JobSourceDetailView.as_view(), name="source-detail"),
    path("<int:pk>/edit/", JobSourceUpdateView.as_view(), name="source-update"),
    path("<int:pk>/delete/", JobSourceDeleteView.as_view(), name="source-delete"),
    path("<int:pk>/run/", run_source, name="source-run"),
    path("job-url/", job_url_import, name="job-url-import"),
]
