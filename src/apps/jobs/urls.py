from django.urls import path
from .views import JobCreateView, JobDetailView, JobListView, JobUpdateView

from django.urls import path
from .views import JobListView, JobCreateView, JobDetailView, JobUpdateView, JobDeleteView

urlpatterns = [
    path('', JobListView.as_view(), name='job-list'),
    path('create/', JobCreateView.as_view(), name='job-create'),
    path('<int:pk>/', JobDetailView.as_view(), name='job-detail'),
    path('<int:pk>/edit/', JobUpdateView.as_view(), name='job-update'),
    path('<int:pk>/delete/', JobDeleteView.as_view(), name='job-delete'),
]
