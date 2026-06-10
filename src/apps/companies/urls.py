from django.urls import path
from .views import (
    CompanyCreateView,
    CompanyDeleteView,
    CompanyDetailView,
    CompanyListView,
    CompanyUpdateView,
    company_sync_jobs,
)

urlpatterns = [
    path("", CompanyListView.as_view(), name="company-list"),
    path("<int:pk>/", CompanyDetailView.as_view(), name="company-detail"),
    path("<int:pk>/sync/", company_sync_jobs, name="company-sync-jobs"),
    path("create/", CompanyCreateView.as_view(), name="company-create"),
    path("<int:pk>/update/", CompanyUpdateView.as_view(), name="company-update"),
    path("<int:pk>/delete/", CompanyDeleteView.as_view(), name="company-delete"),
]
