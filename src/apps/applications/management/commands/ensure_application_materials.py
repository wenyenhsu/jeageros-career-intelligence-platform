from django.core.management.base import BaseCommand

from apps.applications.models import Application
from apps.applications.services.materials_folder_service import MaterialsFolderService


class Command(BaseCommand):
    help = (
        "Create local and Google Drive materials folders for applications "
        "that are missing them."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--id",
            type=int,
            dest="application_id",
            help="Ensure folders for a single Application id.",
        )

    def handle(self, *args, **options):
        queryset = Application.objects.select_related("job_post__company")
        application_id = options.get("application_id")
        if application_id:
            queryset = queryset.filter(pk=application_id)
            if not queryset.exists():
                self.stderr.write(
                    self.style.ERROR(f"Application {application_id} was not found.")
                )
                return

        service = MaterialsFolderService()
        created = 0
        for application in queryset:
            had_url = bool((application.materials_url or "").strip())
            service.ensure_folders(application)
            application.refresh_from_db(fields=["materials_url"])
            if not had_url and (application.materials_url or "").strip():
                created += 1
            local_path = MaterialsFolderService.local_path_for(application)
            self.stdout.write(
                f"Application {application.pk}: {local_path or '-'} "
                f"{application.materials_url or '(no Drive folder)'}"
            )

        self.stdout.write(self.style.SUCCESS(f"Processed {queryset.count()} application(s)."))
        self.stdout.write(f"Drive folders created: {created}")
