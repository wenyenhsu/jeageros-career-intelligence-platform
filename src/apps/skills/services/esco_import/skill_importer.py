import logging
from dataclasses import dataclass
from pathlib import Path

from django.db import IntegrityError

from apps.skills.models import SkillSet

from .csv_reader import REQUIRED_FIELDS_BY_GROUP, read_esco_csv
from .paths import SKILLS_FILE_NAMES, resolve_esco_file

logger = logging.getLogger(__name__)


@dataclass
class EscoSkillImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


class EscoSkillImporter:
    MAX_NAME_LENGTH = 120
    PROGRESS_INTERVAL = 1000

    def __init__(self, data_dir: Path, progress_callback=None):
        self.data_dir = data_dir
        self.progress_callback = progress_callback

    def import_skills(self) -> EscoSkillImportStats:
        skills_path = resolve_esco_file(self.data_dir, SKILLS_FILE_NAMES)
        if skills_path is None:
            raise FileNotFoundError(
                f"No ESCO skills CSV found in {self.data_dir}. "
                f"Expected one of: {', '.join(SKILLS_FILE_NAMES)}"
            )

        rows, _ = read_esco_csv(
            skills_path,
            required_fields=REQUIRED_FIELDS_BY_GROUP["skills"],
        )
        stats = EscoSkillImportStats()
        skill_by_uri: dict[str, SkillSet] = {
            skill.esco_uri: skill
            for skill in SkillSet.objects.filter(esco_uri__isnull=False)
        }
        skill_by_normalized: dict[str, SkillSet] = {
            skill.normalized_name: skill for skill in SkillSet.objects.all()
        }
        total = len(rows)

        for index, row in enumerate(rows, start=1):
            if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                self._report_progress(index, total, "skills")

            concept_type = (row.get("concept_type") or "").casefold()
            if concept_type and "group" in concept_type:
                stats.skipped += 1
                continue

            preferred_label = self._clean_label(row.get("preferred_label") or "")
            if not preferred_label:
                stats.skipped += 1
                continue

            esco_uri = row.get("concept_uri") or ""
            description = (row.get("description") or "").strip()
            name = self._truncate_name(preferred_label)
            if not name:
                stats.skipped += 1
                continue

            normalized_name = SkillSet.normalize_name(name)
            skill = skill_by_uri.get(esco_uri) if esco_uri else None
            if skill is None:
                skill = skill_by_normalized.get(normalized_name)

            if skill is None:
                try:
                    skill = SkillSet(
                        name=name,
                        normalized_name=normalized_name,
                        description=description,
                        esco_uri=esco_uri or None,
                        is_active=True,
                        auto_created=False,
                    )
                    skill.save(sync_keywords=False)
                except IntegrityError:
                    skill = SkillSet.objects.filter(normalized_name=normalized_name).first()
                    if skill is None:
                        stats.errors += 1
                        continue

                if esco_uri:
                    skill_by_uri[esco_uri] = skill
                skill_by_normalized[normalized_name] = skill
                stats.created += 1
                continue

            updated_fields = []
            if esco_uri and skill.esco_uri != esco_uri:
                skill.esco_uri = esco_uri
                updated_fields.append("esco_uri")
                skill_by_uri[esco_uri] = skill

            if description and skill.description != description:
                skill.description = description
                updated_fields.append("description")

            if updated_fields:
                skill.save(
                    update_fields=updated_fields + ["updated_at"],
                    sync_keywords=False,
                )
                stats.updated += 1
            else:
                stats.skipped += 1

            skill_by_normalized[skill.normalized_name] = skill

        return stats

    def _report_progress(self, current: int, total: int, stage: str):
        if self.progress_callback:
            self.progress_callback(current, total, stage)
        else:
            logger.info("ESCO import %s: %s/%s", stage, current, total)

    @classmethod
    def _clean_label(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def _truncate_name(cls, value: str) -> str:
        cleaned = cls._clean_label(value)
        if len(cleaned) <= cls.MAX_NAME_LENGTH:
            return cleaned
        return cleaned[:cls.MAX_NAME_LENGTH].rstrip()
