from django.db import models
from apps.common.models import TimeStampedModel
from apps.companies.models import Company


class JobPost(TimeStampedModel):
    class SourceType(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        URL = "URL", "URL"
        EMAIL = "EMAIL", "Email"
        CSV = "CSV", "CSV"

    class StatusChoices(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
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
    external_id = models.CharField(max_length=255, blank=True, db_index=True)
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.company.name} - {self.title}"

    def save(self, *args, **kwargs):
        normalized_job_type = self.normalize_job_type(
            self.employment_type or self.job_type
        )
        self.job_type = normalized_job_type
        self.employment_type = normalized_job_type
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

    @classmethod
    def normalize_job_type(cls, value):
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return ""
        key = text.casefold().replace("_", " ")
        return cls.JOB_TYPE_ALIASES.get(key, text)
