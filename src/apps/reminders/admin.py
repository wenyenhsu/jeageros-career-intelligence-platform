from django.contrib import admin
from .models import FollowUpTask


@admin.register(FollowUpTask)
class FollowUpTaskAdmin(admin.ModelAdmin):
    list_display = ('application', 'task_type', 'due_date', 'completed')
