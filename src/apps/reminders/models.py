from django.db import models
from apps.applications.models import Application
from apps.common.models import TimeStampedModel


class FollowUpTask(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='followup_tasks')
    task_type = models.CharField(max_length=60)
    due_date = models.DateField()
    completed = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
