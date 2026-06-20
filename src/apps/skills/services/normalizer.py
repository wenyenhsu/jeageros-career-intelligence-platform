from dataclasses import dataclass

from rapidfuzz import fuzz, process

from apps.skills.models import SkillAlias, SkillSet

from .ollama_mapper import OllamaSkillMapper, OllamaSkillMappingError


@dataclass(frozen=True)
class SkillMappingResult:
    """Stable result contract for one raw-to-canonical skill mapping attempt."""

    original: str
    canonical: str | None
    confidence: float
    source: str
    reason: str


class SkillNormalizer:
    """Normalize raw extracted skill names into canonical SkillSet names.

    Resolution is intentionally ordered from deterministic local matches to the
    slower model fallback: SkillAlias, exact SkillSet name, fuzzy SkillSet name,
    then Ollama.
    """

    def __init__(self, fuzzy_threshold=90, ollama_mapper=None):
        self.fuzzy_threshold = fuzzy_threshold
        self.ollama_mapper = ollama_mapper or OllamaSkillMapper()

    def normalize(self, raw_skill: str) -> SkillMappingResult:
        """Resolve one raw skill through alias, exact, fuzzy, then Ollama."""
        original = str(raw_skill or "").strip()
        cleaned = self._clean_skill_name(raw_skill)
        if not cleaned:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=0.0,
                source="empty",
                reason="Skill name is empty.",
            )

        alias_match = self._alias_match(cleaned)
        if alias_match:
            return self._result(
                original=original,
                skill=alias_match,
                confidence=1.0,
                source="alias",
                reason="Matched SkillAlias exactly.",
            )

        exact_match = self._exact_skill_match(cleaned)
        if exact_match:
            return self._result(
                original=original,
                skill=exact_match,
                confidence=1.0,
                source="exact",
                reason="Matched SkillSet name exactly.",
            )

        fuzzy_match = self._fuzzy_match(cleaned)
        if fuzzy_match:
            skill, score = fuzzy_match
            return self._result(
                original=original,
                skill=skill,
                confidence=round(score / 100, 4),
                source="fuzzy",
                reason=f"Fuzzy matched SkillSet name with score {score:.1f}.",
            )

        return self._ollama_fallback(original=original, cleaned=cleaned)

    def normalize_skills(self, raw_skills: list[str]) -> list[SkillMappingResult]:
        """Normalize a batch while preserving input order."""
        return [self.normalize(raw_skill) for raw_skill in raw_skills or []]

    @staticmethod
    def _clean_skill_name(raw_skill):
        return " ".join(str(raw_skill or "").split()).strip(" .,;:|/\\")

    @staticmethod
    def _alias_match(cleaned):
        alias = (
            SkillAlias.objects.select_related("skill")
            .filter(alias__iexact=cleaned)
            .first()
        )
        return alias.skill if alias else None

    @staticmethod
    def _exact_skill_match(cleaned):
        normalized_name = SkillSet.normalize_name(cleaned)
        return SkillSet.objects.filter(normalized_name=normalized_name).first()

    def _fuzzy_match(self, cleaned):
        skills = list(SkillSet.objects.all())
        if not skills:
            return None
        index = {skill.normalized_name: skill for skill in skills}
        match = process.extractOne(
            SkillSet.normalize_name(cleaned),
            list(index),
            scorer=fuzz.WRatio,
            score_cutoff=self.fuzzy_threshold,
        )
        if not match:
            return None
        normalized_name, score, _ = match
        return index[normalized_name], score

    def _ollama_fallback(self, original, cleaned):
        skills = list(SkillSet.objects.order_by("name"))
        try:
            mapping = self.ollama_mapper.map(
                cleaned,
                canonical_options=[skill.name for skill in skills],
            )
        except OllamaSkillMappingError as exc:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=0.0,
                source="ollama_error",
                reason=str(exc),
            )

        canonical = mapping.canonical
        if not canonical:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=mapping.confidence,
                source="ollama",
                reason=mapping.reason or "Ollama did not find a canonical match.",
            )

        matched_skill = self._exact_skill_match(canonical)
        if not matched_skill:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=mapping.confidence,
                source="ollama",
                reason=(
                    f"Ollama suggested {canonical}, but no matching SkillSet exists."
                ),
            )

        return self._result(
            original=original,
            skill=matched_skill,
            confidence=mapping.confidence,
            source="ollama",
            reason=mapping.reason or "Mapped by Ollama fallback.",
        )

    @staticmethod
    def _result(original, skill, confidence, source, reason):
        return SkillMappingResult(
            original=original,
            canonical=skill.name,
            confidence=confidence,
            source=source,
            reason=reason,
        )


def normalize_skills(raw_skills: list[str]) -> list[SkillMappingResult]:
    """Convenience batch API for callers that do not need custom settings."""
    return SkillNormalizer().normalize_skills(raw_skills)
