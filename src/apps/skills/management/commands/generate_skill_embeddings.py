from django.core.management.base import BaseCommand

from apps.skills.models import SkillSet
from apps.skills.services.embedding_service import (
    EmbeddingService,
    EmbeddingServiceError,
)


class Command(BaseCommand):
    help = "Generate and store pgvector embeddings for SkillSet records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Regenerate embeddings even when a SkillSet already has one.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of SkillSet records to process.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        limit = options["limit"]
        service = EmbeddingService()
        queryset = SkillSet.objects.order_by("name")
        if not force:
            queryset = queryset.filter(embedding__isnull=True)
        if limit:
            queryset = queryset[:limit]

        generated = 0
        skipped = 0
        errors = 0
        total = queryset.count() if hasattr(queryset, "count") else len(queryset)

        for index, skill in enumerate(queryset, start=1):
            if skill.embedding and not force:
                skipped += 1
                continue

            self.stdout.write(f"[{index}/{total}] {skill.name}")
            try:
                skill.embedding = service.embed(self._embedding_text(skill))
                skill.save(update_fields=["embedding", "updated_at"])
            except EmbeddingServiceError as exc:
                errors += 1
                self.stderr.write(self.style.ERROR(f"  failed: {exc}"))
                continue

            generated += 1
            self.stdout.write(self.style.SUCCESS("  saved"))

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"Generated: {generated}, Skipped: {skipped}, Errors: {errors}"
            )
        )

    @staticmethod
    def _embedding_text(skill):
        parts = [skill.name]
        if skill.description:
            parts.append(skill.description)
        parts.extend(skill.aliases or [])
        parts.extend(skill.keywords.values_list("raw_text", flat=True))
        return ". ".join(str(part) for part in parts if str(part).strip())
