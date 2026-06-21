from pathlib import Path

from django.core.management.base import BaseCommand

from apps.skills.services.esco_import import (
    default_esco_data_dir,
    discover_esco_files,
    format_missing_files,
)
from apps.skills.services.esco_import.csv_reader import read_esco_csv, REQUIRED_FIELDS_BY_GROUP


class Command(BaseCommand):
    help = "Show ESCO CSV file discovery and row counts (no database changes)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory containing ESCO CSV files (default: data/esco).",
        )

    def handle(self, *args, **options):
        data_dir = Path(options["data_dir"] or default_esco_data_dir()).resolve()
        self.stdout.write(f"Resolved ESCO data directory: {data_dir}")
        self.stdout.write(f"Directory exists: {data_dir.is_dir()}")

        if not data_dir.is_dir():
            self.stdout.write(format_missing_files(data_dir))
            return

        discovered = discover_esco_files(data_dir)
        for group, path in discovered.items():
            if path is None:
                self.stdout.write(f"{group}: NOT FOUND")
                continue
            self.stdout.write(f"{group}: {path}")
            required = REQUIRED_FIELDS_BY_GROUP.get(group.replace("skill_skill_relations", "skill_skill_relations"))
            if group == "skills":
                required_fields = REQUIRED_FIELDS_BY_GROUP["skills"]
            elif group == "skill_groups":
                required_fields = REQUIRED_FIELDS_BY_GROUP["skill_groups"]
            elif group == "broader_relations":
                required_fields = REQUIRED_FIELDS_BY_GROUP["broader_relations"]
            elif group == "skill_skill_relations":
                required_fields = REQUIRED_FIELDS_BY_GROUP["skill_skill_relations"]
            else:
                required_fields = None

            if required_fields:
                rows, header_map = read_esco_csv(path, required_fields=required_fields)
                self.stdout.write(f"  rows: {len(rows)}")
                self.stdout.write(f"  mapped columns: {', '.join(sorted(header_map.keys()))}")

        self.stdout.write("")
        self.stdout.write("Run import:")
        self.stdout.write(f"  python manage.py import_esco --data-dir {data_dir}")
