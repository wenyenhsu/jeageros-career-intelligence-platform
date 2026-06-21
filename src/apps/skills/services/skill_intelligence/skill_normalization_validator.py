from dataclasses import dataclass, field

from apps.skills.models import SkillAlias, SkillRelationship, SkillSet
from apps.skills.services.skill_intelligence.db_utils import intelligence_layer_tables_exist


@dataclass
class SkillNormalizationReport:
    unresolved_aliases: list[str] = field(default_factory=list)
    duplicate_canonical_skills: list[str] = field(default_factory=list)
    orphan_relationships: list[str] = field(default_factory=list)


class SkillNormalizationValidator:
    def validate(self) -> SkillNormalizationReport:
        return SkillNormalizationReport(
            unresolved_aliases=self._unresolved_aliases(),
            duplicate_canonical_skills=self._duplicate_canonical_skills(),
            orphan_relationships=self._orphan_relationships(),
        )

    def _unresolved_aliases(self) -> list[str]:
        unresolved = []
        canonical_names = set(
            SkillSet.objects.values_list("normalized_name", flat=True)
        )

        for alias in SkillAlias.objects.select_related("skill"):
            normalized_alias = SkillSet.normalize_name(alias.alias)
            if not normalized_alias:
                unresolved.append(f"{alias.alias} -> (empty target)")
                continue
            if (
                normalized_alias in canonical_names
                and normalized_alias != alias.skill.normalized_name
            ):
                canonical = SkillSet.objects.filter(
                    normalized_name=normalized_alias
                ).first()
                unresolved.append(
                    f"{alias.alias} -> {alias.skill.name} "
                    f"(canonical match: {canonical.name if canonical else normalized_alias})"
                )
        return sorted(unresolved)

    def _duplicate_canonical_skills(self) -> list[str]:
        duplicates = []
        alias_index: dict[str, list[str]] = {}

        for skill in SkillSet.objects.all():
            keys = {skill.normalized_name}
            keys.update(SkillSet.normalize_name(alias) for alias in skill.aliases or [])
            for alias in skill.skill_aliases.all():
                keys.add(SkillSet.normalize_name(alias.alias))
            for key in keys:
                if key:
                    alias_index.setdefault(key, []).append(skill.name)

        for key, names in alias_index.items():
            unique_names = sorted(set(names))
            if len(unique_names) > 1:
                duplicates.append(f"{key}: {', '.join(unique_names)}")
        return sorted(duplicates)

    def _orphan_relationships(self) -> list[str]:
        orphans = []
        for relationship in SkillRelationship.objects.select_related(
            "source_skill",
            "target_skill",
        ):
            source = relationship.source_skill
            target = relationship.target_skill
            if not source.is_active or not target.is_active:
                orphans.append(
                    f"{source.name} -[{relationship.relationship_type}]-> {target.name} "
                    "(inactive endpoint)"
                )
                continue

            source_links = self._skill_has_classification(source)
            target_links = self._skill_has_classification(target)
            if not source_links or not target_links:
                orphans.append(
                    f"{source.name} -[{relationship.relationship_type}]-> {target.name} "
                    "(unclassified endpoint)"
                )
        return sorted(orphans)

    def _skill_has_classification(self, skill: SkillSet) -> bool:
        if skill.categories.exists():
            return True
        if not intelligence_layer_tables_exist():
            return False
        return (
            skill.business_category_links.filter(is_approved=True).exists()
            or skill.market_category_links.filter(is_approved=True).exists()
        )
