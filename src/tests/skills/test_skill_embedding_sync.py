import pytest
from django.conf import settings
from django.test import override_settings

from apps.skills.models import SkillSet
from apps.skills.services.embedding_service import EmbeddingServiceError
from apps.skills.services.skill_embedding_service import SkillEmbeddingSyncService
from apps.skills.tasks import generate_skill_embeddings


class FakeEmbeddingService:
    def embed(self, text):
        return [1.0, 0.0]


class FailingEmbeddingService:
    def embed(self, text):
        raise EmbeddingServiceError("boom")


@pytest.mark.django_db
def test_sync_embeddings_generates_missing_vectors():
    skill = SkillSet.objects.create(name="Python")
    result = SkillEmbeddingSyncService(
        embedding_service=FakeEmbeddingService()
    ).sync_embeddings(limit=10)

    skill.refresh_from_db()
    assert skill.embedding is not None
    assert result.generated == 1
    assert result.errors == 0
    assert result.remaining_without_embedding == 0


@pytest.mark.django_db
def test_sync_embeddings_skips_existing_vectors_by_default():
    skill = SkillSet.objects.create(name="Python", embedding=[1.0, 0.0])
    result = SkillEmbeddingSyncService(
        embedding_service=FakeEmbeddingService()
    ).sync_embeddings(limit=10)

    assert result.generated == 0
    assert result.skipped == 0
    skill.refresh_from_db()
    assert list(skill.embedding) == [1.0, 0.0]


@pytest.mark.django_db
def test_sync_embeddings_counts_errors_without_stopping_batch():
    SkillSet.objects.create(name="Python")
    SkillSet.objects.create(name="Django")
    result = SkillEmbeddingSyncService(
        embedding_service=FailingEmbeddingService()
    ).sync_embeddings(limit=10)

    assert result.generated == 0
    assert result.errors == 2
    assert result.remaining_without_embedding == 2


@pytest.mark.django_db
def test_generate_skill_embeddings_task_returns_summary(monkeypatch):
    SkillSet.objects.create(name="Python")
    monkeypatch.setattr(
        "apps.skills.services.skill_embedding_service.EmbeddingService",
        lambda *args, **kwargs: FakeEmbeddingService(),
    )
    payload = generate_skill_embeddings.run(limit=10)

    assert payload["generated"] == 1
    assert payload["remaining_without_embedding"] == 0


def test_celery_beat_schedule_registers_embedding_task():
    scheduled_task = settings.CELERY_BEAT_SCHEDULE["generate-skill-embeddings"]

    assert scheduled_task["task"] == "apps.skills.tasks.generate_skill_embeddings"
    assert scheduled_task["schedule"] == settings.SKILL_EMBEDDING_SCHEDULE_SECONDS
    assert scheduled_task["schedule"] > 0


@pytest.mark.django_db
@override_settings(SKILL_EMBEDDING_SYNC_ENABLED=False)
def test_schedule_skill_embedding_sync_disabled_returns_none():
    from apps.skills.tasks import schedule_skill_embedding_sync

    assert schedule_skill_embedding_sync() is None
