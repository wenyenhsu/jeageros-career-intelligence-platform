from datetime import UTC, datetime

import pytest
from django.urls import reverse

from apps.companies.models import Company
from apps.jobs.models import JobPost
from apps.skills.models import JobPostSkill, SkillKeyword, SkillSet


@pytest.fixture
def searchable_jobs(company):
    second_company = Company.objects.create(name="Anthropic")
    python = SkillSet.objects.create(name="Python", aliases=["Py"])
    django = SkillSet.objects.create(name="Django")

    backend = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        employment_type="Full-time",
        location="San Francisco",
    )
    intern = JobPost.objects.create(
        company=second_company,
        title="Research Assistant",
        employment_type="Internship",
        location="Remote",
    )
    JobPostSkill.objects.create(job_post=backend, skill_set=python)
    JobPostSkill.objects.create(job_post=intern, skill_set=django)
    SkillKeyword.ensure_for_skillset(django, "Django ORM")
    return {
        "backend": backend,
        "intern": intern,
    }


@pytest.mark.django_db
def test_job_search_by_title_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Backend"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Backend Engineer" in content
    assert "Research Assistant" not in content


@pytest.mark.django_db
def test_job_search_form_supports_auto_search(client, searchable_jobs):
    response = client.get(reverse("job-list"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-auto-search-form" in content
    assert "data-auto-search-input" in content


@pytest.mark.django_db
def test_job_search_by_company_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Anthropic"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_job_search_by_skill_keyword_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "py"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Backend Engineer" in content
    assert "Research Assistant" not in content


@pytest.mark.django_db
def test_job_search_by_skillset_name_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Django"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_job_search_by_job_type_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Internship"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_job_search_by_partial_job_type_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "intern"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_job_search_by_display_job_type_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Full Time"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Backend Engineer" in content
    assert "Research Assistant" not in content


@pytest.mark.django_db
def test_job_search_by_location_works(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Remote"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_job_search_by_created_date_works(client, searchable_jobs):
    JobPost.objects.filter(pk=searchable_jobs["backend"].pk).update(
        created_at=datetime(2026, 5, 10, 8, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 10, 8, 5, tzinfo=UTC),
    )
    JobPost.objects.filter(pk=searchable_jobs["intern"].pk).update(
        created_at=datetime(2026, 6, 18, 9, 23, tzinfo=UTC),
        updated_at=datetime(2026, 6, 18, 9, 25, tzinfo=UTC),
    )

    response = client.get(reverse("job-list"), {"q": "2026-06-18"})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Research Assistant" in content
    assert "Backend Engineer" not in content


@pytest.mark.django_db
def test_empty_job_search_returns_all_jobs(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "   "})

    assert response.status_code == 200
    content = response.content.decode()
    assert "Backend Engineer" in content
    assert "Research Assistant" in content


@pytest.mark.django_db
def test_no_match_job_search_shows_search_empty_state(client, searchable_jobs):
    response = client.get(reverse("job-list"), {"q": "Cobol"})

    assert response.status_code == 200
    content = response.content.decode()
    assert 'No jobs match "Cobol"' in content
    assert "Create your first job" not in content


@pytest.mark.django_db
def test_api_job_search_by_job_type_matches_list_behavior(
    client, user, searchable_jobs
):
    client.force_login(user)

    response = client.get("/api/jobs/", {"q": "Internship"})

    assert response.status_code == 200
    payload = response.json()
    assert [job["title"] for job in payload] == ["Research Assistant"]
