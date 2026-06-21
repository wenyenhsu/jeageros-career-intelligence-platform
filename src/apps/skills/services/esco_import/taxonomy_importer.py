import logging
from dataclasses import dataclass
from pathlib import Path

from apps.skills.models import SkillCategory, SkillSet

from .csv_reader import REQUIRED_FIELDS_BY_GROUP, read_esco_csv
from .paths import (
    BROADER_RELATIONS_FILE_NAMES,
    SKILL_GROUPS_FILE_NAMES,
    resolve_esco_file,
)

logger = logging.getLogger(__name__)


@dataclass
class EscoTaxonomyImportStats:
    categories_created: int = 0
    categories_updated: int = 0
    categories_skipped: int = 0
    hierarchy_links_created: int = 0
    hierarchy_links_skipped: int = 0
    skill_links_created: int = 0
    skill_links_skipped: int = 0


class EscoTaxonomyImporter:
    MAX_NAME_LENGTH = 120
    PROGRESS_INTERVAL = 1000

    def __init__(self, data_dir: Path, progress_callback=None):
        self.data_dir = data_dir
        self.progress_callback = progress_callback

    def import_taxonomy(self) -> EscoTaxonomyImportStats:
        stats = EscoTaxonomyImportStats()
        groups_path = resolve_esco_file(self.data_dir, SKILL_GROUPS_FILE_NAMES)
        if groups_path is None:
            raise FileNotFoundError(
                f"No ESCO skill groups CSV found in {self.data_dir}. "
                f"Expected one of: {', '.join(SKILL_GROUPS_FILE_NAMES)}"
            )

        rows, _ = read_esco_csv(
            groups_path,
            required_fields=REQUIRED_FIELDS_BY_GROUP["skill_groups"],
        )
        category_by_uri: dict[str, SkillCategory] = {
            category.esco_uri: category
            for category in SkillCategory.objects.filter(esco_uri__isnull=False)
        }
        category_by_normalized_root: dict[str, SkillCategory] = {
            category.normalized_name: category
            for category in SkillCategory.objects.filter(parent__isnull=True)
        }

        total = len(rows)
        for index, row in enumerate(rows, start=1):
            if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                self._report_progress(index, total, "categories")

            esco_uri = row.get("concept_uri") or ""
            name = self._truncate_name(self._clean_label(row.get("preferred_label") or ""))
            if not name:
                stats.categories_skipped += 1
                continue

            description = (row.get("description") or "").strip()
            normalized_name = SkillSet.normalize_name(name)
            category = category_by_uri.get(esco_uri) if esco_uri else None
            if category is None:
                category = category_by_normalized_root.get(normalized_name)

            if category is None:
                category = SkillCategory.objects.create(
                    name=name,
                    description=description,
                    esco_uri=esco_uri or None,
                )
                stats.categories_created += 1
            else:
                updated_fields = []
                if esco_uri and category.esco_uri != esco_uri:
                    category.esco_uri = esco_uri
                    updated_fields.append("esco_uri")
                if description and category.description != description:
                    category.description = description
                    updated_fields.append("description")
                if updated_fields:
                    category.save(update_fields=updated_fields + ["updated_at"])
                    stats.categories_updated += 1
                else:
                    stats.categories_skipped += 1

            if esco_uri:
                category_by_uri[esco_uri] = category
            if category.parent_id is None:
                category_by_normalized_root[normalized_name] = category

        broader_path = resolve_esco_file(self.data_dir, BROADER_RELATIONS_FILE_NAMES)
        if broader_path is None:
            return stats

        broader_rows, _ = read_esco_csv(
            broader_path,
            required_fields=REQUIRED_FIELDS_BY_GROUP["broader_relations"],
        )
        skill_by_uri = {
            skill.esco_uri: skill
            for skill in SkillSet.objects.filter(esco_uri__isnull=False)
        }
        existing_skill_category_pairs = set(
            SkillSet.categories.through.objects.values_list(
                "skillset_id",
                "skillcategory_id",
            )
        )

        total = len(broader_rows)
        for index, row in enumerate(broader_rows, start=1):
            if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                self._report_progress(index, total, "taxonomy-links")

            narrower_uri = row.get("concept_uri") or ""
            broader_uri = row.get("broader_uri") or ""
            if not narrower_uri or not broader_uri:
                stats.hierarchy_links_skipped += 1
                continue

            narrower_skill = skill_by_uri.get(narrower_uri)
            broader_category = category_by_uri.get(broader_uri)
            narrower_category = category_by_uri.get(narrower_uri)
            broader_category_parent = category_by_uri.get(broader_uri)

            if narrower_skill and broader_category:
                pair = (narrower_skill.id, broader_category.id)
                if pair in existing_skill_category_pairs:
                    stats.skill_links_skipped += 1
                else:
                    narrower_skill.categories.add(broader_category)
                    existing_skill_category_pairs.add(pair)
                    stats.skill_links_created += 1
                continue

            if narrower_category and broader_category_parent:
                if narrower_category.parent_id == broader_category_parent.id:
                    stats.hierarchy_links_skipped += 1
                else:
                    narrower_category.parent = broader_category_parent
                    narrower_category.save(update_fields=["parent", "updated_at"])
                    stats.hierarchy_links_created += 1
                continue

            stats.hierarchy_links_skipped += 1

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
