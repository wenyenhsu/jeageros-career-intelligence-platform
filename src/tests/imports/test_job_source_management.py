import json

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.imports.models import JobSource
from apps.imports.services import ParserRegistry, SourceDetector

EXPECTED_RESOURCES = {
    SourceDetector.LINKEDIN,
    SourceDetector.HANDSHAKE,
    SourceDetector.GREENHOUSE,
    SourceDetector.LEVER,
    SourceDetector.CAREER_SITE,
    SourceDetector.RSS,
    SourceDetector.API,
    SourceDetector.GENERIC_HTML,
}


def test_job_source_choices_match_registered_parser_types():
    resource_values = {value for value, _label in JobSource.ResourceChoices.choices}

    assert resource_values == EXPECTED_RESOURCES
    assert EXPECTED_RESOURCES.issubset(ParserRegistry._parsers)


def test_source_detector_preserves_explicit_generic_html_resource():
    source = JobSource(
        name="Company career HTML",
        resource=JobSource.ResourceChoices.GENERIC_HTML,
        base_url="https://careers.example.com/jobs",
    )

    assert (
        SourceDetector.detect_parser_type(source)
        == JobSource.ResourceChoices.GENERIC_HTML
    )


@pytest.mark.parametrize(
    ("resource", "base_url"),
    [
        (JobSource.ResourceChoices.LINKEDIN, "https://linkedin.com/jobs/search/"),
        (
            JobSource.ResourceChoices.HANDSHAKE,
            "https://app.joinhandshake.com/stu/postings",
        ),
        (
            JobSource.ResourceChoices.GREENHOUSE,
            "https://job-boards.greenhouse.io/acme",
        ),
        (JobSource.ResourceChoices.LEVER, "https://jobs.lever.co/acme"),
        (JobSource.ResourceChoices.CAREER_SITE, "https://careers.example.com/jobs"),
        (JobSource.ResourceChoices.RSS, "https://careers.example.com/jobs.xml"),
        (JobSource.ResourceChoices.API, "https://api.example.com/jobs"),
        (JobSource.ResourceChoices.GENERIC_HTML, "https://example.com/careers"),
    ],
)
def test_job_source_accepts_compatible_urls(resource, base_url):
    source = JobSource(name="Source", resource=resource, base_url=base_url)

    source.full_clean()


def test_job_source_rejects_provider_url_mismatch():
    source = JobSource(
        name="Wrong provider",
        resource=JobSource.ResourceChoices.LEVER,
        base_url="https://www.linkedin.com/jobs/search/",
    )

    with pytest.raises(ValidationError) as exc_info:
        source.full_clean()

    assert "jobs.lever.co" in exc_info.value.message_dict["base_url"][0]


def test_enabled_job_source_requires_base_url():
    source = JobSource(
        name="Missing URL",
        resource=JobSource.ResourceChoices.API,
        base_url="",
        enabled=True,
    )

    with pytest.raises(ValidationError) as exc_info:
        source.full_clean()

    assert "requires a base URL" in exc_info.value.message_dict["base_url"][0]


@pytest.mark.django_db
def test_regular_user_cannot_create_copy_or_delete_source(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )

    create_response = client.get(reverse("source-create"))
    copy_response = client.post(reverse("source-copy", args=[source.pk]))
    delete_response = client.post(reverse("source-delete", args=[source.pk]))

    assert create_response.status_code == 403
    assert copy_response.status_code == 403
    assert delete_response.status_code == 403
    assert JobSource.objects.filter(pk=source.pk).exists()


@pytest.mark.django_db
def test_regular_user_can_update_filters_but_not_resource(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )

    page_response = client.get(reverse("source-update", args=[source.pk]))
    update_response = client.post(
        reverse("source-update", args=[source.pk]),
        data={
            "name": source.name,
            "resource": JobSource.ResourceChoices.GREENHOUSE,
            "base_url": source.base_url,
            "enabled": "on",
            "crawl_interval_minutes": 720,
            "include_keywords": "python, django",
            "notes": "User-managed filters",
        },
    )

    assert page_response.status_code == 200
    page_content = page_response.content.decode()
    assert '<select name="resource"' not in page_content
    assert "Managed by a system administrator" in page_content
    assert update_response.status_code == 302
    source.refresh_from_db()
    assert source.resource == JobSource.ResourceChoices.LINKEDIN
    assert source.crawl_interval_minutes == 720
    assert source.filter_config["include_keywords"] == ["python", "django"]


@pytest.mark.django_db
def test_regular_user_api_cannot_create_or_change_resource(client):
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.ResourceChoices.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
    )

    create_response = client.post(
        "/api/sources/",
        data=json.dumps(
            {
                "name": "Lever",
                "resource": JobSource.ResourceChoices.LEVER,
                "base_url": "https://jobs.lever.co/acme",
            }
        ),
        content_type="application/json",
    )
    update_response = client.patch(
        f"/api/sources/{source.pk}/",
        data=json.dumps(
            {
                "name": "LinkedIn filters",
                "resource": JobSource.ResourceChoices.GREENHOUSE,
            }
        ),
        content_type="application/json",
    )

    assert create_response.status_code == 403
    assert update_response.status_code == 200
    source.refresh_from_db()
    assert source.name == "LinkedIn filters"
    assert source.resource == JobSource.ResourceChoices.LINKEDIN


@pytest.mark.django_db
def test_staff_api_can_create_registered_source(client, user):
    user.is_staff = True
    user.save(update_fields=["is_staff"])

    response = client.post(
        "/api/sources/",
        data=json.dumps(
            {
                "name": "Careers API",
                "resource": JobSource.ResourceChoices.API,
                "base_url": "https://api.example.com/jobs",
                "enabled": True,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201, response.content
    assert JobSource.objects.filter(
        name="Careers API",
        resource=JobSource.ResourceChoices.API,
    ).exists()
