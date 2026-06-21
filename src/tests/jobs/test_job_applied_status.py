import pytest
from django.urls import reverse

from apps.applications.models import Application
from apps.companies.models import Company
from apps.jobs.models import JobPost


@pytest.mark.django_db
def test_application_create_sets_job_status_applied(user):
    company = Company.objects.create(name="OpenAI")
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        status=JobPost.StatusChoices.ACTIVE,
    )

    Application.objects.create(user=user, job_post=job)

    job.refresh_from_db()
    assert job.status == JobPost.StatusChoices.APPLIED


@pytest.mark.django_db
def test_application_delete_reverts_job_status_to_active(user):
    company = Company.objects.create(name="OpenAI")
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        status=JobPost.StatusChoices.APPLIED,
    )
    application = Application.objects.create(user=user, job_post=job)

    application.delete()

    job.refresh_from_db()
    assert job.status == JobPost.StatusChoices.ACTIVE


@pytest.mark.django_db
def test_dashboard_shows_applied_job_status_segment(client, user):
    company = Company.objects.create(name="OpenAI")
    job = JobPost.objects.create(
        company=company,
        title="Applied Role",
        status=JobPost.StatusChoices.ACTIVE,
    )
    Application.objects.create(
        user=user,
        job_post=job,
        status=Application.Status.APPLIED,
    )

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Applied 1" in content
    assert "status-segment-applied" in content
