from dataclasses import dataclass, field

from django.db import IntegrityError

from apps.skills.models import SkillAlias, SkillCategory, SkillSet

from .seed_data import EmergingSkillSeed, US_EMERGING_CATEGORIES, US_EMERGING_SKILLS


@dataclass
class UsEmergingSkillsSeedStats:
    skills_created: int = 0
    skills_updated: int = 0
    skills_skipped: int = 0
    aliases_created: int = 0
    aliases_updated: int = 0
    aliases_skipped: int = 0
    category_links_created: int = 0
    category_links_skipped: int = 0
    categories_created: int = 0


class UsEmergingSkillsSeeder:
    def seed(self, skills: list[EmergingSkillSeed] | None = None) -> UsEmergingSkillsSeedStats:
        stats = UsEmergingSkillsSeedStats()
        seeds = skills or US_EMERGING_SKILLS
        category_map = self._resolve_categories(stats)

        for seed in seeds:
            self._seed_skill(seed, category_map, stats)

        return stats

    def _resolve_categories(self, stats: UsEmergingSkillsSeedStats) -> dict[str, SkillCategory]:
        category_map: dict[str, SkillCategory] = {}
        for name in US_EMERGING_CATEGORIES:
            normalized = SkillSet.normalize_name(name)
            category = SkillCategory.objects.filter(normalized_name=normalized).first()
            if category is None:
                category = SkillCategory.objects.create(
                    name=name,
                    description=f"US emerging skills category: {name}",
                )
                stats.categories_created += 1
            category_map[name] = category
        return category_map

    def _seed_skill(
        self,
        seed: EmergingSkillSeed,
        category_map: dict[str, SkillCategory],
        stats: UsEmergingSkillsSeedStats,
    ):
        normalized_name = SkillSet.normalize_name(seed.name)
        if not normalized_name:
            stats.skills_skipped += 1
            return

        skill = SkillSet.objects.filter(normalized_name=normalized_name).first()
        skill_changed = False
        was_created = False
        if skill is None:
            try:
                skill = SkillSet(
                    name=seed.name,
                    normalized_name=normalized_name,
                    description=seed.description,
                    is_active=True,
                    auto_created=False,
                )
                skill.save(sync_keywords=False)
                stats.skills_created += 1
                skill_changed = True
                was_created = True
            except IntegrityError:
                skill = SkillSet.objects.filter(normalized_name=normalized_name).first()
                if skill is None:
                    stats.skills_skipped += 1
                    return
        else:
            if seed.description and not skill.description:
                skill.description = seed.description
                skill.save(update_fields=["description", "updated_at"], sync_keywords=False)
                skill_changed = True

        category = category_map.get(seed.category)
        if category is not None:
            if skill.categories.filter(id=category.id).exists():
                stats.category_links_skipped += 1
            else:
                skill.categories.add(category)
                stats.category_links_created += 1
                skill_changed = True

        merged_aliases = SkillSet.clean_aliases(
            list(skill.aliases or []) + list(seed.aliases)
        )
        if merged_aliases != (skill.aliases or []):
            skill.aliases = merged_aliases
            skill.save(update_fields=["aliases", "updated_at"], sync_keywords=False)
            skill_changed = True

        for alias_text in seed.aliases:
            self._seed_alias(alias_text, skill, stats)

        skill.sync_keywords_from_profile()

        if was_created:
            return
        if skill_changed:
            stats.skills_updated += 1
        else:
            stats.skills_skipped += 1

    def _seed_alias(
        self,
        alias_text: str,
        skill: SkillSet,
        stats: UsEmergingSkillsSeedStats,
    ):
        cleaned = " ".join(str(alias_text or "").split()).strip()
        if not cleaned:
            stats.aliases_skipped += 1
            return

        if SkillSet.normalize_name(cleaned) == skill.normalized_name:
            stats.aliases_skipped += 1
            return

        existing = SkillAlias.objects.filter(alias__iexact=cleaned).first()
        if existing is None:
            try:
                SkillAlias.objects.create(alias=cleaned, skill=skill)
                stats.aliases_created += 1
            except IntegrityError:
                stats.aliases_skipped += 1
            return

        if existing.skill_id == skill.id:
            stats.aliases_skipped += 1
            return

        existing.skill = skill
        existing.save(update_fields=["skill", "updated_at"])
        stats.aliases_updated += 1
