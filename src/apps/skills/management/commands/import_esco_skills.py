from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.skills.services.esco_import import (
    default_esco_data_dir,
    EscoSkillImporter,
    format_missing_files,
)


class Command(BaseCommand):
    help = "Import ESCO skills into SkillSet from CSV files."

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
            raise CommandError(
                f"ESCO data directory not found: {data_dir}\n"
                f"{format_missing_files(data_dir)}"
            )

        try:
            stats = EscoSkillImporter(data_dir).import_skills()
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Created Skills: {stats.created}")
        self.stdout.write(f"Updated Skills: {stats.updated}")
        self.stdout.write(f"Skipped Skills: {stats.skipped}")
