import logging
from dataclasses import dataclass
from pathlib import Path

from apps.skills.models import SkillAlias, SkillSet

from .csv_reader import REQUIRED_FIELDS_BY_GROUP, read_esco_csv, split_alt_labels
from .paths import SKILLS_FILE_NAMES, resolve_esco_file

logger = logging.getLogger(__name__)


@dataclass
class EscoAliasImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class EscoAliasImporter:
    MAX_ALIAS_LENGTH = 120
    PROGRESS_INTERVAL = 2000

    def __init__(self, data_dir: Path, progress_callback=None):
        self.data_dir = data_dir
        self.progress_callback = progress_callback

    def import_aliases(self) -> EscoAliasImportStats:
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
        stats = EscoAliasImportStats()
        skill_by_uri = {
            skill.esco_uri: skill
            for skill in SkillSet.objects.filter(esco_uri__isnull=False)
        }
        skill_by_name = {
            skill.normalized_name: skill for skill in SkillSet.objects.all()
        }
        alias_by_text: dict[str, SkillAlias] = {}
        for alias in SkillAlias.objects.select_related("skill").all():
            alias_by_text[alias.alias.casefold()] = alias

        total = len(rows)
        for index, row in enumerate(rows, start=1):
            if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                self._report_progress(index, total, "aliases")

            preferred_label = self._clean_label(row.get("preferred_label") or "")
            if not preferred_label:
                continue

            esco_uri = row.get("concept_uri") or ""
            skill = skill_by_uri.get(esco_uri)
            if skill is None:
                skill = skill_by_name.get(SkillSet.normalize_name(preferred_label))
            if skill is None:
                alt_labels = split_alt_labels(row.get("alt_labels") or "")
                stats.skipped += len(alt_labels) if alt_labels else 1
                continue

            alt_labels = split_alt_labels(row.get("alt_labels") or "")
            for alt_label in alt_labels:
                self._import_alias(alt_label, skill, stats, alias_by_text)

        return stats

    def _import_alias(
        self,
        alt_label: str,
        skill: SkillSet,
        stats: EscoAliasImportStats,
        alias_by_text: dict[str, SkillAlias],
    ):
        alias_text = self._truncate_alias(self._clean_label(alt_label))
        if not alias_text:
            stats.skipped += 1
            return

        if SkillSet.normalize_name(alias_text) == skill.normalized_name:
            stats.skipped += 1
            return

        existing = alias_by_text.get(alias_text.casefold())
        if existing is None:
            alias = SkillAlias.objects.create(alias=alias_text, skill=skill)
            alias_by_text[alias_text.casefold()] = alias
            stats.created += 1
            return

        if existing.skill_id == skill.id:
            stats.skipped += 1
            return

        existing.skill = skill
        existing.save(update_fields=["skill", "updated_at"])
        stats.updated += 1

    def _report_progress(self, current: int, total: int, stage: str):
        if self.progress_callback:
            self.progress_callback(current, total, stage)
        else:
            logger.info("ESCO import %s: %s/%s", stage, current, total)

    @classmethod
    def _clean_label(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()

    @classmethod
    def _truncate_alias(cls, value: str) -> str:
        cleaned = cls._clean_label(value)
        if len(cleaned) <= cls.MAX_ALIAS_LENGTH:
            return cleaned
        return cleaned[:cls.MAX_ALIAS_LENGTH].rstrip()
