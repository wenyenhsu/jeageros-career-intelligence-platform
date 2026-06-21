from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count

from apps.skills.models import (
    CategoryMappingSource,
    MarketCategory,
    SkillMarketCategory,
    SkillSet,
)
from apps.skills.services.skill_intelligence.market_taxonomy_seed import MARKET_TAXONOMY
from apps.skills.services.skill_intelligence.taxonomy_matcher import TaxonomyMatcher, skills_for_ids


@dataclass
class MarketCategoryAssignmentStats:
    categories_created: int = 0
    mappings_created: int = 0
    mappings_updated: int = 0
    skills_assigned: int = 0


class MarketCategoryService:
    def seed_taxonomy(self) -> MarketCategoryAssignmentStats:
        stats = MarketCategoryAssignmentStats()
        for seed in MARKET_TAXONOMY:
            category, created = MarketCategory.objects.get_or_create(
                slug=seed.slug,
                defaults={
                    "name": seed.name,
                    "description": seed.description,
                    "is_active": True,
                },
            )
            if created:
                stats.categories_created += 1
            elif category.name != seed.name:
                category.name = seed.name
                category.description = seed.description
                category.save(update_fields=["name", "description", "updated_at"])

            assignment = self.assign_market_categories(
                category_slugs=[seed.slug],
                auto_approve=True,
                source=CategoryMappingSource.SEED,
            )
            stats.mappings_created += assignment.mappings_created
            stats.mappings_updated += assignment.mappings_updated
            stats.skills_assigned += assignment.skills_assigned
        return stats

    def assign_market_categories(
        self,
        skill_ids: set[int] | list[int] | None = None,
        category_slugs: list[str] | None = None,
        auto_approve: bool = True,
        source: str = CategoryMappingSource.AUTO,
    ) -> MarketCategoryAssignmentStats:
        stats = MarketCategoryAssignmentStats()
        categories = MarketCategory.objects.filter(is_active=True)
        if category_slugs:
            categories = categories.filter(slug__in=category_slugs)

        matcher = TaxonomyMatcher(skills=skills_for_ids(skill_ids))
        seed_by_slug = {seed.slug: seed for seed in MARKET_TAXONOMY}

        for category in categories:
            seed = seed_by_slug.get(category.slug)
            if seed is None:
                continue

            skill_matches = matcher.match_skill_names(seed.skill_names)
            pattern_matches = [
                skill for skill, _, _ in matcher.match_patterns(seed.skill_patterns)
            ]
            matched_skills = {skill.id: skill for skill in skill_matches + pattern_matches}

            for skill in matched_skills.values():
                if skill_ids is not None and skill.id not in set(skill_ids):
                    continue
                mapping, created = SkillMarketCategory.objects.get_or_create(
                    skill=skill,
                    category=category,
                    defaults={
                        "source": source,
                        "is_approved": auto_approve,
                        "confidence": 0.9,
                    },
                )
                if created:
                    stats.mappings_created += 1
                    stats.skills_assigned += 1
                else:
                    updated_fields = []
                    if auto_approve and not mapping.is_approved:
                        mapping.is_approved = True
                        updated_fields.append("is_approved")
                    if mapping.source != source and source == CategoryMappingSource.SEED:
                        mapping.source = source
                        updated_fields.append("source")
                    if updated_fields:
                        mapping.save(update_fields=[*updated_fields, "updated_at"])
                        stats.mappings_updated += 1

        return stats

    def suggest_market_categories(
        self,
        skill_id: int | None = None,
    ) -> list[dict]:
        if skill_id is not None:
            skills = list(SkillSet.objects.filter(id=skill_id, is_active=True))
        else:
            skills = list(SkillSet.objects.filter(is_active=True))

        matcher = TaxonomyMatcher(skills=skills)
        suggestions: list[dict] = []

        for seed in MARKET_TAXONOMY:
            category = MarketCategory.objects.filter(slug=seed.slug).first()
            assigned_ids = set()
            if category is not None:
                assigned_ids = set(
                    SkillMarketCategory.objects.filter(
                        category=category,
                        is_approved=True,
                    ).values_list("skill_id", flat=True)
                )

            for item in matcher.suggestions_for_seed(
                seed.name,
                seed.slug,
                seed.skill_names,
                seed.skill_patterns,
                assigned_ids,
            ):
                if skill_id is not None and item.skill_id != skill_id:
                    continue
                suggestions.append(
                    {
                        "skillset_id": item.skill_id,
                        "skill_name": item.skill_name,
                        "category": item.category_name,
                        "category_slug": item.category_slug,
                        "confidence": item.confidence,
                        "match_reason": item.match_reason,
                    }
                )

        suggestions.sort(
            key=lambda row: (-row["confidence"], row["category"].casefold())
        )
        return suggestions

    def approve_mapping(self, mapping_id: int) -> SkillMarketCategory:
        mapping = SkillMarketCategory.objects.get(pk=mapping_id)
        mapping.is_approved = True
        mapping.source = CategoryMappingSource.MANUAL
        mapping.save(update_fields=["is_approved", "source", "updated_at"])
        return mapping

    def category_counts_for_skills(
        self,
        skill_ids: set[int] | list[int],
        approved_only: bool = True,
    ) -> dict[str, int]:
        if not skill_ids:
            return {}

        links = SkillMarketCategory.objects.filter(skill_id__in=skill_ids)
        if approved_only:
            links = links.filter(is_approved=True)

        rows = (
            links.values("category__name")
            .annotate(total=Count("skill_id", distinct=True))
            .order_by("-total", "category__name")
        )
        return {row["category__name"]: row["total"] for row in rows}


def assign_market_categories(**kwargs) -> MarketCategoryAssignmentStats:
    return MarketCategoryService().assign_market_categories(**kwargs)


def suggest_market_categories(skill_id: int | None = None) -> list[dict]:
    return MarketCategoryService().suggest_market_categories(skill_id=skill_id)
