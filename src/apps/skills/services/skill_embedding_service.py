from dataclasses import dataclass

from django.conf import settings

from apps.skills.models import SkillSet

from .embedding_service import EmbeddingService, EmbeddingServiceError


@dataclass(frozen=True)
class SkillEmbeddingSyncResult:
    generated: int
    skipped: int
    errors: int
    remaining_without_embedding: int

    def as_dict(self):
        return {
            "generated": self.generated,
            "skipped": self.skipped,
            "errors": self.errors,
            "remaining_without_embedding": self.remaining_without_embedding,
        }


class SkillEmbeddingSyncService:
    """Generate pgvector embeddings for SkillSet records."""

    def __init__(self, embedding_service=None):
        self.embedding_service = embedding_service or EmbeddingService()

    def sync_embeddings(self, force=False, limit=None) -> SkillEmbeddingSyncResult:
        if limit is None:
            limit = settings.SKILL_EMBEDDING_BATCH_LIMIT

        queryset = SkillSet.objects.order_by("id")
        if not force:
            queryset = queryset.filter(embedding__isnull=True)

        queryset = queryset.prefetch_related("keywords")
        if limit:
            queryset = queryset[:limit]

        generated = 0
        skipped = 0
        errors = 0

        for skill in queryset:
            if skill.embedding and not force:
                skipped += 1
                continue

            try:
                skill.embedding = self.embedding_service.embed(
                    self.build_embedding_text(skill)
                )
                skill.save(update_fields=["embedding", "updated_at"])
            except EmbeddingServiceError:
                errors += 1
                continue

            generated += 1

        remaining = SkillSet.objects.filter(embedding__isnull=True).count()
        return SkillEmbeddingSyncResult(
            generated=generated,
            skipped=skipped,
            errors=errors,
            remaining_without_embedding=remaining,
        )

    @staticmethod
    def build_embedding_text(skill: SkillSet) -> str:
        parts = [skill.name]
        if skill.description:
            parts.append(skill.description)
        parts.extend(skill.aliases or [])
        for keyword in skill.active_keywords:
            parts.append(keyword.raw_text)
        return ". ".join(str(part) for part in parts if str(part).strip())
