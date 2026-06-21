from dataclasses import dataclass, field

from apps.skills.models import SkillAlias, SkillCategory, SkillRelationship, SkillSet


@dataclass
class SkillKnowledgeBaseReport:
    skillset_count: int = 0
    skill_alias_count: int = 0
    skill_category_count: int = 0
    skill_relationship_count: int = 0
    missing_categories: list[str] = field(default_factory=list)
    orphan_skills: list[str] = field(default_factory=list)
    duplicate_aliases: list[str] = field(default_factory=list)


class SkillKnowledgeBaseValidator:
    def validate(self) -> SkillKnowledgeBaseReport:
        report = SkillKnowledgeBaseReport(
            skillset_count=SkillSet.objects.count(),
            skill_alias_count=SkillAlias.objects.count(),
            skill_category_count=SkillCategory.objects.count(),
            skill_relationship_count=SkillRelationship.objects.count(),
        )

        report.missing_categories = self._missing_category_parents()
        report.orphan_skills = self._orphan_skills()
        report.duplicate_aliases = self._duplicate_aliases()
        return report

    def _missing_category_parents(self) -> list[str]:
        parent_ids = set(
            SkillCategory.objects.filter(parent__isnull=False).values_list(
                "parent_id", flat=True
            )
        )
        existing_ids = set(
            SkillCategory.objects.filter(id__in=parent_ids).values_list("id", flat=True)
        )
        missing_ids = parent_ids - existing_ids
        if not missing_ids:
            return []
        return sorted(
            SkillCategory.objects.filter(id__in=missing_ids).values_list(
                "name", flat=True
            )
        )

    def _orphan_skills(self) -> list[str]:
        return list(
            SkillSet.objects.filter(
                categories__isnull=True,
                outgoing_relationships__isnull=True,
                incoming_relationships__isnull=True,
            )
            .distinct()
            .order_by("name")
            .values_list("name", flat=True)
        )

    def _duplicate_aliases(self) -> list[str]:
        normalized_map: dict[str, list[str]] = {}
        for alias in SkillAlias.objects.all():
            key = SkillSet.normalize_name(alias.alias)
            normalized_map.setdefault(key, []).append(alias.alias)

        duplicates = []
        for key, aliases in normalized_map.items():
            unique_aliases = sorted(set(aliases))
            if len(unique_aliases) > 1:
                duplicates.append(f"{key}: {', '.join(unique_aliases)}")
        return duplicates
