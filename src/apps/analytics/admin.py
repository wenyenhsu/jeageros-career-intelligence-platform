from django.contrib import admin

from .models import SkillCandidate, SkillDemand, SkillTrend


@admin.register(SkillDemand)
class SkillDemandAdmin(admin.ModelAdmin):
    list_display = (
        "skill",
        "demand_score",
        "unique_jobs",
        "rolling_30_day_count",
        "rolling_90_day_count",
        "total_occurrences",
        "updated_at",
    )
    search_fields = ("skill__name", "skill__normalized_name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-demand_score", "skill__name")


@admin.register(SkillTrend)
class SkillTrendAdmin(admin.ModelAdmin):
    list_display = ("skill", "trend_type", "growth_ratio", "updated_at")
    list_filter = ("trend_type",)
    search_fields = ("skill__name", "skill__normalized_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(SkillCandidate)
class SkillCandidateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "occurrence_count",
        "source",
        "flagged_for_review",
        "reviewed",
        "first_seen",
        "updated_at",
    )
    list_filter = ("source", "flagged_for_review", "reviewed")
    search_fields = ("name", "normalized_name")
    readonly_fields = ("normalized_name", "created_at", "updated_at")
