import logging
from pathlib import Path

from django.conf import settings
from django.utils.text import slugify

from .google_drive_folder_client import GoogleDriveFolderClient

logger = logging.getLogger(__name__)


class MaterialsFolderService:
    def __init__(self, drive_client=None):
        self.drive_client = drive_client or GoogleDriveFolderClient(
            credentials_file=getattr(settings, "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE", ""),
            parent_folder_id=getattr(settings, "GOOGLE_DRIVE_PARENT_FOLDER_ID", ""),
        )

    def ensure_folders(self, application):
        path = self.local_path_for(application)
        if path is not None:
            path.mkdir(parents=True, exist_ok=True)

        if (getattr(application, "materials_url", "") or "").strip():
            return application
        if not self.drive_client.is_configured():
            return application

        try:
            url = (
                self.drive_client.create_folder(self.drive_folder_name(application))
                or ""
            ).strip()
        except Exception:
            logger.exception(
                "Failed to create Google Drive folder for application %s",
                getattr(application, "pk", None),
            )
            return application

        if not url:
            return application

        application.materials_url = url
        update_fields = ["materials_url"]
        if hasattr(application, "last_updated_at"):
            update_fields.append("last_updated_at")
        application.save(update_fields=update_fields)
        return application

    @classmethod
    def local_path_for(cls, application):
        job_post = cls._job_post(application)
        if job_post is None:
            return None
        company = cls._slug(cls._company_name(job_post), fallback="company")
        title = cls._slug(getattr(job_post, "title", ""), fallback="job")
        return Path(settings.APPLICATION_MATERIALS_ROOT) / company / title

    @classmethod
    def drive_folder_name(cls, application):
        job_post = cls._job_post(application)
        company = cls._company_name(job_post) or "Company"
        title = (getattr(job_post, "title", None) or "Job").strip() or "Job"
        return f"{company} - {title}"

    @staticmethod
    def _job_post(application):
        try:
            return application.job_post
        except Exception:
            return None

    @staticmethod
    def _company_name(job_post):
        if job_post is None:
            return ""
        company = getattr(job_post, "company", None)
        return (getattr(company, "name", None) or "").strip()

    @staticmethod
    def _slug(value, fallback="item"):
        slug = slugify(value or "")
        return slug or fallback
