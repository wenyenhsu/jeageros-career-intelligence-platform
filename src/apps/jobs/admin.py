from django.contrib import admin
from .models import JobPost


@admin.register(JobPost)
class JobPostAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "company",
        "location",
        "source_type",
        "status",
        "last_synced_at",
        "created_at",
    )
    search_fields = ("title", "company__name", "location", "external_id", "source_url")
    list_filter = ("source_type", "status")
