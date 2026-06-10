from rest_framework import serializers
from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import JobSource
from apps.jobs.models import JobPost


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'


class JobPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPost
        fields = '__all__'


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = '__all__'


class JobSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobSource
        fields = "__all__"
