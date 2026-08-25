from copy import copy

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource, PipelineLog
from apps.jobs.identity import JobIdentityService
from apps.jobs.models import JobPost
from apps.skills.models import SkillKeyword


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = "__all__"


class JobPostSerializer(serializers.ModelSerializer):
    job_type = serializers.CharField(required=False, allow_blank=True)
    skill_set_names = serializers.SerializerMethodField()
    skill_keywords = serializers.SerializerMethodField()

    class Meta:
        model = JobPost
        fields = "__all__"
        read_only_fields = (
            "canonical_source_url",
            "normalized_external_id",
            "source_key",
        )

    def validate(self, attrs):
        if "job_type" in attrs:
            attrs["employment_type"] = JobPost.normalize_job_type(attrs.pop("job_type"))
        elif "employment_type" in attrs:
            attrs["employment_type"] = JobPost.normalize_job_type(
                attrs["employment_type"]
            )
        instance = self.instance
        company = attrs.get("company") or getattr(instance, "company", None)
        source_url = attrs.get(
            "source_url",
            getattr(instance, "source_url", ""),
        )
        external_id = attrs.get(
            "external_id",
            getattr(instance, "external_id", ""),
        )
        identity = JobIdentityService.build(
            source_url=source_url,
            external_id=external_id,
            source=getattr(instance, "source_key", ""),
            company_name=getattr(company, "name", ""),
        )
        queryset = JobPost.objects.all()
        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)
        errors = {}
        if (
            identity.canonical_source_url
            and queryset.filter(
                canonical_source_url=identity.canonical_source_url
            ).exists()
        ):
            errors["source_url"] = (
                "A job with this canonical source URL already exists."
            )
        if (
            identity.source_key
            and identity.normalized_external_id
            and queryset.filter(
                source_key=identity.source_key,
                normalized_external_id=identity.normalized_external_id,
            ).exists()
        ):
            errors["external_id"] = (
                "A job with this external ID already exists for the same source."
            )
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def get_skill_set_names(self, obj):
        return obj.skill_set_names

    def get_skill_keywords(self, obj):
        return _skill_keywords_for(obj.skill_sets.all())


class ApplicationSerializer(serializers.ModelSerializer):
    job_title = serializers.CharField(source="job_title_display", read_only=True)
    company_name = serializers.CharField(source="company_display", read_only=True)
    job_type = serializers.CharField(read_only=True)
    job_type_display = serializers.CharField(read_only=True)
    location = serializers.CharField(source="location_display", read_only=True)
    source_url = serializers.CharField(source="source_url_display", read_only=True)
    skill_set_names = serializers.SerializerMethodField()
    skill_keywords = serializers.SerializerMethodField()
    job_skill_set_names = serializers.SerializerMethodField()
    job_skill_keywords = serializers.SerializerMethodField()
    shared_skill_set_names = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = "__all__"

    def get_skill_set_names(self, obj):
        return obj.skill_set_names

    def get_skill_keywords(self, obj):
        return _skill_keywords_for(obj.skill_sets.all())

    def get_job_skill_set_names(self, obj):
        return obj.job_skill_set_names

    def get_job_skill_keywords(self, obj):
        if obj.job_post_id:
            return _skill_keywords_for(obj.job_post.skill_sets.all())
        return []

    def get_shared_skill_set_names(self, obj):
        return obj.shared_skill_set_names


class SkillKeywordSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillKeyword
        fields = "__all__"


def _skill_keywords_for(skillsets):
    keywords = []
    seen = set()
    for skillset in skillsets:
        for keyword in skillset.keywords.all():
            if keyword.status != SkillKeyword.StatusChoices.ACTIVE:
                continue
            if keyword.normalized_text in seen:
                continue
            seen.add(keyword.normalized_text)
            keywords.append(keyword.raw_text)
    return keywords


class JobSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobSource
        fields = "__all__"

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")
        if request is not None and not request.user.is_staff:
            fields["resource"].read_only = True
        return fields

    def validate(self, attrs):
        candidate = copy(self.instance) if self.instance is not None else JobSource()
        for field_name, value in attrs.items():
            setattr(candidate, field_name, value)
        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs


class CrawlRunSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = CrawlRun
        fields = "__all__"


class PipelineLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineLog
        fields = "__all__"
