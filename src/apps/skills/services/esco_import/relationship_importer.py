import logging
from dataclasses import dataclass
from pathlib import Path

from apps.skills.models import SkillRelationship, SkillSet

from .csv_reader import REQUIRED_FIELDS_BY_GROUP, read_esco_csv
from .paths import (
    BROADER_RELATIONS_FILE_NAMES,
    SKILL_SKILL_RELATIONS_FILE_NAMES,
    resolve_esco_file,
)

logger = logging.getLogger(__name__)


@dataclass
class EscoRelationshipImportStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class EscoRelationshipImporter:
    PROGRESS_INTERVAL = 2000

    def __init__(self, data_dir: Path, progress_callback=None):
        self.data_dir = data_dir
        self.progress_callback = progress_callback

    def import_relationships(self) -> EscoRelationshipImportStats:
        stats = EscoRelationshipImportStats()
        skill_by_uri = {
            skill.esco_uri: skill
            for skill in SkillSet.objects.filter(esco_uri__isnull=False)
        }
        existing_keys = set(
            SkillRelationship.objects.values_list(
                "source_skill_id",
                "target_skill_id",
                "relationship_type",
            )
        )

        skill_skill_path = resolve_esco_file(
            self.data_dir, SKILL_SKILL_RELATIONS_FILE_NAMES
        )
        if skill_skill_path:
            rows, _ = read_esco_csv(
                skill_skill_path,
                required_fields=REQUIRED_FIELDS_BY_GROUP["skill_skill_relations"],
            )
            total = len(rows)
            for index, row in enumerate(rows, start=1):
                if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                    self._report_progress(index, total, "skill-relations")

                source_uri = row.get("concept_uri") or ""
                target_uri = row.get("related_uri") or ""
                if not source_uri or not target_uri:
                    stats.skipped += 1
                    continue
                relation_type = self._normalize_relation_type(
                    row.get("relation_type") or "related"
                )
                self._import_pair(
                    skill_by_uri,
                    source_uri,
                    target_uri,
                    relation_type,
                    stats,
                    existing_keys,
                )

        broader_path = resolve_esco_file(self.data_dir, BROADER_RELATIONS_FILE_NAMES)
        if broader_path:
            rows, _ = read_esco_csv(
                broader_path,
                required_fields=REQUIRED_FIELDS_BY_GROUP["broader_relations"],
            )
            total = len(rows)
            for index, row in enumerate(rows, start=1):
                if index == 1 or index % self.PROGRESS_INTERVAL == 0 or index == total:
                    self._report_progress(index, total, "broader-relations")

                narrower_uri = row.get("concept_uri") or ""
                broader_uri = row.get("broader_uri") or ""
                narrower = skill_by_uri.get(narrower_uri)
                broader = skill_by_uri.get(broader_uri)
                if narrower is None or broader is None:
                    stats.skipped += 1
                    continue
                self._upsert_relationship(
                    narrower,
                    broader,
                    SkillRelationship.RelationshipType.NARROWER,
                    stats,
                    existing_keys,
                )
                self._upsert_relationship(
                    broader,
                    narrower,
                    SkillRelationship.RelationshipType.BROADER,
                    stats,
                    existing_keys,
                )

        return stats

    def _import_pair(
        self,
        skill_by_uri: dict[str, SkillSet],
        source_uri: str,
        target_uri: str,
        relation_type: str,
        stats: EscoRelationshipImportStats,
        existing_keys: set[tuple[int, int, str]],
    ):
        source_skill = skill_by_uri.get(source_uri)
        target_skill = skill_by_uri.get(target_uri)
        if source_skill is None or target_skill is None:
            stats.skipped += 1
            return
        self._upsert_relationship(
            source_skill, target_skill, relation_type, stats, existing_keys
        )

    def _upsert_relationship(
        self,
        source_skill: SkillSet,
        target_skill: SkillSet,
        relationship_type: str,
        stats: EscoRelationshipImportStats,
        existing_keys: set[tuple[int, int, str]],
    ):
        if source_skill.id == target_skill.id:
            stats.skipped += 1
            return

        key = (source_skill.id, target_skill.id, relationship_type)
        if key in existing_keys:
            stats.skipped += 1
            return

        SkillRelationship.objects.create(
            source_skill=source_skill,
            target_skill=target_skill,
            relationship_type=relationship_type,
        )
        existing_keys.add(key)
        stats.created += 1

    def _report_progress(self, current: int, total: int, stage: str):
        if self.progress_callback:
            self.progress_callback(current, total, stage)
        else:
            logger.info("ESCO import %s: %s/%s", stage, current, total)

    @classmethod
    def _normalize_relation_type(cls, value: str) -> str:
        normalized = str(value or "").strip().casefold()
        if normalized in {"broader", "broader than", "broaderthan"}:
            return SkillRelationship.RelationshipType.BROADER
        if normalized in {"narrower", "narrower than", "narrowerthan"}:
            return SkillRelationship.RelationshipType.NARROWER
        return SkillRelationship.RelationshipType.RELATED
