from django.core.management.base import BaseCommand

from apps.skills.services.skill_intelligence.business_category_service import (
    BusinessCategoryService,
)


class Command(BaseCommand):
    help = "Seed JägerOS business taxonomy and assign skill mappings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign-only",
            action="store_true",
            help="Skip category creation and only run assignment.",
        )

    def handle(self, *args, **options):
        service = BusinessCategoryService()
        if options["assign_only"]:
            stats = service.assign_business_categories(auto_approve=True)
        else:
            stats = service.seed_taxonomy()

        self.stdout.write(
            self.style.SUCCESS(
                "Business taxonomy ready: "
                f"categories_created={stats.categories_created} "
                f"mappings_created={stats.mappings_created} "
                f"mappings_updated={stats.mappings_updated} "
                f"skills_assigned={stats.skills_assigned}"
            )
        )
