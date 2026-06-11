from django.contrib import admin

from .models import ApplicationSkill, JobPostSkill, SkillKeyword, SkillSet


class SkillKeywordInline(admin.TabularInline):
    model = SkillKeyword
    extra = 0
    fields = (
        "raw_text",
        "normalized_text",
        "source",
        "status",
        "is_primary",
    )
    readonly_fields = ("normalized_text",)


@admin.register(SkillSet)
class SkillSetAdmin(admin.ModelAdmin):
    inlines = (SkillKeywordInline,)
    list_display = (
        "name",
        "normalized_name",
        "is_active",
        "auto_created",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "auto_created")
    search_fields = (
        "name",
        "normalized_name",
        "aliases",
        "keywords__raw_text",
        "keywords__normalized_text",
    )
    readonly_fields = ("normalized_name", "created_at", "updated_at")


@admin.register(SkillKeyword)
class SkillKeywordAdmin(admin.ModelAdmin):
    list_display = (
        "raw_text",
        "normalized_text",
        "skill_set",
        "source",
        "status",
        "is_primary",
        "created_at",
        "updated_at",
    )
    list_filter = ("source", "status", "is_primary")
    search_fields = (
        "raw_text",
        "normalized_text",
        "skill_set__name",
        "skill_set__normalized_name",
    )
    readonly_fields = ("normalized_text", "created_at", "updated_at")
    autocomplete_fields = ("skill_set",)


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
