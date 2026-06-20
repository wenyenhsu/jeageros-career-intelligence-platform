from dataclasses import dataclass

import pytest

from apps.skills.models import SkillAlias, SkillSet
from apps.skills.services.ollama_mapper import (
    OllamaSkillMapping,
    OllamaSkillMappingError,
)
from apps.skills.services.skill_rag_pipeline import SkillRAGPipeline


@dataclass(frozen=True)
class FakeSimilarSkill:
    skill: SkillSet
    similarity: float


class FakeOllamaMapper:
    def __init__(self, canonical=None, confidence=0.95, reason="verified"):
        self.canonical = canonical
        self.confidence = confidence
        self.reason = reason
        self.calls = []

    def map(self, raw_skill, canonical_options=None):
        self.calls.append(
            {
                "raw_skill": raw_skill,
                "canonical_options": canonical_options or [],
            }
        )
        return OllamaSkillMapping(
            original=raw_skill,
            canonical=self.canonical,
            confidence=self.confidence,
            reason=self.reason,
        )


class FailingOllamaMapper:
    def map(self, raw_skill, canonical_options=None):
        raise OllamaSkillMappingError("malformed JSON")


@pytest.mark.django_db
def test_rag_pipeline_uses_alias_hit_without_ollama():
    postgres = SkillSet.objects.create(name="PostgreSQL")
    SkillAlias.objects.create(alias="Postgres", skill=postgres)
    mapper = FakeOllamaMapper(canonical="PostgreSQL")

    result = SkillRAGPipeline(ollama_mapper=mapper).map_skills(["Postgres"])[0]

    assert result.canonical == "PostgreSQL"
    assert result.confidence == 1.0
    assert result.source == "alias"
    assert mapper.calls == []


@pytest.mark.django_db
def test_rag_pipeline_uses_exact_match_without_ollama():
    SkillSet.objects.create(name="MySQL")
    mapper = FakeOllamaMapper(canonical="MySQL")

    result = SkillRAGPipeline(ollama_mapper=mapper).map_skills(["mysql"])[0]

    assert result.canonical == "MySQL"
    assert result.source == "exact"
    assert mapper.calls == []


@pytest.mark.django_db
def test_rag_pipeline_uses_vector_retrieval_candidates_for_ollama():
    postgres = SkillSet.objects.create(name="PostgreSQL")
    mysql = SkillSet.objects.create(name="MySQL")
    mapper = FakeOllamaMapper(
        canonical="PostgreSQL",
        confidence=0.99,
        reason="Alias + semantic similarity",
    )
    vector_calls = []

    def fake_vector_search(query, top_k=10):
        vector_calls.append({"query": query, "top_k": top_k})
        return [
            FakeSimilarSkill(skill=postgres, similarity=0.94),
            FakeSimilarSkill(skill=mysql, similarity=0.81),
        ]

    result = SkillRAGPipeline(
        ollama_mapper=mapper,
        vector_search=fake_vector_search,
    ).map_skills(["pg database"])[0]

    assert vector_calls == [{"query": "pg database", "top_k": 10}]
    assert mapper.calls[0]["canonical_options"] == ["PostgreSQL", "MySQL"]
    assert result.canonical == "PostgreSQL"
    assert result.confidence == 0.99
    assert result.source == "rag"


@pytest.mark.django_db
def test_rag_pipeline_uses_catalog_fallback_when_vector_has_no_candidates():
    SkillSet.objects.create(name="Machine Learning")
    SkillSet.objects.create(name="SQL")
    mapper = FakeOllamaMapper(
        canonical="Machine Learning",
        confidence=0.9,
        reason="AI and LLM map best to machine learning.",
    )

    def empty_vector_search(query, top_k=10):
        return []

    result = SkillRAGPipeline(
        ollama_mapper=mapper,
        vector_search=empty_vector_search,
    ).map_skills(["AI & LLM Engineering"])[0]

    assert "Machine Learning" in mapper.calls[0]["canonical_options"]
    assert "SQL" not in mapper.calls[0]["canonical_options"]
    assert result.canonical == "Machine Learning"
    assert result.source == "rag"


@pytest.mark.django_db
def test_rag_pipeline_ollama_fallback_maps_vector_candidate():
    mongodb = SkillSet.objects.create(name="MongoDB")
    mapper = FakeOllamaMapper(canonical="MongoDB", confidence=0.86)

    def fake_vector_search(query, top_k=10):
        return [FakeSimilarSkill(skill=mongodb, similarity=0.77)]

    result = SkillRAGPipeline(
        ollama_mapper=mapper,
        vector_search=fake_vector_search,
    ).map_skills(["document database"])[0]

    assert result.canonical == "MongoDB"
    assert result.source == "rag"
    assert result.confidence == 0.86


@pytest.mark.django_db
def test_rag_pipeline_handles_invalid_json_response():
    postgres = SkillSet.objects.create(name="PostgreSQL")

    def fake_vector_search(query, top_k=10):
        return [FakeSimilarSkill(skill=postgres, similarity=0.93)]

    result = SkillRAGPipeline(
        ollama_mapper=FailingOllamaMapper(),
        vector_search=fake_vector_search,
    ).map_skills(["postgres db"])[0]

    assert result.canonical is None
    assert result.confidence == 0.0
    assert result.source == "ollama_error"
    assert "malformed JSON" in result.reason


@pytest.mark.django_db
def test_rag_pipeline_rejects_low_confidence_ollama_mapping():
    postgres = SkillSet.objects.create(name="PostgreSQL")
    mapper = FakeOllamaMapper(
        canonical="PostgreSQL",
        confidence=0.79,
        reason="weak semantic similarity",
    )

    def fake_vector_search(query, top_k=10):
        return [FakeSimilarSkill(skill=postgres, similarity=0.92)]

    result = SkillRAGPipeline(
        ollama_mapper=mapper,
        vector_search=fake_vector_search,
    ).map_skills(["ambiguous db"])[0]

    assert result.canonical is None
    assert result.confidence == 0.79
    assert result.source == "low_confidence"


@pytest.mark.django_db
def test_rag_pipeline_batch_processing_preserves_order_and_reuses_cache():
    python = SkillSet.objects.create(name="Python")
    mapper = FakeOllamaMapper(canonical="Python", confidence=0.91)

    def fake_vector_search(query, top_k=10):
        return [FakeSimilarSkill(skill=python, similarity=0.88)]

    results = SkillRAGPipeline(
        ollama_mapper=mapper,
        vector_search=fake_vector_search,
    ).map_skills(["py scripting", "py scripting", ""])

    assert [result.canonical for result in results] == ["Python", "Python", None]
    assert [result.source for result in results] == ["rag", "rag", "empty"]
    assert len(mapper.calls) == 1
