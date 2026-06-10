from django.urls import path

from .views import (
    JobSourceCreateView,
    JobSourceDeleteView,
    JobSourceDetailView,
    JobSourceListView,
    JobSourceUpdateView,
    job_url_import,
)

urlpatterns = [
    path("", JobSourceListView.as_view(), name="source-list"),
    path("create/", JobSourceCreateView.as_view(), name="source-create"),
    path("<int:pk>/", JobSourceDetailView.as_view(), name="source-detail"),
    path("<int:pk>/edit/", JobSourceUpdateView.as_view(), name="source-update"),
    path("<int:pk>/delete/", JobSourceDeleteView.as_view(), name="source-delete"),
    path("job-url/", job_url_import, name="job-url-import"),
]
