import pytest
from django.urls import reverse

from apps.imports.models import JobSource


@pytest.fixture
def searchable_sources():
    linkedin = JobSource.objects.create(
        name="LinkedIn Data Analyst - Intern",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/",
        enabled=True,
        notes="Primary internship feed",
        filter_config={
            "search_keywords": ["data analyst", "intern"],
            "include_keywords": ["python"],
            "target_companies": ["OpenAI"],
        },
    )
    disabled = JobSource.objects.create(
        name="LinkedIn backend - no limit",
        resource=JobSource.Resource.LINKEDIN,
        base_url="https://www.linkedin.com/jobs/search/?keywords=backend",
        enabled=False,
        notes="Paused backend crawl",
        filter_config={
            "search_keywords": ["backend engineer"],
            "exclude_keywords": ["senior"],
        },
    )
    return {
        "linkedin": linkedin,
        "disabled": disabled,
    }


@pytest.mark.django_db
def test_job_source_search_form_supports_auto_search(client, searchable_sources):
    response = client.get(reverse("source-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-auto-search-form" in content
    assert "data-auto-search-input" in content
    assert 'name="q"' in content


@pytest.mark.django_db
def test_job_source_search_by_name_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "Data Analyst"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn Data Analyst - Intern" in content
    assert "LinkedIn backend - no limit" not in content


@pytest.mark.django_db
def test_job_source_search_by_resource_type_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "LinkedIn"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn Data Analyst - Intern" in content
    assert "LinkedIn backend - no limit" in content


@pytest.mark.django_db
def test_job_source_search_by_filter_keyword_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "OpenAI"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn Data Analyst - Intern" in content
    assert "LinkedIn backend - no limit" not in content


@pytest.mark.django_db
def test_job_source_search_by_enabled_status_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "disabled"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn backend - no limit" in content
    assert "LinkedIn Data Analyst - Intern" not in content


@pytest.mark.django_db
def test_job_source_search_by_partial_disabled_status_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "disa"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn backend - no limit" in content
    assert "LinkedIn Data Analyst - Intern" not in content


@pytest.mark.django_db
def test_job_source_search_by_partial_enabled_status_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "ena"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn Data Analyst - Intern" in content
    assert "LinkedIn backend - no limit" not in content


@pytest.mark.django_db
def test_job_source_search_by_notes_works(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "internship feed"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "LinkedIn Data Analyst - Intern" in content
    assert "LinkedIn backend - no limit" not in content


@pytest.mark.django_db
def test_job_source_search_shows_empty_state(client, searchable_sources):
    response = client.get(reverse("source-list"), {"q": "nonexistent-source"})

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No sources match "nonexistent-source"' in content
    assert "Clear search" in content
