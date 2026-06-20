import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.services.resume_tuning_service import ResumeTuningService


class Command(BaseCommand):
    help = "Run repeated resume Ollama analysis against a gold skill spec."

    def add_arguments(self, parser):
        parser.add_argument(
            "resume_path",
            help="Path to a PDF, DOCX, TXT, or Markdown resume.",
        )
        parser.add_argument("gold_path", help="Path to the resume gold JSON file.")
        parser.add_argument(
            "--runs",
            type=int,
            default=3,
            help="Number of repeated Ollama analysis runs.",
        )
        parser.add_argument(
            "--output",
            help="Optional path to write the full JSON evaluation report.",
        )
        parser.add_argument(
            "--fail-on-regression",
            action="store_true",
            help="Exit with an error if any run misses the gold expectations.",
        )
        parser.add_argument("--job-limit", type=int, default=None)
        parser.add_argument("--market-limit", type=int, default=None)

    def handle(self, *args, **options):
        resume_path = Path(options["resume_path"])
        gold_path = Path(options["gold_path"])
        if not resume_path.exists():
            raise CommandError(f"Resume file does not exist: {resume_path}")
        if not gold_path.exists():
            raise CommandError(f"Gold file does not exist: {gold_path}")

        service = ResumeTuningService()
        report = service.run(
            resume_path=resume_path,
            gold_path=gold_path,
            runs=options["runs"],
            job_limit=options["job_limit"],
            market_limit=options["market_limit"],
            progress_callback=self._progress,
        )

        output_path = options.get("output")
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self.stdout.write(f"Wrote report: {path}")

        summary = report["summary"]
        status = "PASSED" if report["passed"] else "FAILED"
        self.stdout.write(
            self.style.SUCCESS(status)
            if report["passed"]
            else self.style.ERROR(status)
        )
        self.stdout.write(
            "Runs: {passing}/{total} passed | stable mapped: {stable} | "
            "unstable verified: {unstable}".format(
                passing=summary["passing_runs"],
                total=report["runs_completed"],
                stable=len(summary["stable_mapped_skills"]),
                unstable=len(summary["unstable_verified_skills"]),
            )
        )
        for run in report["runs"]:
            if run["passed"]:
                continue
            self.stdout.write(
                "Run {index} failed: missing={missing} mapped={mapped} "
                "any_of={any_of} rejected={rejected}".format(
                    index=run["index"],
                    missing=run["missing_expected"],
                    mapped=run["missing_mapped"],
                    any_of=run["expected_any_of_failures"],
                    rejected=run["unexpected_rejected_present"],
                )
            )

        if options["fail_on_regression"] and not report["passed"]:
            raise CommandError("Resume Ollama regression check failed.")

    def _progress(self, index, total):
        self.stdout.write(f"[{index}/{total}] Running resume analysis...")
