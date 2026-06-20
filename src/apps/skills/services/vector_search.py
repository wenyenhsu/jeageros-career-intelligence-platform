from dataclasses import dataclass

from pgvector.django import CosineDistance

from apps.skills.models import SkillSet

from .embedding_service import EmbeddingService


@dataclass(frozen=True)
class SimilarSkill:
    skill: SkillSet
    distance: float
    similarity: float

    def as_dict(self):
        return {
            "skillset_id": self.skill.id,
            "name": self.skill.name,
            "distance": self.distance,
            "similarity": self.similarity,
        }


def get_similar_skills(query: str, top_k: int = 10, embedding_service=None):
    """Return canonical skills ordered by cosine similarity to the query text."""
    cleaned = " ".join(str(query or "").split()).strip()
    if not cleaned:
        return []

    if not SkillSet.objects.filter(embedding__isnull=False).exists():
        return []

    service = embedding_service or EmbeddingService()
    embedding = service.embed(cleaned)
    limit = max(1, int(top_k or 10))
    queryset = (
        SkillSet.objects.filter(embedding__isnull=False)
        .annotate(distance=CosineDistance("embedding", embedding))
        .order_by("distance", "name")[:limit]
    )

    results = []
    for skill in queryset:
        distance = float(skill.distance)
        results.append(
            SimilarSkill(
                skill=skill,
                distance=distance,
                similarity=max(0.0, 1.0 - distance),
            )
        )
    return results
