from django.urls import path
from .views import (
    ApplicationCreateView,
    ApplicationDeleteView,
    ApplicationDetailView,
    ApplicationListView,
    ApplicationUpdateView,
    apply_application_materials_pack,
    cover_letter_tailor_status,
    run_application_ats_scan,
)

urlpatterns = [
    path("", ApplicationListView.as_view(), name="application-list"),
    path("create/", ApplicationCreateView.as_view(), name="application-create"),
    path(
        "cover-letter-status/",
        cover_letter_tailor_status,
        name="application-cover-letter-status",
    ),
    path("<int:pk>/", ApplicationDetailView.as_view(), name="application-detail"),
    path("<int:pk>/edit/", ApplicationUpdateView.as_view(), name="application-update"),
    path("<int:pk>/delete/", ApplicationDeleteView.as_view(), name="application-delete"),
    path("<int:pk>/ats-scan/", run_application_ats_scan, name="application-ats-scan"),
    path(
        "<int:pk>/materials-pack/",
        apply_application_materials_pack,
        name="application-materials-pack",
    ),
]
