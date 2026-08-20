from django.contrib import admin
from .forms import ApplicationForm
from .models import Application, StatusHistory


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    can_delete = False
    readonly_fields = (
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
        "updated_at",
    )


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    form = ApplicationForm
    list_display = (
        "job_post",
        "user",
        "status",
        "priority",
        "referral",
        "has_materials",
        "last_updated_at",
    )
    list_filter = ("status", "referral")
    search_fields = (
        "job_post__title",
        "job_post__company__name",
        "user__username",
        "skill_sets__keywords__raw_text",
        "skill_sets__keywords__normalized_text",
        "job_post__skill_sets__keywords__raw_text",
        "job_post__skill_sets__keywords__normalized_text",
    )
    inlines = [StatusHistoryInline]

    @admin.display(boolean=True, description="Drive folder")
    def has_materials(self, obj):
        return obj.has_materials


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "old_status",
        "new_status",
        "changed_by",
        "created_at",
    )
