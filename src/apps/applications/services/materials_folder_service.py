import logging
import shutil
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

    def delete_folders(self, application):
        return {
            "local": self._delete_local_folder(application),
            "drive": self._delete_drive_folder(application),
        }

    def _delete_local_folder(self, application):
        path = self.local_path_for(application)
        if path is None or not self._is_safe_materials_path(path):
            return False
        if self._other_applications_use_path(application, path):
            return False
        try:
            if path.is_dir():
                shutil.rmtree(path)
            self._remove_empty_parent(path)
        except OSError:
            logger.exception("Failed to delete local materials folder %s", path)
            return False
        return True

    def _delete_drive_folder(self, application):
        url = (getattr(application, "materials_url", "") or "").strip()
        if not url:
            return False
        if self._other_applications_use_drive_url(application, url):
            return False
        try:
            return bool(self.drive_client.delete_folder(url))
        except Exception:
            logger.exception(
                "Failed to delete Google Drive folder for application %s",
                getattr(application, "pk", None),
            )
            return False

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

    @classmethod
    def _is_safe_materials_path(cls, path):
        root = Path(getattr(settings, "APPLICATION_MATERIALS_ROOT", "") or "")
        if not str(root):
            return False
        try:
            resolved = path.resolve()
            root_resolved = root.resolve()
        except OSError:
            return False
        if resolved == root_resolved:
            return False
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            return False
        return "golden" not in resolved.name.casefold()

    @classmethod
    def _other_applications_use_path(cls, application, path):
        from ..models import Application

        others = Application.objects.select_related("job_post__company").exclude(
            pk=getattr(application, "pk", None)
        )
        for other in others:
            other_path = cls.local_path_for(other)
            if other_path is not None and other_path == path:
                return True
        return False

    @staticmethod
    def _other_applications_use_drive_url(application, url):
        from ..models import Application

        normalized = str(url or "").strip()
        if not normalized:
            return False
        return (
            Application.objects.exclude(pk=getattr(application, "pk", None))
            .filter(materials_url=normalized)
            .exists()
        )

    @classmethod
    def _remove_empty_parent(cls, path):
        root = Path(getattr(settings, "APPLICATION_MATERIALS_ROOT", "") or "")
        parent = path.parent
        try:
            if (
                parent.exists()
                and parent.resolve() != root.resolve()
                and cls._is_safe_materials_path(parent)
                and parent.is_dir()
                and not any(parent.iterdir())
            ):
                parent.rmdir()
        except OSError:
            logger.exception("Failed to remove empty materials parent %s", parent)

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
