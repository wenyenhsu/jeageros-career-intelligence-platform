from rest_framework import viewsets
from apps.applications.models import Application
from apps.companies.models import Company
from apps.jobs.models import JobPost
from .serializers import ApplicationSerializer, CompanySerializer, JobPostSerializer


class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer


class JobPostViewSet(viewsets.ModelViewSet):
    queryset = JobPost.objects.select_related('company').all()
    serializer_class = JobPostSerializer


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.select_related('user', 'job_post').all()
    serializer_class = ApplicationSerializer
