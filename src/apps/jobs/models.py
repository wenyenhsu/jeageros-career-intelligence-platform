from datetime import date, datetime

from django.db import models
from apps.common.models import TimeStampedModel
from apps.companies.models import Company

from .identity import JobIdentityService


class JobPost(TimeStampedModel):
    class SourceType(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        URL = "URL", "URL"
        EMAIL = "EMAIL", "Email"
        CSV = "CSV", "CSV"

    class StatusChoices(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        APPLIED = "APPLIED", "Applied"
        CLOSED = "CLOSED", "Closed"
        ARCHIVED = "ARCHIVED", "Archived"

    JOB_TYPE_CHOICES = (
        ("Full-time", "Full Time"),
        ("Internship", "Internship"),
        ("Part-time", "Part Time"),
        ("Contract", "Contract"),
        ("Temporary", "Temporary"),
    )
    JOB_TYPE_LABELS = dict(JOB_TYPE_CHOICES)
    JOB_TYPE_ALIASES = {
        "full time": "Full-time",
        "full-time": "Full-time",
        "fulltime": "Full-time",
        "intern": "Internship",
        "internship": "Internship",
        "part time": "Part-time",
        "part-time": "Part-time",
        "parttime": "Part-time",
        "contract": "Contract",
        "temporary": "Temporary",
        "temp": "Temporary",
    }

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="job_posts"
    )
    title = models.CharField(max_length=255)
    source_url = models.URLField(blank=True)
    canonical_source_url = models.CharField(
        max_length=1000,
        blank=True,
        db_index=True,
        editable=False,
    )
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
    normalized_external_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        editable=False,
    )
    source_key = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        editable=False,
    )
    source_type = models.CharField(
        max_length=20, choices=SourceType.choices, default=SourceType.MANUAL
    )
    status = models.CharField(
        max_length=20, choices=StatusChoices.choices, default=StatusChoices.ACTIVE
    )
    location = models.CharField(max_length=120, blank=True)
    remote_type = models.CharField(max_length=50, blank=True)
    job_type = models.CharField(max_length=100, blank=True, default="")
    employment_type = models.CharField(max_length=100, blank=True)
    salary_min = models.PositiveIntegerField(null=True, blank=True)
    salary_max = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    tags = models.CharField(max_length=255, blank=True)
    skill_sets = models.ManyToManyField(
        "skills.SkillSet",
        through="skills.JobPostSkill",
        related_name="job_posts",
        blank=True,
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    start_precision = models.CharField(max_length=16, blank=True)
    end_precision = models.CharField(max_length=16, blank=True)
    season = models.CharField(max_length=32, blank=True)
    duration_weeks = models.PositiveSmallIntegerField(null=True, blank=True)
    schedule_raw = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["canonical_source_url"],
                condition=~models.Q(canonical_source_url=""),
                name="jobs_jobpost_unique_canonical_url",
            ),
            models.UniqueConstraint(
                fields=["source_key", "normalized_external_id"],
                condition=(
                    ~models.Q(source_key="") & ~models.Q(normalized_external_id="")
                ),
                name="jobs_jobpost_unique_source_external_id",
            ),
        ]

    def __str__(self):
        return f"{self.company.name} - {self.title}"

    def save(self, *args, **kwargs):
        identity = JobIdentityService.build(
            source_url=self.source_url,
            external_id=self.external_id,
            source=self.source_key,
            company_name=self.company.name if self.company_id else "",
        )
        self.canonical_source_url = identity.canonical_source_url
        self.normalized_external_id = identity.normalized_external_id
        self.source_key = identity.source_key
        normalized_job_type = self.normalize_job_type(
            self.employment_type or self.job_type
        )
        self.job_type = normalized_job_type
        self.employment_type = normalized_job_type
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
            if "source_url" in update_fields:
                update_fields.update({"canonical_source_url", "source_key"})
            if "external_id" in update_fields:
                update_fields.add("normalized_external_id")
            if update_fields & {"company", "company_id", "source_key"}:
                update_fields.add("source_key")
            kwargs["update_fields"] = list(update_fields)
        super().save(*args, **kwargs)

    @property
    def title_display(self):
        return self.title or ""

    @property
    def source_url_display(self):
        return (self.source_url or "").strip()

    @property
    def job_type_display(self):
        return self.JOB_TYPE_LABELS.get(self.job_type, self.job_type)

    @property
    def skill_set_list(self):
        return sorted(self.skill_sets.all(), key=lambda skill: skill.name.casefold())

    @property
    def skill_set_names(self):
        return [skill.name for skill in self.skill_set_list]

    @property
    def skill_set_display(self):
        return ", ".join(self.skill_set_names)

    @property
    def schedule_display(self):
        starts_on = self._coerce_date(self.starts_on)
        ends_on = self._coerce_date(self.ends_on)
        if starts_on and ends_on:
            return f"{starts_on:%b %Y} – {ends_on:%b %Y}"
        if starts_on:
            return f"{starts_on:%b %Y}"
        if self.season:
            return self.season.replace("-", " ").title()
        return ""

    @staticmethod
    def _coerce_date(value):
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    @property
    def status_badge_class(self):
        badge_classes = {
            self.StatusChoices.ACTIVE: "text-bg-success",
            self.StatusChoices.APPLIED: "text-bg-primary",
            self.StatusChoices.CLOSED: "text-bg-secondary",
            self.StatusChoices.ARCHIVED: "text-bg-dark",
        }
        return badge_classes.get(self.status, "text-bg-light border")

    @classmethod
    def normalize_job_type(cls, value):
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        key = text.casefold().replace("_", " ")
        return cls.JOB_TYPE_ALIASES.get(key, text)
