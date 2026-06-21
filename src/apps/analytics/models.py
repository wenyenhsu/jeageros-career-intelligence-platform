from django.db import models

from apps.common.models import TimeStampedModel
from apps.skills.models import SkillSet


class SkillDemand(TimeStampedModel):
    skill = models.OneToOneField(
        SkillSet,
        on_delete=models.CASCADE,
        related_name="demand",
    )
    total_occurrences = models.PositiveIntegerField(default=0)
    unique_jobs = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    rolling_30_day_count = models.PositiveIntegerField(default=0)
    rolling_90_day_count = models.PositiveIntegerField(default=0)
    demand_score = models.FloatField(default=0.0, db_index=True)

    class Meta:
        ordering = ["-demand_score", "skill__name"]

    def __str__(self):
        return f"{self.skill.name} (score={self.demand_score})"


class SkillTrend(TimeStampedModel):
    class TrendType(models.TextChoices):
        RISING = "rising", "Rising"
        STABLE = "stable", "Stable"
        DECLINING = "declining", "Declining"

    skill = models.OneToOneField(
        SkillSet,
        on_delete=models.CASCADE,
        related_name="trend",
    )
    trend_type = models.CharField(
        max_length=20,
        choices=TrendType.choices,
        default=TrendType.STABLE,
        db_index=True,
    )
    growth_ratio = models.FloatField(default=1.0)

    class Meta:
        ordering = ["-growth_ratio", "skill__name"]

    def __str__(self):
        return f"{self.skill.name} ({self.trend_type})"


class SkillCandidate(TimeStampedModel):
    class SourceChoices(models.TextChoices):
        JOB_CRAWL = "JOB_CRAWL", "Job Crawl"
        RESUME = "RESUME", "Resume"
        MANUAL = "MANUAL", "Manual"

    name = models.CharField(max_length=120)
    normalized_name = models.CharField(max_length=120, unique=True, db_index=True)
    occurrence_count = models.PositiveIntegerField(default=0)
    first_seen = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=20,
        choices=SourceChoices.choices,
        default=SourceChoices.JOB_CRAWL,
    )
    reviewed = models.BooleanField(default=False)
    flagged_for_review = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-occurrence_count", "name"]

    def save(self, *args, **kwargs):
        self.normalized_name = SkillSet.normalize_name(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.occurrence_count})"
