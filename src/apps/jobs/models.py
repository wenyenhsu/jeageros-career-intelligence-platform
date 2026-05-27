from django.db import models
from apps.common.models import TimeStampedModel
from apps.companies.models import Company


class JobPost(TimeStampedModel):
    class SourceType(models.TextChoices):
        MANUAL = 'MANUAL', 'Manual'
        URL = 'URL', 'URL'
        EMAIL = 'EMAIL', 'Email'
        CSV = 'CSV', 'CSV'

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='job_posts')
    title = models.CharField(max_length=255)
    source_url = models.URLField(blank=True)
    source_type = models.CharField(max_length=20, choices=SourceType.choices, default=SourceType.MANUAL)
    location = models.CharField(max_length=120, blank=True)
    remote_type = models.CharField(max_length=50, blank=True)
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.company.name} - {self.title}'
