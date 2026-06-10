import re

from django.db import models

from apps.common.models import TimeStampedModel


class SkillSet(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    normalized_name = models.CharField(max_length=120, unique=True, db_index=True)
    aliases = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    auto_created = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.normalized_name = self.normalize_name(self.name)
        self.aliases = self.clean_aliases(self.aliases)
        super().save(*args, **kwargs)

    @classmethod
    def normalize_name(cls, name):
        normalized = re.sub(r"\s+", " ", str(name or "")).strip()
        normalized = normalized.strip(".,;:|/\\")
        return normalized.casefold()

    @classmethod
    def clean_aliases(cls, aliases):
        if not aliases:
            return []

        cleaned = []
        seen = set()
        values = aliases
        if isinstance(aliases, str):
            values = [aliases]

        for alias in values:
            text = re.sub(r"\s+", " ", str(alias or "")).strip()
            text = text.strip(".,;:|/\\")
            key = cls.normalize_name(text)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned

    @property
    def normalized_aliases(self):
        return [self.normalize_name(alias) for alias in self.aliases or []]

    def __str__(self):
        return self.name


class SkillAttachmentSource(models.TextChoices):
    OLLAMA_PIPELINE = "OLLAMA_PIPELINE", "Ollama Pipeline"
    MANUAL = "MANUAL", "Manual"


class SkillAttachmentBase(TimeStampedModel):
    skill_set = models.ForeignKey(SkillSet, on_delete=models.CASCADE)
    score = models.PositiveSmallIntegerField(default=0)
    source_type = models.CharField(
        max_length=40,
        choices=SkillAttachmentSource.choices,
        default=SkillAttachmentSource.OLLAMA_PIPELINE,
    )
    extraction_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class JobPostSkill(SkillAttachmentBase):
    job_post = models.ForeignKey(
        "jobs.JobPost",
        on_delete=models.CASCADE,
        related_name="skill_links",
    )

    class Meta:
        ordering = ["-score", "skill_set__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["job_post", "skill_set"],
                name="unique_jobpost_skill",
            )
        ]

    def __str__(self):
        return f"{self.job_post} - {self.skill_set} ({self.score})"


class ApplicationSkill(SkillAttachmentBase):
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.CASCADE,
        related_name="skill_links",
    )

    class Meta:
        ordering = ["-score", "skill_set__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "skill_set"],
                name="unique_application_skill",
            )
        ]

    def __str__(self):
        return f"{self.application} - {self.skill_set} ({self.score})"
