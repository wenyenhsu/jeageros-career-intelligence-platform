from django.db import models


class JobSource(models.Model):
    class ResourceChoices(models.TextChoices):
        LINKEDIN = "LINKEDIN", "LinkedIn"
        HANDSHAKE = "HANDSHAKE", "Handshake"
        GREENHOUSE = "GREENHOUSE", "Greenhouse"
        LEVER = "LEVER", "Lever"
        CAREER_SITE = "CAREER_SITE", "Career Site"
        RSS = "RSS", "RSS"
        API = "API", "API"
        GENERIC_HTML = "GENERIC_HTML", "Generic HTML"

    name = models.CharField(max_length=255)
    resource = models.CharField(
        max_length=20,
        choices=ResourceChoices.choices,
        db_column="source_type",
    )
    base_url = models.URLField(blank=True)
    enabled = models.BooleanField(default=True)
    crawl_interval_minutes = models.PositiveIntegerField(default=1440)
    crawl_config = models.JSONField(default=dict, blank=True)
    filter_config = models.JSONField(default=dict, blank=True)
    last_crawled_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name