from django.urls import path
from .views import ApplicationCreateView, ApplicationDetailView, ApplicationListView, ApplicationUpdateView,ApplicationDeleteView

urlpatterns = [
    path("", ApplicationListView.as_view(), name="application-list"),
    path("create/", ApplicationCreateView.as_view(), name="application-create"),
    path("<int:pk>/", ApplicationDetailView.as_view(), name="application-detail"),
    path("<int:pk>/edit/", ApplicationUpdateView.as_view(), name="application-update"),
    path("<int:pk>/delete/", ApplicationDeleteView.as_view(), name="application-delete"),
]
