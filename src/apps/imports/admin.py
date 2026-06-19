from django.contrib import admin

from .models import CrawlRun, JobArchiveRun, JobSource, PipelineLog


@admin.register(JobSource)
class JobSourceAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "resource",
        "enabled",
        "crawl_interval_minutes",
        "last_crawled_at",
        "created_at",
    )
    list_filter = ("resource", "enabled")
    search_fields = ("name", "base_url")
    readonly_fields = ("created_at", "updated_at", "last_crawled_at")
    fieldsets = (
        (
            "Basic",
            {
                "fields": (
                    "name",
                    "resource",
                    "base_url",
                    "enabled",
                    "crawl_interval_minutes",
                )
            },
        ),
        ("Rules", {"fields": ("crawl_config", "filter_config", "notes")}),
        ("Status", {"fields": ("last_crawled_at", "created_at", "updated_at")}),
    )


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "total_sources",
        "processed_sources",
        "success_count",
        "failure_count",
        "jobs_created",
        "jobs_updated",
        "jobs_closed",
        "errors",
        "progress_percentage",
        "current_source",
        "started_at",
        "finished_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "started_at",
        "finished_at",
        "total_sources",
        "processed_sources",
        "success_count",
        "failure_count",
        "jobs_created",
        "jobs_updated",
        "jobs_closed",
        "errors",
        "current_source",
        "status",
        "summary",
    )

    @admin.display(description="Progress")
    def progress_percentage(self, obj):
        return f"{obj.progress_percentage:.2f}%"


@admin.register(JobArchiveRun)
class JobArchiveRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "status",
        "age_months",
        "jobs_archived",
        "jobs_restored",
        "cutoff_at",
        "created_at",
        "restored_at",
    )
    list_filter = ("status", "age_months", "created_at", "restored_at")
    search_fields = ("payload", "error_text")
    readonly_fields = (
        "created_at",
        "cutoff_at",
        "age_months",
        "jobs_archived",
        "jobs_restored",
        "status",
        "payload",
        "restored_at",
        "error_text",
    )


@admin.register(PipelineLog)
class PipelineLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "severity",
        "status",
        "step_name",
        "service_name",
        "source",
        "job",
        "company",
        "duration_ms",
    )
    list_filter = ("severity", "status", "step_name", "service_name", "created_at")
    search_fields = (
        "message",
        "step_name",
        "service_name",
        "source__name",
        "job__title",
        "company__name",
        "error_text",
    )
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "service_name",
        "step_name",
        "status",
        "severity",
        "crawl_run",
        "source",
        "job",
        "company",
        "message",
        "metadata",
        "error_text",
        "duration_ms",
    )
