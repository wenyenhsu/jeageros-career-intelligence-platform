from django.db import models
from apps.applications.models import Application
from apps.common.models import TimeStampedModel


class InterviewRound(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='interview_rounds')
    round_type = models.CharField(max_length=60)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    interviewer = models.CharField(max_length=120, blank=True)
    outcome = models.CharField(max_length=50, blank=True)
    feedback = models.TextField(blank=True)
