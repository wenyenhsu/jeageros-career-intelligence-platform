from django.contrib import admin
from .models import JobPost


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company",
        "location",
        "employment_type",
        "source_type",
        "status",
        "last_synced_at",
        "created_at",
    )
    search_fields = (
        "title",
        "company__name",
        "location",
        "external_id",
        "source_url",
        "skill_sets__keywords__raw_text",
        "skill_sets__keywords__normalized_text",
    )
    list_filter = ("employment_type", "source_type", "status")
