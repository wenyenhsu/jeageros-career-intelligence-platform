from rest_framework import serializers
from apps.applications.models import Application
from apps.companies.models import Company
from apps.imports.models import CrawlRun, JobSource, PipelineLog
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

    def validate(self, attrs):
        if "job_type" in attrs:
            attrs["employment_type"] = JobPost.normalize_job_type(attrs.pop("job_type"))
        elif "employment_type" in attrs:
            attrs["employment_type"] = JobPost.normalize_job_type(
                attrs["employment_type"]
            )
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


class CrawlRunSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.FloatField(read_only=True)

    class Meta:
        model = CrawlRun
        fields = "__all__"


class PipelineLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineLog
        fields = "__all__"
