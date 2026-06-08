from django.urls import path
from .views import CompanyCreateView, CompanyListView, CompanyDeleteView,CompanyUpdateView,CompanyDetailView

urlpatterns = [
    path("", CompanyListView.as_view(), name="company-list"),
    path("<int:pk>/", CompanyDetailView.as_view(), name="company-detail"),
    path("create/", CompanyCreateView.as_view(), name="company-create"),
    path("<int:pk>/update/", CompanyUpdateView.as_view(), name="company-update"),
    path("<int:pk>/delete/", CompanyDeleteView.as_view(), name="company-delete"),
]
