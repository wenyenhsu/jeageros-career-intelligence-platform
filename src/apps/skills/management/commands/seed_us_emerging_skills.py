from django.core.management.base import BaseCommand

from apps.skills.services.us_emerging_skills import UsEmergingSkillsSeeder


class Command(BaseCommand):
    help = "Seed curated US emerging technology skills into SkillSet."

    def handle(self, *args, **options):
        stats = UsEmergingSkillsSeeder().seed()

        self.stdout.write(f"Created Skills: {stats.skills_created}")
        self.stdout.write(f"Updated Skills: {stats.skills_updated}")
        self.stdout.write(f"Skipped Skills: {stats.skills_skipped}")
        self.stdout.write(f"Created Aliases: {stats.aliases_created}")
        self.stdout.write(f"Updated Aliases: {stats.aliases_updated}")
        self.stdout.write(f"Skipped Aliases: {stats.aliases_skipped}")
        self.stdout.write(f"Categories Created: {stats.categories_created}")
        self.stdout.write(f"Category Links Created: {stats.category_links_created}")
        self.stdout.write(f"Category Links Skipped: {stats.category_links_skipped}")
