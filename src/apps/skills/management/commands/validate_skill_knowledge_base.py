from django.core.management.base import BaseCommand

from apps.skills.services.esco_import import SkillKnowledgeBaseValidator


class Command(BaseCommand):
    help = "Validate the skill knowledge base after ESCO import."

    def handle(self, *args, **options):
        report = SkillKnowledgeBaseValidator().validate()

        self.stdout.write(f"SkillSet Count: {report.skillset_count}")
        self.stdout.write(f"SkillAlias Count: {report.skill_alias_count}")
        self.stdout.write(f"SkillCategory Count: {report.skill_category_count}")
        self.stdout.write(f"SkillRelationship Count: {report.skill_relationship_count}")

        self.stdout.write("")
        self.stdout.write("Missing Categories:")
        if report.missing_categories:
            for name in report.missing_categories:
                self.stdout.write(f"  - {name}")
        else:
            self.stdout.write("  (none)")

        self.stdout.write("")
        self.stdout.write("Orphan Skills:")
        if report.orphan_skills:
            for name in report.orphan_skills[:50]:
                self.stdout.write(f"  - {name}")
            if len(report.orphan_skills) > 50:
                self.stdout.write(
                    f"  ... and {len(report.orphan_skills) - 50} more"
                )
        else:
            self.stdout.write("  (none)")

        self.stdout.write("")
        self.stdout.write("Duplicate Aliases:")
        if report.duplicate_aliases:
            for entry in report.duplicate_aliases[:50]:
                self.stdout.write(f"  - {entry}")
            if len(report.duplicate_aliases) > 50:
                self.stdout.write(
                    f"  ... and {len(report.duplicate_aliases) - 50} more"
                )
        else:
            self.stdout.write("  (none)")
