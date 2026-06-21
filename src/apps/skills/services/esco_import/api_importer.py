from dataclasses import dataclass

from apps.skills.models import SkillCategory, SkillSet

from .alias_importer import EscoAliasImportStats, EscoAliasImporter
from .api_client import EscoApiClient


@dataclass
class EscoApiImportStats:
    skills_created: int = 0
    skills_updated: int = 0
    skills_skipped: int = 0
    aliases_created: int = 0
    aliases_skipped: int = 0
    categories_created: int = 0
    categories_updated: int = 0
    categories_skipped: int = 0
    hierarchy_links_created: int = 0
    skill_category_links_created: int = 0


class EscoApiImporter:
    MAX_NAME_LENGTH = 120

    def __init__(self, language: str = "en"):
        self.client = EscoApiClient(language=language)
        self.alias_helper = EscoAliasImporter.__new__(EscoAliasImporter)

    def import_all(self) -> EscoApiImportStats:
        stats = EscoApiImportStats()
        category_by_uri = self._import_hierarchy_categories(stats)
        self._import_member_skills(stats, category_by_uri)
        return stats

    def _import_hierarchy_categories(self, stats: EscoApiImportStats) -> dict[str, SkillCategory]:
        category_by_uri: dict[str, SkillCategory] = {
            category.esco_uri: category
            for category in SkillCategory.objects.filter(esco_uri__isnull=False)
        }
        pending_parents: list[tuple[str, str]] = []

        for batch in self.client.iter_scheme_skills(self.client.SKILLS_HIERARCHY_SCHEME):
            for item in batch:
                uri = item.get("uri") or ""
                name = self._truncate(self.client.pick_english_label(item.get("preferredLabel")))
                if not uri or not name:
                    stats.categories_skipped += 1
                    continue

                description = self.client.pick_english_description(item.get("description"))
                category = category_by_uri.get(uri)
                if category is None:
                    category = SkillCategory.objects.filter(
                        parent__isnull=True,
                        normalized_name=SkillSet.normalize_name(name),
                    ).first()

                if category is None:
                    category = SkillCategory.objects.create(
                        name=name,
                        description=description,
                        esco_uri=uri,
                    )
                    stats.categories_created += 1
                else:
                    updated_fields = []
                    if category.esco_uri != uri:
                        category.esco_uri = uri
                        updated_fields.append("esco_uri")
                    if description and category.description != description:
                        category.description = description
                        updated_fields.append("description")
                    if updated_fields:
                        category.save(update_fields=updated_fields + ["updated_at"])
                        stats.categories_updated += 1
                    else:
                        stats.categories_skipped += 1

                category_by_uri[uri] = category
                for broader_uri in self.client.link_uris(item.get("_links"), ("broaderConcept",)):
                    pending_parents.append((uri, broader_uri))

        for child_uri, parent_uri in pending_parents:
            child = category_by_uri.get(child_uri)
            parent = category_by_uri.get(parent_uri)
            if child is None or parent is None:
                continue
            if child.parent_id == parent.id:
                continue
            child.parent = parent
            child.save(update_fields=["parent", "updated_at"])
            stats.hierarchy_links_created += 1

        return category_by_uri

    def _import_member_skills(
        self,
        stats: EscoApiImportStats,
        category_by_uri: dict[str, SkillCategory],
    ):
        alias_stats = EscoAliasImportStats()

        for batch in self.client.iter_scheme_skills(self.client.SKILLS_SCHEME):
            for item in batch:
                uri = item.get("uri") or ""
                name = self._truncate(self.client.pick_english_label(item.get("preferredLabel")))
                if not uri or not name:
                    stats.skills_skipped += 1
                    continue

                description = self.client.pick_english_description(item.get("description"))
                skill = SkillSet.objects.filter(esco_uri=uri).first()
                if skill is None:
                    skill = SkillSet.objects.filter(
                        normalized_name=SkillSet.normalize_name(name)
                    ).first()

                if skill is None:
                    skill = SkillSet.objects.create(
                        name=name,
                        description=description,
                        esco_uri=uri,
                        is_active=True,
                        auto_created=False,
                    )
                    stats.skills_created += 1
                else:
                    updated_fields = []
                    if skill.esco_uri != uri:
                        skill.esco_uri = uri
                        updated_fields.append("esco_uri")
                    if description and skill.description != description:
                        skill.description = description
                        updated_fields.append("description")
                    if updated_fields:
                        skill.save(update_fields=updated_fields + ["updated_at"])
                        stats.skills_updated += 1
                    else:
                        stats.skills_skipped += 1

                for alt_label in self.client.pick_english_alt_labels(
                    item.get("alternativeLabel")
                ):
                    self.alias_helper._import_alias(alt_label, skill, alias_stats)

                for category_uri in self.client.link_uris(
                    item.get("_links"),
                    ("broaderHierarchyConcept",),
                ):
                    category = category_by_uri.get(category_uri)
                    if category is None:
                        continue
                    if not skill.categories.filter(id=category.id).exists():
                        skill.categories.add(category)
                        stats.skill_category_links_created += 1

        stats.aliases_created = alias_stats.created
        stats.aliases_skipped = alias_stats.skipped + alias_stats.updated

    @classmethod
    def _truncate(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split()).strip()
        if len(cleaned) <= cls.MAX_NAME_LENGTH:
            return cleaned
        return cleaned[:cls.MAX_NAME_LENGTH].rstrip()
