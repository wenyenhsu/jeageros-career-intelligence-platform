from django.core.management.base import BaseCommand

from apps.skills.services.skill_intelligence import SkillNormalizationValidator


class Command(BaseCommand):
    help = "Validate canonical skill normalization coverage."

    def handle(self, *args, **options):
        report = SkillNormalizationValidator().validate()

        self.stdout.write("Unresolved Aliases:")
        if report.unresolved_aliases:
            for entry in report.unresolved_aliases[:100]:
                self.stdout.write(f"  - {entry}")
            if len(report.unresolved_aliases) > 100:
                self.stdout.write(
                    f"  ... and {len(report.unresolved_aliases) - 100} more"
                )
        else:
            self.stdout.write("  (none)")

        self.stdout.write("")
        self.stdout.write("Duplicate Canonical Skills:")
        if report.duplicate_canonical_skills:
            for entry in report.duplicate_canonical_skills[:100]:
                self.stdout.write(f"  - {entry}")
            if len(report.duplicate_canonical_skills) > 100:
                self.stdout.write(
                    f"  ... and {len(report.duplicate_canonical_skills) - 100} more"
                )
        else:
            self.stdout.write("  (none)")

        self.stdout.write("")
        self.stdout.write("Orphan Relationships:")
        if report.orphan_relationships:
            for entry in report.orphan_relationships[:100]:
                self.stdout.write(f"  - {entry}")
            if len(report.orphan_relationships) > 100:
                self.stdout.write(
                    f"  ... and {len(report.orphan_relationships) - 100} more"
                )
        else:
            self.stdout.write("  (none)")
