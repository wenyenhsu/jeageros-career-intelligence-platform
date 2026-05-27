from django.conf import settings
from django.db import models
from apps.common.models import TimeStampedModel
from apps.jobs.models import JobPost


class Application(TimeStampedModel):
    class Status(models.TextChoices):
        SAVED = 'SAVED', 'Saved'
        APPLIED = 'APPLIED', 'Applied'
        OA = 'OA', 'OA'
        PHONE = 'PHONE', 'Phone Screen'
        TECH = 'TECH', 'Technical Interview'
        ONSITE = 'ONSITE', 'Onsite'
        OFFER = 'OFFER', 'Offer'
        REJECTED = 'REJECTED', 'Rejected'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job_post = models.ForeignKey(JobPost, on_delete=models.CASCADE, related_name='applications')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SAVED)
    applied_at = models.DateTimeField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=3)
    referral = models.BooleanField(default=False)
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('user', 'job_post')]
        ordering = ['-last_updated_at']

    def __str__(self):
        return f'{self.job_post.title} ({self.status})'


class StatusHistory(TimeStampedModel):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='history')
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']
