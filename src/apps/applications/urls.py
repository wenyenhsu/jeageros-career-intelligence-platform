from django.urls import path
from .views import ApplicationCreateView, ApplicationDetailView, ApplicationListView, ApplicationUpdateView

urlpatterns = [
    path('', ApplicationListView.as_view(), name='application-list'),
    path('create/', ApplicationCreateView.as_view(), name='application-create'),
    path('<int:pk>/', ApplicationDetailView.as_view(), name='application-detail'),
    path('<int:pk>/edit/', ApplicationUpdateView.as_view(), name='application-edit'),
]
