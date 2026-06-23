from django.core.management.base import BaseCommand

from apps.skills.services.skill_embedding_service import SkillEmbeddingSyncService


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
        result = SkillEmbeddingSyncService().sync_embeddings(
            force=options["force"],
            limit=options["limit"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"Generated: {result.generated}, "
                f"Skipped: {result.skipped}, "
                f"Errors: {result.errors}, "
                f"Remaining without embedding: {result.remaining_without_embedding}"
            )
        )
