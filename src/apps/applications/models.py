from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.common.models import TimeStampedModel
from apps.jobs.models import JobPost

GOOGLE_DRIVE_HOSTS = ("drive.google.com", "docs.google.com")


def normalize_materials_url(value):
    url = " ".join(str(value or "").split()).strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    host = urlparse(url).netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    if host not in GOOGLE_DRIVE_HOSTS:
        raise ValidationError("Enter a Google Drive folder URL.")
    return url


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

    class MaterialsPack(models.TextChoices):
        AI = "AI", "AI"
        INFRA = "INFRA", "Infra"

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
    materials_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Google Drive folder that contains this job's cover letter and resume.",
    )
    ats_scan = models.JSONField(
        default=dict,
        blank=True,
        help_text="Latest Simplify-style ATS keyword scan for this application.",
    )
    materials_pack = models.CharField(
        max_length=16,
        blank=True,
        choices=MaterialsPack.choices,
        help_text="Golden resume pack copied into the local materials folder.",
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

    @property
    def has_materials(self):
        return bool(self.materials_url_display)

    @property
    def materials_url_display(self):
        return (self.materials_url or "").strip()

    @property
    def materials_local_path(self):
        from .services.materials_folder_service import MaterialsFolderService

        path = MaterialsFolderService.local_path_for(self)
        return str(path) if path is not None else ""

    @property
    def ats_scan_display(self):
        return self.ats_scan if isinstance(self.ats_scan, dict) else {}

    @property
    def ats_score(self):
        score = self.ats_scan_display.get("score")
        return score if isinstance(score, (int, float)) else None

    @property
    def ats_meets_target(self):
        score = self.ats_score
        target = self.ats_scan_display.get("target") or 70
        return score is not None and score >= target

    @property
    def ats_tailored_score(self):
        score = self.ats_scan_display.get("tailored_score")
        return score if isinstance(score, (int, float)) else None

    @property
    def ats_tailored_meets_target(self):
        score = self.ats_tailored_score
        target = self.ats_scan_display.get("target") or 70
        return score is not None and score >= target


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
