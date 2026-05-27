from django.db import models
from apps.common.models import TimeStampedModel


class Notification(TimeStampedModel):
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
