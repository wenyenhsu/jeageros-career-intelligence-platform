from django.core.management.base import BaseCommand

from apps.analytics.services.skill_demand_service import update_skill_demand


class Command(BaseCommand):
    help = "Aggregate JobPostSkill data into SkillDemand and SkillTrend records."

    def handle(self, *args, **options):
        stats = update_skill_demand()
        self.stdout.write(f"Demand records updated: {stats['demand_records']}")
        self.stdout.write(f"Trend records updated: {stats['trend_records']}")
        self.stdout.write(f"Stale demand rows removed: {stats['stale_removed']}")
