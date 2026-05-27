from django.contrib import admin
from .models import Application, StatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ('old_status', 'new_status', 'changed_by', 'created_at', 'updated_at')


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('job_post', 'user', 'status', 'priority', 'referral', 'last_updated_at')
    list_filter = ('status', 'referral')
    search_fields = ('job_post__title', 'job_post__company__name', 'user__username')
    inlines = [StatusHistoryInline]


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('application', 'old_status', 'new_status', 'changed_by', 'created_at')
