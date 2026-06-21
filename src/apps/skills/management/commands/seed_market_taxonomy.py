from django.core.management.base import BaseCommand

from apps.skills.services.skill_intelligence.market_category_service import (
    MarketCategoryService,
)


class Command(BaseCommand):
    help = "Seed US market taxonomy and assign skill mappings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign-only",
            action="store_true",
            help="Skip category creation and only run assignment.",
        )

    def handle(self, *args, **options):
        service = MarketCategoryService()
        if options["assign_only"]:
            stats = service.assign_market_categories(auto_approve=True)
        else:
            stats = service.seed_taxonomy()

        self.stdout.write(
            self.style.SUCCESS(
                "Market taxonomy ready: "
                f"categories_created={stats.categories_created} "
                f"mappings_created={stats.mappings_created} "
                f"mappings_updated={stats.mappings_updated} "
                f"skills_assigned={stats.skills_assigned}"
            )
        )
