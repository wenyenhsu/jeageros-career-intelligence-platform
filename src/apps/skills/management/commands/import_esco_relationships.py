from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.skills.services.esco_import import (
    default_esco_data_dir,
    EscoRelationshipImporter,
)


class Command(BaseCommand):
    help = "Import ESCO skill-skill relationships into SkillRelationship."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory containing ESCO CSV files (default: data/esco).",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"] or default_esco_data_dir())
        if not data_dir.is_dir():
            raise CommandError(f"ESCO data directory not found: {data_dir}")

        try:
            stats = EscoRelationshipImporter(data_dir).import_relationships()
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Created Relationships: {stats.created}")
        self.stdout.write(f"Updated Relationships: {stats.updated}")
        self.stdout.write(f"Skipped Relationships: {stats.skipped}")
