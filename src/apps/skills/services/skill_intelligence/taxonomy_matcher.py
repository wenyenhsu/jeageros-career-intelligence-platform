from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Prefetch

from apps.skills.models import SkillAlias, SkillSet


@dataclass(frozen=True)
class CategorySuggestion:
    skill_id: int
    skill_name: str
    category_name: str
    category_slug: str
    confidence: float
    match_reason: str


class TaxonomyMatcher:
    def __init__(self, skills=None):
        self.skills = list(skills or SkillSet.objects.filter(is_active=True))
        self._name_index = self._build_name_index(self.skills)

    @classmethod
    def _build_name_index(cls, skills):
        index: dict[str, list[SkillSet]] = {}
        for skill in skills:
            keys = {SkillSet.normalize_name(skill.name)}
            keys.update(SkillSet.normalize_name(alias) for alias in skill.aliases or [])
            for alias in skill.skill_aliases.all():
                keys.add(SkillSet.normalize_name(alias.alias))
            for key in keys:
                if key:
                    index.setdefault(key, []).append(skill)
        return index

    def match_skill_names(self, skill_names: list[str]) -> list[SkillSet]:
        matched: list[SkillSet] = []
        seen = set()
        for name in skill_names:
            for skill in self._name_index.get(SkillSet.normalize_name(name), []):
                if skill.id not in seen:
                    seen.add(skill.id)
                    matched.append(skill)
        return matched

    def match_patterns(self, patterns: list[str]) -> list[tuple[SkillSet, str, float]]:
        matches: list[tuple[SkillSet, str, float]] = []
        seen = set()
        for skill in self.skills:
            searchable = " ".join(
                [
                    skill.name,
                    skill.normalized_name,
                    " ".join(skill.aliases or []),
                    " ".join(
                        alias.alias for alias in skill.skill_aliases.all()
                    ),
                ]
            ).casefold()
            for pattern in patterns:
                normalized_pattern = pattern.casefold().strip()
                if not normalized_pattern or normalized_pattern not in searchable:
                    continue
                key = (skill.id, normalized_pattern)
                if key in seen:
                    continue
                seen.add(key)
                confidence = 0.85 if len(normalized_pattern) >= 8 else 0.7
                matches.append((skill, normalized_pattern, confidence))
        return matches

    def suggestions_for_seed(
        self,
        category_name: str,
        category_slug: str,
        skill_names: list[str],
        skill_patterns: list[str],
        assigned_skill_ids: set[int],
    ) -> list[CategorySuggestion]:
        suggestions: list[CategorySuggestion] = []
        seen = set()

        for skill in self.match_skill_names(skill_names):
            if skill.id in assigned_skill_ids or skill.id in seen:
                continue
            seen.add(skill.id)
            suggestions.append(
                CategorySuggestion(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    category_name=category_name,
                    category_slug=category_slug,
                    confidence=0.95,
                    match_reason=f"exact skill match: {skill.name}",
                )
            )

        for skill, pattern, confidence in self.match_patterns(skill_patterns):
            if skill.id in assigned_skill_ids or skill.id in seen:
                continue
            seen.add(skill.id)
            suggestions.append(
                CategorySuggestion(
                    skill_id=skill.id,
                    skill_name=skill.name,
                    category_name=category_name,
                    category_slug=category_slug,
                    confidence=confidence,
                    match_reason=f"pattern match: {pattern}",
                )
            )
        return suggestions


def skills_for_ids(skill_ids: set[int] | list[int] | None = None):
    queryset = SkillSet.objects.filter(is_active=True).prefetch_related(
        Prefetch("skill_aliases", queryset=SkillAlias.objects.all())
    )
    if skill_ids is not None:
        queryset = queryset.filter(id__in=skill_ids)
    return queryset
