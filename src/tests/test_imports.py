import pytest
from django.urls import reverse

from apps.imports.models import JobSource


@pytest.mark.django_db
def test_job_source_str():
    source = JobSource.objects.create(
        name="LinkedIn",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/",
        enabled=True,
    )

    assert str(source) == "LinkedIn (LinkedIn)"


@pytest.mark.django_db
def test_source_list_view(client):
    JobSource.objects.create(name="LinkedIn", resource=JobSource.Resource.LINKEDIN, base_url="https://www.linkedin.com/jobs/")

    response = client.get(reverse("source-list"))

    assert response.status_code == 200
    assert "LinkedIn" in response.content.decode()


@pytest.mark.django_db
def test_source_create_view(client):
    payload = {
        "name": "Greenhouse",
        "resource": JobSource.Resource.GREENHOUSE,
        "base_url": "https://boards.greenhouse.io/",
        "enabled": True,
        "crawl_interval_minutes": 720,
        "crawl_config": '{"pages": 2}',
        "filter_config": '{"include_keywords": ["python"]}',
        "notes": "Test source",
    }

    response = client.post(reverse("source-create"), data=payload)

    assert response.status_code in (302, 303)
    assert JobSource.objects.filter(name="Greenhouse").exists()
