import re

from django.db import models
from pgvector.django import VectorField

from apps.common.models import TimeStampedModel


class SkillSet(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    normalized_name = models.CharField(max_length=120, unique=True, db_index=True)
    aliases = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    auto_created = models.BooleanField(default=False)
    embedding = VectorField(dimensions=1024, null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        sync_keywords = kwargs.pop("sync_keywords", True)
        self.normalized_name = self.normalize_name(self.name)
        self.aliases = self.clean_aliases(self.aliases)
        super().save(*args, **kwargs)
        if sync_keywords:
            self.sync_keywords_from_profile()

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

    @property
    def keyword_texts(self):
        return [keyword.raw_text for keyword in self.active_keywords]

    @property
    def active_keywords(self):
        return self.keywords.filter(status=SkillKeyword.StatusChoices.ACTIVE)

    def sync_keywords_from_profile(self):
        desired_keywords = [(self.name, SkillKeyword.SourceChoices.CANONICAL, True)]
        desired_keywords.extend(
            (alias, SkillKeyword.SourceChoices.ALIAS, False)
            for alias in self.aliases or []
        )

        normalized_keywords = set()
        for raw_text, source, is_primary in desired_keywords:
            normalized_text = SkillKeyword.normalize_keyword(raw_text)
            if not normalized_text or normalized_text in normalized_keywords:
                continue
            normalized_keywords.add(normalized_text)
            SkillKeyword.objects.update_or_create(
                skill_set=self,
                normalized_text=normalized_text,
                defaults={
                    "raw_text": SkillKeyword.clean_keyword(raw_text),
                    "source": source,
                    "status": SkillKeyword.StatusChoices.ACTIVE,
                    "is_primary": is_primary,
                },
            )

        SkillKeyword.objects.filter(
            skill_set=self,
            source__in=(
                SkillKeyword.SourceChoices.CANONICAL,
                SkillKeyword.SourceChoices.ALIAS,
            ),
        ).exclude(normalized_text__in=normalized_keywords).delete()

    def __str__(self):
        return self.name


class SkillKeyword(TimeStampedModel):
    class SourceChoices(models.TextChoices):
        CANONICAL = "CANONICAL", "Canonical"
        ALIAS = "ALIAS", "Alias"
        MANUAL = "MANUAL", "Manual"
        OLLAMA_EXTRACT = "OLLAMA_EXTRACT", "Ollama Extract"
        OLLAMA_VERIFY = "OLLAMA_VERIFY", "Ollama Verify"
        MAPPED = "MAPPED", "Mapped"

    class StatusChoices(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        CANDIDATE = "CANDIDATE", "Candidate"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        INACTIVE = "INACTIVE", "Inactive"

    skill_set = models.ForeignKey(
        SkillSet,
        on_delete=models.CASCADE,
        related_name="keywords",
    )
    raw_text = models.CharField(max_length=120)
    normalized_text = models.CharField(max_length=120, db_index=True)
    source = models.CharField(
        max_length=40,
        choices=SourceChoices.choices,
        default=SourceChoices.MANUAL,
    )
    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
    )
    is_primary = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["skill_set__name", "-is_primary", "raw_text"]
        constraints = [
            models.UniqueConstraint(
                fields=["skill_set", "normalized_text"],
                name="unique_skill_keyword_per_skillset",
            )
        ]
        indexes = [
            models.Index(fields=["normalized_text"]),
            models.Index(fields=["status", "normalized_text"]),
        ]

    def save(self, *args, **kwargs):
        self.raw_text = self.clean_keyword(self.raw_text or self.normalized_text)
        self.normalized_text = self.normalize_keyword(
            self.normalized_text or self.raw_text
        )
        super().save(*args, **kwargs)

    @classmethod
    def clean_keyword(cls, value):
        return re.sub(r"\s+", " ", str(value or "")).strip(" .,;:|/\\")

    @classmethod
    def normalize_keyword(cls, value):
        return SkillSet.normalize_name(value)

    @classmethod
    def ensure_for_skillset(
        cls,
        skill_set,
        raw_text,
        source=SourceChoices.MANUAL,
        status=StatusChoices.ACTIVE,
        is_primary=False,
        metadata=None,
    ):
        normalized_text = cls.normalize_keyword(raw_text)
        if not normalized_text:
            return None
        keyword, created = cls.objects.get_or_create(
            skill_set=skill_set,
            normalized_text=normalized_text,
            defaults={
                "raw_text": cls.clean_keyword(raw_text),
                "source": source,
                "status": status,
                "is_primary": is_primary,
                "metadata": metadata or {},
            },
        )
        if not created and keyword.status != status:
            keyword.status = status
            keyword.save(update_fields=["status", "updated_at"])
        return keyword

    def __str__(self):
        return f"{self.raw_text} -> {self.skill_set.name}"


class SkillAlias(TimeStampedModel):
    alias = models.CharField(max_length=120, unique=True, db_index=True)
    skill = models.ForeignKey(
        SkillSet,
        on_delete=models.CASCADE,
        related_name="skill_aliases",
    )

    class Meta:
        ordering = ["alias"]
        verbose_name_plural = "skill aliases"

    def save(self, *args, **kwargs):
        self.alias = re.sub(r"\s+", " ", str(self.alias or "")).strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.alias} -> {self.skill.name}"


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
