import json

import pytest
from django.urls import reverse

from apps.companies.models import Company
from apps.imports.models import PipelineLog
from apps.imports.services import (
    CanonicalJobPayload,
    CompanyUpsertService,
    JobSyncService,
)
from apps.jobs.models import JobPost


@pytest.mark.django_db
def test_company_upsert_creates_and_updates_existing_company():
    created_result = CompanyUpsertService.upsert(" OpenAI ", "https://openai.com")

    assert created_result.created is True
    assert created_result.company.name == "OpenAI"
    assert created_result.company.website == "https://openai.com"

    updated_result = CompanyUpsertService.upsert("OpenAI", "https://jobs.openai.com")

    assert updated_result.created is False
    assert updated_result.company.id == created_result.company.id
    assert updated_result.company.website == "https://jobs.openai.com"
    assert Company.objects.count() == 1


@pytest.mark.django_db
def test_company_upsert_matches_existing_company_by_normalized_name():
    company = Company.objects.create(name="  OpenAI  ")

    result = CompanyUpsertService.upsert("OpenAI")

    company.refresh_from_db()
    assert result.created is False
    assert result.company.id == company.id
    assert company.name == "OpenAI"
    assert Company.objects.count() == 1


@pytest.mark.django_db
def test_job_sync_creates_job_from_canonical_dict():
    result = JobSyncService.upsert_job(
        {
            "source": "greenhouse",
            "title": "Backend Engineer",
            "company_name": "OpenAI",
            "source_url": "https://jobs.example.com/openai/backend-engineer",
            "external_id": "openai-backend-engineer",
            "remote_type": "Remote",
            "location": "Remote",
            "employment_type": "FULL_TIME",
            "description": "Build Django services.",
            "sections": {"requirements": "Python"},
            "metadata": {"company_website": "https://openai.com"},
        }
    )

    assert result.created is True
    assert result.job.company.name == "OpenAI"
    assert result.job.title == "Backend Engineer"
    assert result.job.source_url == "https://jobs.example.com/openai/backend-engineer"
    assert result.job.external_id == "openai-backend-engineer"
    assert result.job.location == "Remote"
    assert result.job.remote_type == "Remote"
    assert result.job.employment_type == "Full-time"
    assert result.job.status == JobPost.StatusChoices.ACTIVE
    assert result.job.source_type == JobPost.SourceType.URL
    assert result.job.last_synced_at is not None
    assert result.job.company.website == "https://openai.com"


@pytest.mark.django_db
def test_job_sync_accepts_canonical_payload_dataclass():
    payload = CanonicalJobPayload(
        source="lever",
        source_url="https://jobs.lever.co/openai/platform-engineer",
        external_id="platform-engineer",
        company_name="OpenAI",
        title="Platform Engineer",
        job_type="FULL_TIME",
        employment_type="FULL_TIME",
        remote_type="Hybrid",
        location="San Francisco, CA",
        description="Build internal platforms.",
        sections={"requirements": "Django and Python"},
        posted_at="2026-06-11",
        metadata={"source": "lever"},
    )

    result = JobSyncService.upsert_job(payload)

    assert result.created is True
    assert result.job.title == "Platform Engineer"
    assert result.job.remote_type == "Hybrid"
    assert result.job.employment_type == "Full-time"


@pytest.mark.django_db
def test_job_sync_rejects_source_specific_parser_payload():
    with pytest.raises(ValueError, match="canonical job payload fields only"):
        JobSyncService.upsert_job(
            {
                "jobTitle": "Backend Engineer",
                "companyName": "OpenAI",
                "jobUrl": "https://www.linkedin.com/jobs/view/123",
                "jobPostingId": "123",
            }
        )


@pytest.mark.django_db
def test_job_sync_updates_existing_job_by_external_id():
    original = JobSyncService.upsert_job(
        {
            "title": "Backend Engineer",
            "company_name": "OpenAI",
            "source_url": "https://jobs.example.com/openai/backend-engineer",
            "external_id": "openai-backend-engineer",
            "location": "Remote",
            "employment_type": "Full-time",
            "description": "Original description.",
        }
    ).job

    result = JobSyncService.upsert_job(
        {
            "title": "Senior Backend Engineer",
            "company_name": "OpenAI",
            "source_url": "https://jobs.example.com/openai/backend-engineer-updated",
            "external_id": "openai-backend-engineer",
            "location": "San Francisco, CA",
            "employment_type": "Full-time",
            "description": "Updated description.",
        }
    )

    original.refresh_from_db()
    assert result.created is False
    assert result.job.id == original.id
    assert original.title == "Senior Backend Engineer"
    assert (
        original.source_url
        == "https://jobs.example.com/openai/backend-engineer-updated"
    )
    assert original.location == "San Francisco, CA"
    assert original.description == "Updated description."
    assert JobPost.objects.count() == 1


@pytest.mark.django_db
def test_job_sync_prevents_duplicate_jobs_by_source_url():
    payload = {
        "title": "Frontend Engineer",
        "company_name": "OpenAI",
        "source_url": "https://jobs.example.com/openai/frontend-engineer",
        "external_id": "",
        "location": "Remote",
        "employment_type": "Full-time",
        "description": "Build interfaces.",
    }

    first = JobSyncService.upsert_job(payload)
    second = JobSyncService.upsert_job({**payload, "title": "Frontend Engineer II"})

    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id
    assert JobPost.objects.count() == 1
    first.job.refresh_from_db()
    assert first.job.title == "Frontend Engineer II"


@pytest.mark.django_db
def test_company_sync_marks_missing_source_jobs_closed(company):
    found_job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_type=JobPost.SourceType.URL,
        source_url="https://jobs.example.com/openai/backend-engineer",
        external_id="openai-backend-engineer",
    )
    missing_job = JobPost.objects.create(
        company=company,
        title="Data Engineer",
        source_type=JobPost.SourceType.URL,
        source_url="https://jobs.example.com/openai/data-engineer",
        external_id="openai-data-engineer",
    )
    manual_job = JobPost.objects.create(
        company=company,
        title="Manually Tracked Role",
    )

    result = JobSyncService.sync_company(
        company,
        [
            {
                "title": "Backend Engineer",
                "company_name": company.name,
                "source_url": found_job.source_url,
                "external_id": found_job.external_id,
                "location": "Remote",
                "employment_type": "Full-time",
                "description": "Still listed.",
            }
        ],
    )

    found_job.refresh_from_db()
    missing_job.refresh_from_db()
    manual_job.refresh_from_db()
    assert result.jobs_created == 0
    assert result.jobs_updated == 1
    assert result.jobs_closed == 1
    assert found_job.status == JobPost.StatusChoices.ACTIVE
    assert missing_job.status == JobPost.StatusChoices.CLOSED
    assert missing_job.last_synced_at is not None
    assert manual_job.status == JobPost.StatusChoices.ACTIVE


@pytest.mark.django_db
def test_company_sync_closes_missing_jobs_within_same_source_scope(company):
    found_linkedin_job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_type=JobPost.SourceType.URL,
        source_url="https://www.linkedin.com/jobs/view/100",
        external_id="linkedin-100",
    )
    missing_linkedin_job = JobPost.objects.create(
        company=company,
        title="Data Engineer",
        source_type=JobPost.SourceType.URL,
        source_url="https://www.linkedin.com/jobs/view/200",
        external_id="linkedin-200",
    )
    lever_job = JobPost.objects.create(
        company=company,
        title="ML Engineer",
        source_type=JobPost.SourceType.URL,
        source_url="https://jobs.lever.co/openai/ml-engineer",
        external_id="lever-ml",
    )

    result = JobSyncService.sync_company(
        company,
        [
            {
                "source": "linkedin",
                "title": "Backend Engineer",
                "company_name": company.name,
                "source_url": found_linkedin_job.source_url,
                "external_id": found_linkedin_job.external_id,
                "location": "Remote",
                "employment_type": "FULL_TIME",
                "description": "Still listed.",
            }
        ],
    )

    found_linkedin_job.refresh_from_db()
    missing_linkedin_job.refresh_from_db()
    lever_job.refresh_from_db()
    assert result.jobs_closed == 1
    assert found_linkedin_job.status == JobPost.StatusChoices.ACTIVE
    assert missing_linkedin_job.status == JobPost.StatusChoices.CLOSED
    assert lever_job.status == JobPost.StatusChoices.ACTIVE


@pytest.mark.django_db
def test_company_sync_logs_summary(company):
    result = JobSyncService.sync_company(
        company,
        [
            {
                "source": "greenhouse",
                "title": "Backend Engineer",
                "company_name": company.name,
                "source_url": "https://boards.greenhouse.io/openai/jobs/100",
                "external_id": "greenhouse-100",
                "location": "Remote",
                "employment_type": "FULL_TIME",
                "description": "Build Django services.",
            }
        ],
    )

    log = PipelineLog.objects.filter(step_name="company_sync").latest("created_at")
    assert result.jobs_created == 1
    assert log.status == PipelineLog.StatusChoices.SUCCESS
    assert log.company == company
    assert log.metadata["jobs_created"] == 1


@pytest.mark.django_db
def test_company_sync_api_returns_sync_counts(client, user, company):
    client.force_login(user)

    response = client.post(
        f"/api/companies/{company.id}/sync/",
        data=json.dumps(
            {
                "jobs": [
                    {
                        "source": "career_site",
                        "title": "Backend Engineer",
                        "company_name": company.name,
                        "source_url": "https://jobs.example.com/openai/backend-engineer",
                        "external_id": "openai-backend-engineer",
                        "location": "Remote",
                        "employment_type": "Full-time",
                        "description": "Build Django services.",
                    }
                ]
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "jobs_created": 1,
        "jobs_updated": 0,
        "jobs_closed": 0,
    }


@pytest.mark.django_db
def test_company_sync_api_rejects_source_specific_payload(client, user, company):
    client.force_login(user)

    response = client.post(
        f"/api/companies/{company.id}/sync/",
        data=json.dumps(
            {
                "jobs": [
                    {
                        "jobTitle": "Backend Engineer",
                        "companyName": company.name,
                        "jobUrl": "https://www.linkedin.com/jobs/view/123",
                    }
                ]
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert "canonical job payload fields only" in response.json()["detail"]


@pytest.mark.django_db
def test_company_detail_exposes_sync_jobs_button(client, company):
    response = client.get(reverse("company-detail", args=[company.id]))

    assert response.status_code == 200
    assert "Sync Jobs" in response.content.decode()


@pytest.mark.django_db
def test_company_sync_button_route_redirects_to_company_detail(client, company):
    response = client.post(reverse("company-sync-jobs", args=[company.id]))

    assert response.status_code in (302, 303)
    assert response.url == reverse("company-detail", args=[company.id])
