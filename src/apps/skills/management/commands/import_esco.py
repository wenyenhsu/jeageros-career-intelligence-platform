from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.skills.models import SkillSet
from apps.skills.services.esco_import import (
    default_esco_data_dir,
    discover_esco_files,
    EscoAliasImporter,
    EscoApiImporter,
    EscoRelationshipImporter,
    EscoSkillImporter,
    EscoTaxonomyImporter,
    format_missing_files,
    SkillKnowledgeBaseValidator,
)
from apps.skills.services.esco_import.api_client import EscoApiError
from apps.skills.services.esco_import.csv_reader import read_esco_csv, REQUIRED_FIELDS_BY_GROUP


class Command(BaseCommand):
    help = "Import the full ESCO skill knowledge base (skills, aliases, taxonomy, relationships)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data-dir",
            type=str,
            default=None,
            help="Directory containing ESCO CSV files (default: data/esco).",
        )
        parser.add_argument(
            "--source",
            choices=("csv", "api"),
            default="csv",
            help="Import from local CSV files or the public ESCO API.",
        )
        parser.add_argument(
            "--language",
            default="en",
            help="Language for ESCO API import (default: en).",
        )
        parser.add_argument(
            "--skip-relationships",
            action="store_true",
            help="Skip skill-skill relationship import (CSV only).",
        )
        parser.add_argument(
            "--skip-keyword-sync",
            action="store_true",
            help="Skip SkillKeyword sync after skill import (faster; run later if needed).",
        )

    def handle(self, *args, **options):
        source = options["source"]
        data_dir = Path(options["data_dir"] or default_esco_data_dir()).resolve()

        if source == "api":
            self._import_from_api(options["language"])
        else:
            self._import_from_csv(
                data_dir,
                options["skip_relationships"],
                options["skip_keyword_sync"],
            )

        report = SkillKnowledgeBaseValidator().validate()
        self.stdout.write("")
        self.stdout.write(f"SkillSet Count: {report.skillset_count}")
        self.stdout.write(f"SkillAlias Count: {report.skill_alias_count}")
        self.stdout.write(f"SkillCategory Count: {report.skill_category_count}")
        self.stdout.write(f"SkillRelationship Count: {report.skill_relationship_count}")

    def _progress(self, current: int, total: int, stage: str):
        self.stdout.write(f"  [{stage}] {current}/{total}")

    def _import_from_api(self, language: str):
        self.stdout.write(f"Importing ESCO data from API (language={language})...")
        try:
            stats = EscoApiImporter(language=language).import_all()
        except EscoApiError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Created Skills: {stats.skills_created}")
        self.stdout.write(f"Updated Skills: {stats.skills_updated}")
        self.stdout.write(f"Skipped Skills: {stats.skills_skipped}")
        self.stdout.write(f"Created Aliases: {stats.aliases_created}")
        self.stdout.write(f"Skipped Aliases: {stats.aliases_skipped}")
        self.stdout.write(f"Created Categories: {stats.categories_created}")
        self.stdout.write(f"Updated Categories: {stats.categories_updated}")
        self.stdout.write(f"Skipped Categories: {stats.categories_skipped}")
        self.stdout.write(f"Hierarchy Links Created: {stats.hierarchy_links_created}")
        self.stdout.write(
            f"Skill-Category Links Created: {stats.skill_category_links_created}"
        )
        self.stdout.write(
            self.style.WARNING(
                "API import does not include skillSkillRelations. "
                "Run import_esco_relationships after adding relationship CSV files."
            )
        )

    def _import_from_csv(
        self,
        data_dir: Path,
        skip_relationships: bool,
        skip_keyword_sync: bool,
    ):
        if not data_dir.is_dir():
            raise CommandError(
                f"ESCO data directory not found: {data_dir}\n"
                f"{format_missing_files(data_dir)}"
            )

        discovered = discover_esco_files(data_dir)
        if discovered["skills"] is None:
            raise CommandError(format_missing_files(data_dir))

        self.stdout.write(f"Using ESCO CSV directory: {data_dir}")
        for group, path in discovered.items():
            self.stdout.write(f"  {group}: {path or 'NOT FOUND'}")

        skills_path = discovered["skills"]
        if skills_path:
            rows, _ = read_esco_csv(
                skills_path,
                required_fields=REQUIRED_FIELDS_BY_GROUP["skills"],
            )
            self.stdout.write(f"  skills rows parsed: {len(rows)}")

        progress = self._progress

        try:
            self.stdout.write("Importing skills...")
            skill_stats = EscoSkillImporter(
                data_dir, progress_callback=progress
            ).import_skills()

            if not skip_keyword_sync:
                self.stdout.write("Syncing SkillKeywords for ESCO skills...")
                synced = 0
                for skill in SkillSet.objects.filter(esco_uri__isnull=False).iterator():
                    skill.sync_keywords_from_profile()
                    synced += 1
                    if synced % 2000 == 0:
                        self.stdout.write(f"  [keywords] {synced}")
                self.stdout.write(f"  synced keywords for {synced} skills")

            self.stdout.write("Importing aliases...")
            alias_stats = EscoAliasImporter(
                data_dir, progress_callback=progress
            ).import_aliases()

            self.stdout.write("Importing taxonomy...")
            taxonomy_stats = EscoTaxonomyImporter(
                data_dir, progress_callback=progress
            ).import_taxonomy()

            relationship_stats = None
            if not skip_relationships:
                self.stdout.write("Importing relationships...")
                relationship_stats = EscoRelationshipImporter(
                    data_dir, progress_callback=progress
                ).import_relationships()
        except (FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"Created Skills: {skill_stats.created}")
        self.stdout.write(f"Updated Skills: {skill_stats.updated}")
        self.stdout.write(f"Skipped Skills: {skill_stats.skipped}")
        if skill_stats.errors:
            self.stdout.write(self.style.WARNING(f"Skill Errors: {skill_stats.errors}"))
        self.stdout.write(f"Created Aliases: {alias_stats.created}")
        self.stdout.write(f"Updated Aliases: {alias_stats.updated}")
        self.stdout.write(f"Skipped Aliases: {alias_stats.skipped}")
        self.stdout.write(f"Created Categories: {taxonomy_stats.categories_created}")
        self.stdout.write(f"Updated Categories: {taxonomy_stats.categories_updated}")
        self.stdout.write(f"Skipped Categories: {taxonomy_stats.categories_skipped}")
        self.stdout.write(
            f"Skill-Category Links Created: {taxonomy_stats.skill_links_created}"
        )
        if relationship_stats:
            self.stdout.write(f"Created Relationships: {relationship_stats.created}")
            self.stdout.write(f"Skipped Relationships: {relationship_stats.skipped}")
