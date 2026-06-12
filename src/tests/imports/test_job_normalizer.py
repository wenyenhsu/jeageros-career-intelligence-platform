import pytest

from apps.imports.models import JobSource
from apps.imports.services import CanonicalJobPayload, JobNormalizer, SourceDetector


def test_linkedin_payload_normalization():
    payload = JobNormalizer.normalize(
        {
            "jobTitle": "  Software Engineer Intern  ",
            "companyName": " OpenAI ",
            "jobUrl": "https://www.linkedin.com/jobs/view/123",
            "jobPostingId": "123",
            "formattedLocation": "REMOTE",
            "workplaceType": "Work From Home",
            "employmentType": "Full Time",
            "description": " Build reliable systems. ",
            "postedAt": "2026-06-10",
        },
        source=SourceDetector.LINKEDIN,
    )

    assert isinstance(payload, CanonicalJobPayload)
    assert payload.source == "linkedin"
    assert payload.title == "Software Engineer Intern"
    assert payload.company_name == "OpenAI"
    assert payload.source_url == "https://www.linkedin.com/jobs/view/123"
    assert payload.external_id == "123"
    assert payload.location == "Remote"
    assert payload.remote_type == "Remote"
    assert payload.job_type == "FULL_TIME"
    assert payload.employment_type == "FULL_TIME"
    assert payload.description == "Build reliable systems."
    assert payload.posted_at == "2026-06-10"
    assert payload.metadata["raw_payload"]["jobTitle"] == "  Software Engineer Intern  "


def test_handshake_payload_normalization():
    payload = JobNormalizer.normalize(
        {
            "position": "Data Science Intern",
            "employerName": "University Lab",
            "url": "https://app.joinhandshake.com/stu/jobs/456",
            "id": "456",
            "jobType": "Internship",
            "location": "N/A",
            "sections": {
                "requirements": "Python and SQL",
                "preferred_qualifications": "Research experience",
            },
        },
        source=SourceDetector.HANDSHAKE,
    )

    assert payload.source == "handshake"
    assert payload.title == "Data Science Intern"
    assert payload.company_name == "University Lab"
    assert payload.location is None
    assert payload.job_type == "INTERNSHIP"
    assert payload.employment_type == "INTERNSHIP"
    assert payload.sections["requirements"] == "Python and SQL"
    assert payload.description == "Python and SQL\n\nResearch experience"


def test_greenhouse_payload_normalization():
    payload = JobNormalizer.normalize(
        {
            "title": "Backend Engineer",
            "company_name": "OpenAI",
            "absolute_url": "https://boards.greenhouse.io/openai/jobs/789",
            "id": 789,
            "location": {"name": " Remote "},
            "metadata": {"department": "Engineering"},
            "content": "Build APIs.",
        },
        source=SourceDetector.GREENHOUSE,
    )

    assert payload.source == "greenhouse"
    assert payload.title == "Backend Engineer"
    assert payload.source_url == "https://boards.greenhouse.io/openai/jobs/789"
    assert payload.external_id == "789"
    assert payload.location == "Remote"
    assert payload.description == "Build APIs."
    assert payload.metadata["department"] == "Engineering"


def test_lever_payload_normalization():
    payload = JobNormalizer.normalize(
        {
            "text": "Machine Learning Engineer",
            "company": "OpenAI",
            "hostedUrl": "https://jobs.lever.co/openai/ml",
            "id": "lever-ml",
            "categories": {
                "location": "San Francisco, CA",
                "commitment": "Full-Time",
            },
            "descriptionPlain": "Train models.",
        },
        source=SourceDetector.LEVER,
    )

    assert payload.source == "lever"
    assert payload.title == "Machine Learning Engineer"
    assert payload.company_name == "OpenAI"
    assert payload.location == "San Francisco, CA"
    assert payload.job_type == "FULL_TIME"
    assert payload.employment_type == "FULL_TIME"
    assert payload.description == "Train models."


def test_empty_field_normalization():
    payload = JobNormalizer.normalize(
        {
            "title": "Engineer",
            "company": "OpenAI",
            "url": "https://jobs.example.com/engineer",
            "external_id": "N/A",
            "location": "",
            "employment_type": "not specified",
            "description": "  ",
        },
        source=SourceDetector.CAREER_SITE,
    )

    assert payload.external_id is None
    assert payload.location is None
    assert payload.job_type is None
    assert payload.employment_type is None
    assert payload.description is None


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("Full Time", "FULL_TIME"),
        ("Full-Time", "FULL_TIME"),
        ("Fulltime", "FULL_TIME"),
        ("part time", "PART_TIME"),
        ("Intern", "INTERNSHIP"),
        ("temporary", "TEMPORARY"),
    ],
)
def test_job_type_normalization(raw_value, expected):
    assert JobNormalizer.normalize_job_type(raw_value) == expected


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("Remote", "Remote"),
        ("REMOTE", "Remote"),
        ("Work From Home", "Remote"),
        ("wfh", "Remote"),
        ("Hybrid", "Hybrid"),
        ("On-site", "On-site"),
        ("San Francisco, CA", "San Francisco, CA"),
    ],
)
def test_location_normalization(raw_value, expected):
    assert JobNormalizer.normalize_location(raw_value) == expected


def test_canonical_payload_validation_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="title"):
        JobNormalizer.normalize(
            {
                "company": "OpenAI",
                "url": "https://jobs.example.com/missing-title",
            },
            source=SourceDetector.CAREER_SITE,
        )

    with pytest.raises(ValueError, match="source_url_or_external_id"):
        JobNormalizer.normalize(
            {
                "title": "Backend Engineer",
                "company": "OpenAI",
            },
            source=SourceDetector.CAREER_SITE,
        )


def test_source_config_can_supply_company_name():
    source = JobSource(
        name="OpenAI Greenhouse",
        resource=JobSource.ResourceChoices.GREENHOUSE,
        base_url="https://boards.greenhouse.io/openai",
        filter_config={"company_name": "OpenAI"},
    )

    payload = JobNormalizer.normalize(
        {
            "title": "Platform Engineer",
            "absolute_url": "https://boards.greenhouse.io/openai/jobs/100",
        },
        source=source,
    )

    assert payload.source == "greenhouse"
    assert payload.company_name == "OpenAI"
