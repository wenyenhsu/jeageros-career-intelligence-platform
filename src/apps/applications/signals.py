from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.jobs.services.job_status_service import sync_job_status_for_job_post_id

from .models import Application


@receiver(post_save, sender=Application)
def sync_job_status_on_application_save(sender, instance, **kwargs):
    sync_job_status_for_job_post_id(instance.job_post_id)


@receiver(post_delete, sender=Application)
def sync_job_status_on_application_delete(sender, instance, **kwargs):
    sync_job_status_for_job_post_id(instance.job_post_id)
