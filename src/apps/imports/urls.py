from django.urls import path
from .views import job_url_import

urlpatterns = [path('job-url/', job_url_import, name='job-url-import')]
