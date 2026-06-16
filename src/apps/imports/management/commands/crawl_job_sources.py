import json

from django.core.management.base import BaseCommand

from apps.imports.models import JobSource
from apps.imports.services import CrawlService


class Command(BaseCommand):
    help = "Run the job source crawl/sync pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-id",
            type=int,
            help="Run the crawl pipeline for a single JobSource id.",
        )

    def handle(self, *args, **options):
        self._last_processed_sources = None
        source_id = options.get("source_id")
        if source_id:
            sources = JobSource.objects.filter(id=source_id)
            if not sources.exists():
                self.stderr.write(
                    self.style.ERROR(f"JobSource {source_id} was not found.")
                )
                return
            summary = CrawlService.crawl_all_sources(
                sources,
                progress_callback=self._display_progress,
            )
        else:
            summary = CrawlService.crawl_enabled_sources(
                progress_callback=self._display_progress,
            )

        self.stdout.write("Done")
        self.stdout.write(f"Created: {summary['jobs_created']}")
        self.stdout.write(f"Updated: {summary['jobs_updated']}")
        self.stdout.write(f"Closed: {summary['jobs_closed']}")
        filtered_count = sum(
            source.get("jobs_filtered", 0) for source in summary["sources"]
        )
        self.stdout.write(f"Filtered: {filtered_count}")
        self.stdout.write(f"Skills attached: {summary.get('skills_attached', 0)}")
        self.stdout.write(
            f"Skill pipeline failures: {summary.get('skill_pipeline_failures', 0)}"
        )
        self.stdout.write(f"Errors: {summary['errors']}")
        self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))

    def _display_progress(self, progress):
        if progress["processed_sources"] == self._last_processed_sources:
            return
        self._last_processed_sources = progress["processed_sources"]
        self.stdout.write(
            (
                f"[{progress['processed_sources']}/{progress['total_sources']}] "
                f"{progress['current_source']} "
                f"({progress['progress_percentage']:.2f}%)"
            )
        )
