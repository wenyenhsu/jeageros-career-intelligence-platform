from django.urls import path
from .views import CompanyCreateView, CompanyListView, CompanyUpdateView

urlpatterns = [
    path('', CompanyListView.as_view(), name='company-list'),
    path('create/', CompanyCreateView.as_view(), name='company-create'),
    path('<int:pk>/edit/', CompanyUpdateView.as_view(), name='company-edit'),
]
