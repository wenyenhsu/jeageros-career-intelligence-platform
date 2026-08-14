from datetime import date

import pytest

from apps.imports.services.internship_schedule_extractor import (
    InternshipScheduleExtractor,
    start_window_from_config,
)


@pytest.mark.parametrize(
    ("title", "description", "expected"),
    [
        (
            "Software Engineer Intern",
            "Start date: December 2026",
            {
                "starts_on": date(2026, 12, 1),
                "start_precision": "month",
                "season": None,
            },
        ),
        (
            "Software Engineer Intern - Summer 2026",
            "Build tools during an internship.",
            {
                "starts_on": date(2026, 5, 1),
                "ends_on": date(2026, 8, 31),
                "start_precision": "season",
                "season": "summer-2026",
            },
        ),
        (
            "Winter 2026 Software Intern",
            "",
            {
                "starts_on": date(2026, 12, 1),
                "ends_on": date(2027, 2, 28),
                "start_precision": "season",
                "season": "winter-2026",
            },
        ),
        (
            "Data Science Intern",
            "The internship runs June – August 2026.",
            {
                "starts_on": date(2026, 6, 1),
                "ends_on": date(2026, 8, 31),
                "start_precision": "month",
                "season": None,
            },
        ),
        (
            "Backend Intern",
            "This is a 12-week internship starting January 2027.",
            {
                "starts_on": date(2027, 1, 1),
                "duration_weeks": 12,
                "start_precision": "month",
            },
        ),
        (
            "Backend Engineer",
            "Build reliable systems.",
            {
                "starts_on": None,
                "ends_on": None,
                "season": None,
                "duration_weeks": None,
            },
        ),
        (
            "Software Engineer Intern",
            "Apply by December 2026. This role has no listed start date.",
            {
                "starts_on": None,
            },
        ),
    ],
)
def test_internship_schedule_extractor_parses_common_phrases(
    title, description, expected
):
    schedule = InternshipScheduleExtractor.extract(
        title=title,
        description=description,
    )
    for field_name, value in expected.items():
        assert getattr(schedule, field_name) == value


def test_december_2026_window_keeps_winter_and_drops_summer():
    window = start_window_from_config({"start_month": "2026-12"})
    assert window == (date(2026, 12, 1), date(2026, 12, 31))

    winter = InternshipScheduleExtractor.extract(title="Winter 2026 Intern")
    fall = InternshipScheduleExtractor.extract(title="Fall 2026 Intern")
    summer = InternshipScheduleExtractor.extract(title="Summer 2026 Intern")
    december = InternshipScheduleExtractor.extract(
        description="Start date: December 2026"
    )
    unknown = InternshipScheduleExtractor.extract(description="No dates listed.")

    assert winter.matches_window(*window, keep_unknown=False)
    assert fall.matches_window(*window, keep_unknown=False)
    assert december.matches_window(*window, keep_unknown=False)
    assert not summer.matches_window(*window, keep_unknown=False)
    assert unknown.matches_window(*window, keep_unknown=True)
    assert not unknown.matches_window(*window, keep_unknown=False)


@pytest.mark.django_db
def test_extract_job_schedules_command_backfills_stored_descriptions(company):
    from django.core.management import call_command

    from apps.jobs.models import JobPost

    job = JobPost.objects.create(
        company=company,
        title="Software Engineer Intern",
        description="Start date: December 2026",
    )

    call_command("extract_job_schedules")

    job.refresh_from_db()
    assert job.starts_on.isoformat() == "2026-12-01"
    assert job.start_precision == "month"
