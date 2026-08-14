from django.core.management.base import BaseCommand

from apps.imports.services.internship_schedule_extractor import (
    InternshipScheduleExtractor,
)
from apps.jobs.models import JobPost


class Command(BaseCommand):
    help = (
        "Extract internship start and end dates from stored job titles and "
        "descriptions without recrawling."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many jobs would be updated without saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        updated = 0
        scanned = 0
        for job in JobPost.objects.iterator():
            scanned += 1
            schedule = InternshipScheduleExtractor.extract(
                title=job.title,
                description=job.description,
            )
            fields = schedule.as_job_fields()
            changed = [
                field_name
                for field_name, value in fields.items()
                if getattr(job, field_name) != value
            ]
            if not changed:
                continue
            updated += 1
            if dry_run:
                continue
            for field_name, value in fields.items():
                setattr(job, field_name, value)
            job.save(update_fields=[*fields, "updated_at"])

        prefix = "Would update" if dry_run else "Updated"
        self.stdout.write(f"{prefix} {updated} of {scanned} jobs.")
