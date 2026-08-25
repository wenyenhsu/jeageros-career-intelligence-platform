import logging
import threading
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

from .ats_document_writer import AtsDocumentWriter
from .ats_keyword_extractor import AtsKeywordError, AtsKeywordExtractor
from .ats_scan_service import AtsScanService
from .materials_folder_service import MaterialsFolderService
from .materials_pack_service import MaterialsPackService
from ..models import GOOGLE_DRIVE_HOSTS

logger = logging.getLogger(__name__)

PROGRESS_CACHE_PREFIX = "cover-letter-run:"
PROGRESS_CACHE_TTL = 60 * 60


def normalize_run_id(value):
    return "".join(ch for ch in str(value or "") if ch.isalnum())[:64]


def save_cover_letter_progress(
    run_id,
    *,
    status,
    progress,
    label,
    error="",
    application_id=None,
    result=None,
):
    run_id = normalize_run_id(run_id)
    if not run_id:
        return {}
    payload = {
        "run_id": run_id,
        "status": status,
        "progress": max(0, min(100, int(progress or 0))),
        "current_step": {"label": label},
        "error": error or "",
        "application_id": application_id,
        "result": result or {},
    }
    cache.set(f"{PROGRESS_CACHE_PREFIX}{run_id}", payload, PROGRESS_CACHE_TTL)
    return payload


def get_cover_letter_progress(run_id):
    run_id = normalize_run_id(run_id)
    if not run_id:
        return {}
    return cache.get(f"{PROGRESS_CACHE_PREFIX}{run_id}") or {}


def queue_cover_letter_tailor(application_id, run_id):
    run_id = normalize_run_id(run_id)
    save_cover_letter_progress(
        run_id,
        status="STARTED",
        progress=18,
        label="Materials copied",
        application_id=application_id,
    )

    def job():
        close_old_connections()
        try:
            from apps.applications.models import Application

            application = Application.objects.select_related("job_post__company").get(
                pk=application_id
            )
            CoverLetterTailorService().run(application, run_id=run_id)
        except Exception:
            logger.exception("Queued cover letter tailor failed")
            save_cover_letter_progress(
                run_id,
                status="FAILED",
                progress=100,
                label="Cover letter tailor failed",
                error="Could not tailor the cover letter; left the copied file unchanged.",
                application_id=application_id,
            )
        finally:
            close_old_connections()

    if getattr(settings, "COVER_LETTER_TAILOR_RUN_INLINE", False):
        job()
        return run_id

    thread = threading.Thread(
        target=job,
        name=f"cover-letter-{run_id[:8] or 'run'}",
        daemon=True,
    )
    thread.start()
    return run_id


class CoverLetterTailorService:
    """Rewrite the copied cover letter from this job's JD. Not SkillSet / Market Fit."""

    def __init__(self, extractor=None, fetch_description=None):
        self.extractor = extractor or AtsKeywordExtractor()
        self.fetch_description = fetch_description or self.fetch_job_description
        self.document_writer = AtsDocumentWriter()

    def run(self, application, run_id=""):
        self.run_id = normalize_run_id(run_id)
        self._progress(
            "STARTED",
            35,
            "Fetching job description",
            application,
        )
        try:
            result = self._run(application)
        except Exception:
            logger.exception("Cover letter tailor failed")
            result = {
                "tailored": False,
                "skipped": False,
                "error": "Could not tailor the cover letter; left the copied file unchanged.",
                "written": [],
                "backups": [],
            }
            self._finish(application, result, status="FAILED")
            return result
        self._finish(application, result)
        return result

    def _run(self, application):
        job_post = getattr(application, "job_post", None)
        if job_post is None:
            return self._skip()

        folder = MaterialsFolderService.local_path_for(application)
        cover_files = self._cover_letter_files(folder, application.materials_pack)
        if not cover_files:
            return self._skip()

        url = (getattr(job_post, "source_url", "") or "").strip()
        stored = (getattr(job_post, "description", "") or "").strip()
        fetched = ""
        if url and not self._is_drive_url(url):
            try:
                fetched = (self.fetch_description(url) or "").strip()
            except Exception:
                logger.exception("Job URL fetch failed for cover letter tailor")
                fetched = ""

        description = fetched or stored
        if not description:
            if url:
                return {
                    "tailored": False,
                    "skipped": False,
                    "error": (
                        "Could not fetch the job description; "
                        "left the copied cover letter unchanged."
                    ),
                    "written": [],
                    "backups": [],
                }
            return self._skip()

        if fetched and not stored:
            job_post.description = fetched
            job_post.save(update_fields=["description"])

        self._progress("STARTED", 70, "Rewriting cover letter", application)
        cover_text = self._read_text(cover_files[0])
        if not cover_text:
            return {
                "tailored": False,
                "skipped": False,
                "error": "Could not read the copied cover letter; left it unchanged.",
                "written": [],
                "backups": [],
            }

        try:
            rewritten = self.extractor.rewrite_cover_letter(
                application.job_title_display or "the role",
                application.company_display or "the company",
                cover_text,
                description,
            )
        except AtsKeywordError as exc:
            logger.warning("Cover letter rewrite failed: %s", exc)
            return {
                "tailored": False,
                "skipped": False,
                "error": "Could not tailor the cover letter; left the copied file unchanged.",
                "written": [],
                "backups": [],
            }

        rewritten = str(rewritten or "").strip()
        if not rewritten:
            return {
                "tailored": False,
                "skipped": False,
                "error": "Could not tailor the cover letter; left the copied file unchanged.",
                "written": [],
                "backups": [],
            }

        written = []
        backups = []
        for path in cover_files:
            result = self.document_writer.overwrite_file(
                path, title="Cover Letter", text=rewritten
            )
            written.append(path.name)
            if result.get("backup"):
                backups.append(result["backup"])

        return {
            "tailored": True,
            "skipped": False,
            "error": "",
            "written": written,
            "backups": backups,
        }

    @staticmethod
    def _skip():
        return {
            "tailored": False,
            "skipped": True,
            "error": "",
            "written": [],
            "backups": [],
        }

    def _progress(self, status, progress, label, application, error="", result=None):
        if not getattr(self, "run_id", ""):
            return {}
        return save_cover_letter_progress(
            self.run_id,
            status=status,
            progress=progress,
            label=label,
            error=error,
            application_id=getattr(application, "pk", None),
            result=result,
        )

    def _finish(self, application, result, status=""):
        result = result or {}
        if status:
            final_status = status
        elif result.get("error"):
            final_status = "FAILED"
        else:
            final_status = "SUCCESS"
        if result.get("tailored"):
            label = "Tailored cover letter to this job description"
        elif result.get("error"):
            label = result["error"]
        else:
            label = "Copied materials pack"
        self._progress(
            final_status,
            100,
            label,
            application,
            error=result.get("error") or "",
            result=result,
        )

    @classmethod
    def fetch_job_description(cls, url):
        from apps.imports.services.job_normalizer import JobNormalizer
        from apps.imports.services.parser_registry import ParserRegistry

        url = str(url or "").strip()
        if not url:
            return ""
        parser = ParserRegistry.get_parser_for_url(url)
        try:
            raw_jobs = parser.extract_single_job(url) or []
        except Exception:
            logger.exception("Job URL parse failed for cover letter tailor")
            return ""
        if not raw_jobs:
            return ""
        try:
            payload = JobNormalizer.normalize(raw_jobs[0], source=url, validate=False)
        except Exception:
            logger.exception("Job URL normalize failed for cover letter tailor")
            return ""
        return (getattr(payload, "description", None) or "").strip()

    @classmethod
    def _cover_letter_files(cls, folder, pack):
        if folder is None or not Path(folder).is_dir():
            return []
        folder = Path(folder)
        pack_key = MaterialsPackService.normalize_pack(pack)
        names = MaterialsPackService.PACK_FILES.get(pack_key) or ()
        files = []
        for name in names:
            if not cls._is_cover_letter_name(name):
                continue
            path = folder / name
            if path.is_file():
                files.append(path)
        if files:
            return files
        return [
            path
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file()
            and cls._is_cover_letter_name(path.name)
            and ".original" not in path.name.casefold()
        ]

    @staticmethod
    def _is_cover_letter_name(name):
        lowered = str(name or "").casefold()
        return "cover" in lowered and "letter" in lowered

    @classmethod
    def _read_text(cls, path):
        path = Path(path)
        try:
            text = AtsScanService.read_document_text(path)
            if text:
                return text
        except Exception:
            logger.exception("Failed to parse cover letter %s", path.name)
        try:
            return " ".join(path.read_text(encoding="utf-8", errors="ignore").split())
        except OSError:
            return ""

    @staticmethod
    def _is_drive_url(url):
        host = urlparse(url).netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        return host in GOOGLE_DRIVE_HOSTS
