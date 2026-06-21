from django.utils import timezone

from apps.analytics.models import SkillCandidate
from apps.skills.models import SkillSet


class SkillCandidateService:
    review_threshold = 5

    def record_unmapped_names(
        self,
        names: list[str],
        source: str = SkillCandidate.SourceChoices.JOB_CRAWL,
    ) -> int:
        recorded = 0
        for raw_name in names or []:
            if self._record_name(raw_name, source=source):
                recorded += 1
        return recorded

    def record_unmapped_skills(
        self,
        unmapped_skills,
        source: str = SkillCandidate.SourceChoices.JOB_CRAWL,
    ) -> int:
        names = []
        for item in unmapped_skills or []:
            if hasattr(item, "name"):
                names.append(item.name)
            elif isinstance(item, dict):
                names.append(item.get("name") or item.get("skill") or "")
            elif isinstance(item, str):
                names.append(item)
        return self.record_unmapped_names(names, source=source)

    def _record_name(self, raw_name: str, source: str) -> bool:
        cleaned = " ".join(str(raw_name or "").split()).strip()
        if not cleaned:
            return False

        normalized = SkillSet.normalize_name(cleaned)
        if SkillSet.objects.filter(normalized_name=normalized).exists():
            return False

        now = timezone.now()
        candidate, created = SkillCandidate.objects.get_or_create(
            normalized_name=normalized,
            defaults={
                "name": cleaned[:120],
                "occurrence_count": 1,
                "first_seen": now,
                "source": source,
            },
        )
        if created:
            candidate.flagged_for_review = candidate.occurrence_count >= self.review_threshold
            candidate.save(update_fields=["flagged_for_review", "updated_at"])
            return True

        candidate.occurrence_count += 1
        candidate.flagged_for_review = (
            candidate.occurrence_count >= self.review_threshold
        )
        candidate.save(
            update_fields=["occurrence_count", "flagged_for_review", "updated_at"]
        )
        return True

    def flagged_candidates(self, limit: int = 50) -> list[dict]:
        rows = SkillCandidate.objects.filter(
            flagged_for_review=True,
            reviewed=False,
        ).order_by("-occurrence_count", "name")[:limit]
        return [
            {
                "id": row.id,
                "name": row.name,
                "occurrence_count": row.occurrence_count,
                "first_seen": row.first_seen,
                "source": row.source,
                "reviewed": row.reviewed,
            }
            for row in rows
        ]
