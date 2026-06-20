import pytest
from django.core.management import call_command
from django.db import connection

from apps.skills.models import SkillSet
from apps.skills.services.embedding_service import (
    EmbeddingService,
    EmbeddingServiceError,
)
from apps.skills.services.vector_search import get_similar_skills


def vector(*values):
    return list(values) + [0.0] * (1024 - len(values))


class FakeEmbeddingBackend:
    def __init__(self, embedding):
        self.embedding = embedding

    def embed(self, text):
        return self.embedding


class FakeEmbeddingService:
    def __init__(self, *args, **kwargs):
        pass

    def embed(self, text):
        return vector(1.0, 0.0)


class ExplodingEmbeddingService:
    def embed(self, text):
        raise AssertionError("Embedding service should not be called")


def test_embedding_service_validates_dimension_count():
    service = EmbeddingService(
        dimensions=3,
        backend=FakeEmbeddingBackend([1, "2", 3.0]),
    )

    assert service.embed(" Python ") == [1.0, 2.0, 3.0]


def test_embedding_service_rejects_wrong_dimension_count():
    service = EmbeddingService(dimensions=3, backend=FakeEmbeddingBackend([1, 2]))

    with pytest.raises(EmbeddingServiceError, match="dimensions"):
        service.embed("Python")


def test_embedding_service_rejects_empty_text():
    service = EmbeddingService(dimensions=3, backend=FakeEmbeddingBackend([1, 2, 3]))

    with pytest.raises(EmbeddingServiceError, match="empty"):
        service.embed("  ")


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="pgvector required")
def test_get_similar_skills_orders_by_cosine_similarity():
    python = SkillSet.objects.create(name="Python", embedding=vector(1.0, 0.0))
    django = SkillSet.objects.create(name="Django", embedding=vector(0.8, 0.2))
    SkillSet.objects.create(name="SQL", embedding=vector(0.0, 1.0))

    results = get_similar_skills(
        "python scripting",
        top_k=2,
        embedding_service=FakeEmbeddingService(),
    )

    assert [result.skill for result in results] == [python, django]
    assert results[0].similarity > results[1].similarity
    assert results[0].as_dict()["name"] == "Python"


@pytest.mark.django_db
def test_get_similar_skills_returns_empty_when_no_embeddings_exist():
    SkillSet.objects.create(name="Python")

    assert (
        get_similar_skills(
            "python scripting",
            embedding_service=ExplodingEmbeddingService(),
        )
        == []
    )


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="pgvector required")
def test_generate_skill_embeddings_command_updates_missing_embeddings(monkeypatch):
    skill = SkillSet.objects.create(name="Python")
    monkeypatch.setattr(
        "apps.skills.management.commands.generate_skill_embeddings.EmbeddingService",
        FakeEmbeddingService,
    )

    call_command("generate_skill_embeddings")

    skill.refresh_from_db()
    assert list(skill.embedding) == vector(1.0, 0.0)
