from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver

from apps.jobs.services.job_status_service import sync_job_status_for_job_post_id

from .models import Application


@receiver(post_save, sender=Application)
def sync_job_status_on_application_save(sender, instance, **kwargs):
    sync_job_status_for_job_post_id(instance.job_post_id)


@receiver(pre_delete, sender=Application)
def delete_application_materials_on_delete(sender, instance, **kwargs):
    from .services.materials_folder_service import MaterialsFolderService

    MaterialsFolderService().delete_folders(instance)


@receiver(post_delete, sender=Application)
def sync_job_status_on_application_delete(sender, instance, **kwargs):
    sync_job_status_for_job_post_id(instance.job_post_id)
