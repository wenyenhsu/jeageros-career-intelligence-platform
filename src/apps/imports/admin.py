from django.contrib import admin

from .models import JobSource


@admin.register(JobSource)
class JobSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "resource", "enabled", "crawl_interval_minutes", "last_crawled_at", "created_at")
    list_filter = ("resource", "enabled")
    search_fields = ("name", "base_url")
    readonly_fields = ("created_at", "updated_at", "last_crawled_at")
    fieldsets = (
        ("Basic", {"fields": ("name", "resource", "base_url", "enabled", "crawl_interval_minutes")}),
        ("Rules", {"fields": ("crawl_config", "filter_config", "notes")}),
        ("Status", {"fields": ("last_crawled_at", "created_at", "updated_at")}),
    )
