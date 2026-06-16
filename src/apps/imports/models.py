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

    Resource = ResourceChoices

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
        return f"{self.name} ({self.get_resource_display()})"


class CrawlRun(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        ABORTED = "ABORTED", "Aborted"

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total_sources = models.PositiveIntegerField(default=0)
    processed_sources = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    current_source = models.CharField(max_length=255, blank=True)
    jobs_created = models.PositiveIntegerField(default=0)
    jobs_updated = models.PositiveIntegerField(default=0)
    jobs_closed = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-started_at"]

    @property
    def progress_percentage(self):
        if self.total_sources == 0:
            return 100 if self.finished_at else 0
        return round((self.processed_sources / self.total_sources) * 100, 2)

    def as_progress_dict(self):
        return {
            "id": self.id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_sources": self.total_sources,
            "processed_sources": self.processed_sources,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "current_source": self.current_source,
            "jobs_created": self.jobs_created,
            "jobs_updated": self.jobs_updated,
            "jobs_closed": self.jobs_closed,
            "errors": self.errors,
            "status": self.status,
            "progress_percentage": self.progress_percentage,
        }

    def __str__(self):
        return f"CrawlRun #{self.pk} ({self.status})"


class PipelineLog(models.Model):
    class SeverityChoices(models.TextChoices):
        DEBUG = "DEBUG", "Debug"
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"

    class StatusChoices(models.TextChoices):
        STARTED = "STARTED", "Started"
        SUCCESS = "SUCCESS", "Success"
        FAILED = "FAILED", "Failed"
        SKIPPED = "SKIPPED", "Skipped"
        INFO = "INFO", "Info"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    service_name = models.CharField(max_length=120, blank=True)
    step_name = models.CharField(max_length=120, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.INFO,
        db_index=True,
    )
    severity = models.CharField(
        max_length=20,
        choices=SeverityChoices.choices,
        default=SeverityChoices.INFO,
        db_index=True,
    )
    crawl_run = models.ForeignKey(
        CrawlRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipeline_logs",
    )
    source = models.ForeignKey(
        JobSource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipeline_logs",
    )
    job = models.ForeignKey(
        "jobs.JobPost",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipeline_logs",
    )
    company = models.ForeignKey(
        "companies.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipeline_logs",
    )
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    error_text = models.TextField(blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["step_name", "status"]),
            models.Index(fields=["severity", "created_at"]),
            models.Index(fields=["source", "created_at"]),
            models.Index(fields=["crawl_run", "created_at"]),
        ]

    def __str__(self):
        return f"{self.step_name} {self.status}: {self.message[:80]}"
