from django.conf import settings
from django.db import models
from apps.common.models import TimeStampedModel
from apps.jobs.models import JobPost


class Application(TimeStampedModel):
    class Status(models.TextChoices):
        SAVED = "SAVED", "Saved"
        APPLIED = "APPLIED", "Applied"
        OA = "OA", "OA"
        PHONE = "PHONE", "Phone Screen"
        TECH = "TECH", "Technical Interview"
        ONSITE = "ONSITE", "Onsite"
        OFFER = "OFFER", "Offer"
        REJECTED = "REJECTED", "Rejected"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    job_post = models.ForeignKey(
        JobPost, on_delete=models.CASCADE, related_name="applications"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SAVED
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    priority = models.PositiveSmallIntegerField(default=3)
    referral = models.BooleanField(default=False)
    skill_sets = models.ManyToManyField(
        "skills.SkillSet",
        through="skills.ApplicationSkill",
        related_name="applications",
        blank=True,
    )
    last_updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "job_post")]
        ordering = ["-last_updated_at"]

    def __str__(self):
        return f"{self.job_post.title} ({self.status})"

    def _linked_job_post(self):
        try:
            return self.job_post
        except (AttributeError, JobPost.DoesNotExist):
            return None

    @property
    def job_title_display(self):
        job_post = self._linked_job_post()
        return job_post.title if job_post else ""

    @property
    def company_display(self):
        job_post = self._linked_job_post()
        if not job_post or not job_post.company_id:
            return ""
        return job_post.company.name

    @property
    def job_type(self):
        job_post = self._linked_job_post()
        return job_post.job_type if job_post else ""

    @property
    def job_type_display(self):
        job_post = self._linked_job_post()
        return job_post.job_type_display if job_post else ""

    @property
    def location_display(self):
        job_post = self._linked_job_post()
        return job_post.location if job_post else ""

    @property
    def source_url_display(self):
        job_post = self._linked_job_post()
        return job_post.source_url_display if job_post else ""

    @property
    def job_skill_set_list(self):
        job_post = self._linked_job_post()
        return job_post.skill_set_list if job_post else []

    @property
    def job_skill_set_names(self):
        return [skill.name for skill in self.job_skill_set_list]

    @property
    def job_skill_set_display(self):
        return ", ".join(self.job_skill_set_names)

    @property
    def shared_skill_set_list(self):
        return self.job_skill_set_list

    @property
    def shared_skill_set_names(self):
        return self.job_skill_set_names

    @property
    def shared_skill_set_display(self):
        return self.job_skill_set_display

    @property
    def skill_set_list(self):
        return sorted(self.skill_sets.all(), key=lambda skill: skill.name.casefold())

    @property
    def application_only_skill_set_list(self):
        job_skill_ids = {skill.id for skill in self.job_skill_set_list}
        return [
            skill
            for skill in self.skill_set_list
            if skill.id not in job_skill_ids
        ]

    @property
    def application_only_skill_set_names(self):
        return [skill.name for skill in self.application_only_skill_set_list]

    @property
    def application_only_skill_set_display(self):
        return ", ".join(self.application_only_skill_set_names)

    @property
    def skill_set_names(self):
        return [skill.name for skill in self.skill_set_list]

    @property
    def skill_set_display(self):
        return ", ".join(self.skill_set_names)


class StatusHistory(TimeStampedModel):
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="history"
    )
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )

    class Meta:
        ordering = ["-created_at"]
