from django.contrib import admin

from .models import ApplicationSkill, JobPostSkill, SkillSet


@admin.register(SkillSet)
class SkillSetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "normalized_name",
        "is_active",
        "auto_created",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "auto_created")
    search_fields = ("name", "normalized_name", "aliases")
    readonly_fields = ("normalized_name", "created_at", "updated_at")


@admin.register(JobPostSkill)
class JobPostSkillAdmin(admin.ModelAdmin):
    list_display = (
        "job_post",
        "skill_set",
        "score",
        "source_type",
        "created_at",
        "updated_at",
    )
    list_filter = ("source_type",)
    search_fields = ("job_post__title", "skill_set__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ApplicationSkill)
class ApplicationSkillAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "skill_set",
        "score",
        "source_type",
        "created_at",
        "updated_at",
    )
    list_filter = ("source_type",)
    search_fields = ("application__job_post__title", "skill_set__name")
    readonly_fields = ("created_at", "updated_at")
