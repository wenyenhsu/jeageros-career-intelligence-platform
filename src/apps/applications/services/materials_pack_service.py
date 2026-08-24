import logging
import shutil
from pathlib import Path

from django.conf import settings

from .materials_folder_service import MaterialsFolderService

logger = logging.getLogger(__name__)


class MaterialsPackError(ValueError):
    pass


class MaterialsPackService:
    PACK_FILES = {
        "AI": (
            "Cover_Letter_AI.pdf",
            "WenYenHsu_Resume_AI.pdf",
            "Cover_Letter_AI.docx",
            "WenYenHsu_Resume_AI.docx",
        ),
        "INFRA": (
            "Cover_Letter_infra.pdf",
            "WenYenHsu_Resume_infra.pdf",
            "Cover_Letter_infra.docx",
            "WenYenHsu_Resume_infra.docx",
        ),
    }

    def apply_pack(self, application, pack):
        pack_key = self.normalize_pack(pack)
        if not pack_key:
            raise MaterialsPackError("Choose AI or Infra.")

        source_dir = self.template_root()
        if source_dir is None or not source_dir.is_dir():
            raise MaterialsPackError("Resume template folder was not found.")

        MaterialsFolderService().ensure_folders(application)
        dest_dir = MaterialsFolderService.local_path_for(application)
        if dest_dir is None:
            raise MaterialsPackError("Application is missing a local materials folder.")
        dest_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        missing = []
        for filename in self.PACK_FILES[pack_key]:
            source = self._resolve_source_file(source_dir, filename)
            if source is None:
                missing.append(filename)
                continue
            shutil.copy2(source, dest_dir / source.name)
            copied.append(source.name)

        if not copied:
            raise MaterialsPackError(
                f"No {pack_key} template files were found in {source_dir}."
            )

        application.materials_pack = pack_key
        application.save(update_fields=["materials_pack", "last_updated_at"])
        return {
            "pack": pack_key,
            "copied": copied,
            "missing": missing,
            "destination": str(dest_dir),
            "source": str(source_dir),
        }

    @classmethod
    def normalize_pack(cls, pack):
        value = str(pack or "").strip().casefold()
        if value in {"ai"}:
            return "AI"
        if value in {"infra", "infrastructure"}:
            return "INFRA"
        return ""

    @classmethod
    def template_root(cls):
        configured = Path(getattr(settings, "RESUME_TEMPLATE_ROOT", "") or "")
        candidates = []
        if str(configured):
            candidates.append(configured)
        materials_root = Path(
            getattr(settings, "APPLICATION_MATERIALS_ROOT", "") or ""
        )
        if str(materials_root):
            candidates.append(materials_root / "resume_golden_template")
            candidates.append(materials_root / "resume＿golden_template")
            if materials_root.is_dir():
                candidates.extend(
                    path
                    for path in materials_root.iterdir()
                    if path.is_dir() and "golden" in path.name.casefold()
                )
        for path in candidates:
            if path.is_dir():
                return path
        return configured if str(configured) else None

    @staticmethod
    def _resolve_source_file(source_dir, filename):
        exact = source_dir / filename
        if exact.is_file():
            return exact
        wanted = filename.casefold()
        for path in source_dir.iterdir():
            if path.is_file() and path.name.casefold() == wanted:
                return path
        return None
