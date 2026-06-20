import logging
import re
from dataclasses import dataclass

from django.db import DatabaseError

from apps.skills.models import SkillAlias, SkillSet

from .embedding_service import EmbeddingServiceError
from .normalizer import SkillMappingResult
from .ollama_mapper import OllamaSkillMapper, OllamaSkillMappingError
from .vector_search import get_similar_skills

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievedSkillCandidate:
    skill: SkillSet
    source: str
    confidence: float
    reason: str


class SkillRAGPipeline:
    """Map raw skill strings to canonical SkillSet records with retrieval + LLM.

    Deterministic matches short-circuit first. When alias and exact matching do
    not resolve a skill, pgvector retrieves candidate SkillSet records and
    Ollama must select from that candidate list only.
    """

    def __init__(
        self,
        vector_top_k=10,
        catalog_fallback_limit=10,
        min_confidence=0.80,
        ollama_mapper=None,
        vector_search=None,
    ):
        self.vector_top_k = vector_top_k
        self.catalog_fallback_limit = catalog_fallback_limit
        self.min_confidence = min_confidence
        self.ollama_mapper = ollama_mapper or OllamaSkillMapper()
        self.vector_search = vector_search or get_similar_skills

    def map_skills(self, raw_skills: list[str]) -> list[SkillMappingResult]:
        """Batch-map raw skills while preserving input order."""
        cache = {}
        results = []
        for raw_skill in raw_skills or []:
            cache_key = SkillSet.normalize_name(raw_skill)
            if cache_key in cache:
                results.append(cache[cache_key])
                continue
            result = self._map_skill(raw_skill)
            cache[cache_key] = result
            results.append(result)
        return results

    def _map_skill(self, raw_skill):
        original = str(raw_skill or "").strip()
        cleaned = self._clean_skill(raw_skill)
        if not cleaned:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=0.0,
                source="empty",
                reason="Skill name is empty.",
            )

        alias_candidate = self._alias_candidate(cleaned)
        if alias_candidate:
            logger.info(
                "RAG skill alias hit: raw_skill=%s canonical=%s",
                cleaned,
                alias_candidate.skill.name,
            )
            return self._accepted_result(original, alias_candidate)

        exact_candidate = self._exact_candidate(cleaned)
        if exact_candidate:
            logger.info(
                "RAG skill exact hit: raw_skill=%s canonical=%s",
                cleaned,
                exact_candidate.skill.name,
            )
            return self._accepted_result(original, exact_candidate)

        candidates = self._retrieval_candidates(cleaned)
        candidate_names = [candidate.skill.name for candidate in candidates]
        logger.info(
            "RAG skill retrieval candidates: raw_skill=%s candidates=%s",
            cleaned,
            candidate_names,
        )
        if not candidates:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=0.0,
                source="unresolved",
                reason="No alias, exact, vector, or catalog candidates found.",
            )

        return self._verify_with_ollama(
            original=original,
            cleaned=cleaned,
            candidates=candidates,
        )

    def _verify_with_ollama(self, original, cleaned, candidates):
        candidate_names = [candidate.skill.name for candidate in candidates]
        try:
            mapping = self.ollama_mapper.map(
                cleaned,
                canonical_options=candidate_names,
            )
        except OllamaSkillMappingError as exc:
            logger.warning(
                "RAG skill Ollama verification failed: raw_skill=%s error=%s",
                cleaned,
                exc,
            )
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=0.0,
                source="ollama_error",
                reason=str(exc),
            )

        logger.info(
            "RAG skill Ollama response: raw_skill=%s canonical=%s confidence=%s",
            cleaned,
            mapping.canonical,
            mapping.confidence,
        )
        if mapping.confidence < self.min_confidence:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=mapping.confidence,
                source="low_confidence",
                reason=(
                    mapping.reason
                    or f"Confidence below threshold {self.min_confidence}."
                ),
            )

        candidate = self._candidate_by_name(candidates, mapping.canonical)
        if not candidate:
            return SkillMappingResult(
                original=original,
                canonical=None,
                confidence=mapping.confidence,
                source="invalid_canonical",
                reason="Ollama returned a canonical skill outside candidates.",
            )

        logger.info(
            "RAG skill final decision: raw_skill=%s canonical=%s confidence=%s",
            cleaned,
            candidate.skill.name,
            mapping.confidence,
        )
        return SkillMappingResult(
            original=original,
            canonical=candidate.skill.name,
            confidence=mapping.confidence,
            source="rag",
            reason=mapping.reason or candidate.reason,
        )

    def _alias_candidate(self, cleaned):
        alias = (
            SkillAlias.objects.select_related("skill")
            .filter(alias__iexact=cleaned)
            .first()
        )
        if not alias:
            return None
        return RetrievedSkillCandidate(
            skill=alias.skill,
            source="alias",
            confidence=1.0,
            reason="Matched SkillAlias exactly.",
        )

    @staticmethod
    def _exact_candidate(cleaned):
        skill = SkillSet.objects.filter(
            normalized_name=SkillSet.normalize_name(cleaned)
        ).first()
        if not skill:
            return None
        return RetrievedSkillCandidate(
            skill=skill,
            source="exact",
            confidence=1.0,
            reason="Matched SkillSet name exactly.",
        )

    def _vector_candidates(self, cleaned):
        try:
            similar_skills = self.vector_search(cleaned, top_k=self.vector_top_k)
        except (EmbeddingServiceError, DatabaseError, ValueError) as exc:
            logger.warning(
                "RAG skill vector retrieval failed: raw_skill=%s error=%s",
                cleaned,
                exc,
            )
            return []

        candidates = []
        seen = set()
        for similar in similar_skills:
            skill = similar.skill
            normalized_name = SkillSet.normalize_name(skill.name)
            if normalized_name in seen:
                continue
            seen.add(normalized_name)
            candidates.append(
                RetrievedSkillCandidate(
                    skill=skill,
                    source="vector",
                    confidence=float(similar.similarity),
                    reason=(
                        "Retrieved by pgvector cosine similarity "
                        f"{float(similar.similarity):.4f}."
                    ),
                )
            )
        return candidates

    def _retrieval_candidates(self, cleaned):
        candidates = []
        seen = set()
        for candidate in self._vector_candidates(cleaned):
            key = SkillSet.normalize_name(candidate.skill.name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        for candidate in self._catalog_candidates(cleaned):
            key = SkillSet.normalize_name(candidate.skill.name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

        return candidates

    def _catalog_candidates(self, cleaned):
        normalized_query = SkillSet.normalize_name(cleaned)
        tokens = self._expanded_tokens(normalized_query)
        if not normalized_query or not tokens:
            return []

        scored = []
        for skill in SkillSet.objects.filter(is_active=True).prefetch_related(
            "keywords"
        ):
            score, reasons = self._catalog_score(skill, normalized_query, tokens)
            if score <= 0:
                continue
            scored.append((score, skill.name.casefold(), skill, reasons))

        scored.sort(key=lambda item: (-item[0], item[1]))
        candidates = []
        for score, _name, skill, reasons in scored[: self.catalog_fallback_limit]:
            candidates.append(
                RetrievedSkillCandidate(
                    skill=skill,
                    source="catalog",
                    confidence=min(0.79, round(score / 20, 4)),
                    reason="Catalog fallback: " + ", ".join(reasons[:3]) + ".",
                )
            )
        return candidates

    @classmethod
    def _catalog_score(cls, skill, normalized_query, tokens):
        skill_name = skill.normalized_name
        skill_tokens = cls._tokens(skill_name)
        score = 0
        reasons = []

        if skill_name in normalized_query or normalized_query in skill_name:
            score += 8
            reasons.append("name phrase overlap")

        overlap = tokens & skill_tokens
        if overlap:
            score += len(overlap) * 4
            reasons.append("name token overlap")
            if skill_tokens and skill_tokens <= tokens:
                score += 2
                reasons.append("name fully covered")

        for alias in skill.normalized_aliases:
            alias_tokens = cls._tokens(alias)
            if alias in normalized_query or normalized_query in alias:
                score += 6
                reasons.append("alias phrase overlap")
            alias_overlap = tokens & alias_tokens
            if alias_overlap:
                score += len(alias_overlap) * 3
                reasons.append("alias token overlap")

        for keyword in skill.active_keywords:
            keyword_text = keyword.normalized_text
            keyword_tokens = cls._tokens(keyword_text)
            if keyword_text in normalized_query or normalized_query in keyword_text:
                score += 6
                reasons.append("keyword phrase overlap")
            keyword_overlap = tokens & keyword_tokens
            if keyword_overlap:
                score += len(keyword_overlap) * 3
                reasons.append("keyword token overlap")

        return score, reasons

    @classmethod
    def _expanded_tokens(cls, normalized_query):
        tokens = cls._tokens(normalized_query)
        expansions = {
            "ai": {"artificial", "intelligence", "machine", "learning", "genai"},
            "llm": {"large", "language", "models", "model", "generative", "ai"},
            "ml": {"machine", "learning"},
            "etl": {"extract", "transform", "load", "data"},
            "db": {"database", "databases"},
            "devops": {"cloud", "infrastructure", "deployment"},
            "ot": {"operational", "technology", "security", "cybersecurity"},
            "nas": {"storage", "network", "infrastructure"},
        }
        expanded = set(tokens)
        for token in tokens:
            expanded.update(expansions.get(token, set()))
        return expanded

    @staticmethod
    def _tokens(value):
        stopwords = {
            "a",
            "an",
            "and",
            "for",
            "in",
            "of",
            "or",
            "the",
            "to",
            "with",
            "skill",
            "skills",
            "tool",
            "tools",
            "technology",
            "technologies",
            "engineering",
            "engineer",
            "implementation",
            "implementations",
            "solution",
            "solutions",
        }
        return {
            token
            for token in re.split(r"[^a-z0-9+#.]+", str(value or "").casefold())
            if len(token) > 1 and token not in stopwords
        }

    @staticmethod
    def _candidate_by_name(candidates, name):
        normalized_name = SkillSet.normalize_name(name)
        if not normalized_name:
            return None
        for candidate in candidates:
            if SkillSet.normalize_name(candidate.skill.name) == normalized_name:
                return candidate
        return None

    @staticmethod
    def _clean_skill(raw_skill):
        return " ".join(str(raw_skill or "").split()).strip(" .,;:|/\\")

    @staticmethod
    def _accepted_result(original, candidate):
        return SkillMappingResult(
            original=original,
            canonical=candidate.skill.name,
            confidence=candidate.confidence,
            source=candidate.source,
            reason=candidate.reason,
        )
