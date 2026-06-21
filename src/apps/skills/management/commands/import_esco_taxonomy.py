from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.skills.services.esco_import import (
    default_esco_data_dir,
    EscoTaxonomyImporter,
)


class Command(BaseCommand):
    help = "Import ESCO skill taxonomy into SkillCategory from CSV files."

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
            stats = EscoTaxonomyImporter(data_dir).import_taxonomy()
        except FileNotFoundError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Created Categories: {stats.categories_created}")
        self.stdout.write(f"Updated Categories: {stats.categories_updated}")
        self.stdout.write(f"Skipped Categories: {stats.categories_skipped}")
        self.stdout.write(f"Hierarchy Links Created: {stats.hierarchy_links_created}")
        self.stdout.write(f"Hierarchy Links Skipped: {stats.hierarchy_links_skipped}")
        self.stdout.write(f"Skill-Category Links Created: {stats.skill_links_created}")
        self.stdout.write(f"Skill-Category Links Skipped: {stats.skill_links_skipped}")
