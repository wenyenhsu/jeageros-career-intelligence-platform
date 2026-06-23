import logging

from celery import shared_task
from django.conf import settings

from apps.skills.services.skill_embedding_service import SkillEmbeddingSyncService

logger = logging.getLogger(__name__)


@shared_task(name="apps.skills.tasks.generate_skill_embeddings")
def generate_skill_embeddings(force=False, limit=None):
    """Backfill SkillSet pgvector embeddings for RAG and market-fit retrieval."""
    service = SkillEmbeddingSyncService()
    result = service.sync_embeddings(force=force, limit=limit)
    payload = result.as_dict()
    logger.info(
        "Skill embedding sync finished: generated=%s skipped=%s errors=%s remaining=%s",
        payload["generated"],
        payload["skipped"],
        payload["errors"],
        payload["remaining_without_embedding"],
    )
    return payload


def schedule_skill_embedding_sync(force=False, limit=None):
    """Enqueue embedding sync when Celery is available; run inline otherwise."""
    if not settings.SKILL_EMBEDDING_SYNC_ENABLED:
        return None

    batch_limit = limit or settings.SKILL_EMBEDDING_BATCH_LIMIT
    try:
        return generate_skill_embeddings.delay(force=force, limit=batch_limit)
    except Exception as exc:
        logger.warning(
            "Celery unavailable for skill embedding sync; running inline: %s",
            exc,
        )
        return generate_skill_embeddings.run(force=force, limit=batch_limit)
