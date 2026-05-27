from django.contrib import admin
from .models import InterviewRound


@admin.register(InterviewRound)
class InterviewRoundAdmin(admin.ModelAdmin):
    list_display = ('application', 'round_type', 'scheduled_at', 'outcome')
