import pytest
from django.db import IntegrityError, transaction

from apps.imports.services import JobSyncService
from apps.jobs.forms import JobPostForm
from apps.jobs.identity import JobIdentityService
from apps.jobs.models import JobPost


def test_linkedin_tracking_urls_share_one_canonical_identity():
    first = JobIdentityService.canonicalize_url(
        "https://www.linkedin.com/jobs/view/backend-engineer-4456520247/"
        "?refId=abc&utm_source=email"
    )
    second = JobIdentityService.canonicalize_url(
        "http://linkedin.com/jobs/view/4456520247?trackingId=xyz"
    )

    assert first == "https://linkedin.com/jobs/view/4456520247"
    assert second == first


def test_greenhouse_host_aliases_share_one_canonical_identity():
    first = JobIdentityService.canonicalize_url(
        "https://boards.greenhouse.io/openai/jobs/123/?gh_jid=123"
    )
    second = JobIdentityService.canonicalize_url(
        "https://job-boards.greenhouse.io/openai/jobs/123"
    )

    assert first == "https://greenhouse.io/openai/jobs/123"
    assert second == first


def test_lever_api_and_hosted_urls_share_tenant_identity():
    hosted = JobIdentityService.build(
        source_url="https://jobs.eu.lever.co/acme/job-123?utm_source=email",
        external_id="job-123",
        company_name="Acme",
    )
    api = JobIdentityService.build(
        source_url="https://api.eu.lever.co/v0/postings/acme/job-123",
        external_id="job-123",
        company_name="Acme",
    )

    assert hosted.canonical_source_url == "https://jobs.eu.lever.co/acme/job-123"
    assert api.canonical_source_url == hosted.canonical_source_url
    assert hosted.source_key == "lever:acme"
    assert api.source_key == hosted.source_key


def test_canonical_url_removes_tracking_but_preserves_job_query_parameters():
    canonical = JobIdentityService.canonicalize_url(
        "https://stripe.com/jobs/search?utm_campaign=test&gh_jid=8146271&ref=mail"
    )

    assert canonical == "https://stripe.com/jobs/search?gh_jid=8146271"


def test_source_keys_scope_external_ids_by_provider_and_company():
    linkedin = JobIdentityService.build(
        source_url="https://www.linkedin.com/jobs/view/123",
        external_id="123",
        company_name="OpenAI",
    )
    greenhouse = JobIdentityService.build(
        source_url="https://boards.greenhouse.io/openai/jobs/123",
        external_id="123",
        company_name="OpenAI",
    )
    other_company = JobIdentityService.build(
        source_url="https://careers.example.com/jobs/123",
        external_id="123",
        company_name="Anthropic",
    )

    assert linkedin.source_key == "linkedin"
    assert greenhouse.source_key == "greenhouse:openai"
    assert other_company.source_key == "careers.example.com:anthropic"


@pytest.mark.django_db
def test_job_model_populates_identity_fields(company):
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url=(
            "https://www.linkedin.com/jobs/view/backend-engineer-4456520247/"
            "?refId=abc"
        ),
        external_id="  ABC-123  ",
    )

    assert job.canonical_source_url == "https://linkedin.com/jobs/view/4456520247"
    assert job.normalized_external_id == "abc-123"
    assert job.source_key == "linkedin"


@pytest.mark.django_db
def test_job_model_refreshes_identity_when_source_url_changes(company):
    job = JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://careers.example.com/jobs/123?utm_source=email",
    )

    job.source_url = "https://www.linkedin.com/jobs/view/4456520247/?refId=abc"
    job.save(update_fields=["source_url"])

    job.refresh_from_db()
    assert job.canonical_source_url == "https://linkedin.com/jobs/view/4456520247"
    assert job.source_key == "linkedin"


@pytest.mark.django_db
def test_database_rejects_duplicate_canonical_source_url(company):
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/4456520247/?refId=abc",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        JobPost.objects.create(
            company=company,
            title="Duplicate",
            source_url=(
                "https://linkedin.com/jobs/view/backend-engineer-4456520247"
                "?trackingId=xyz"
            ),
        )


@pytest.mark.django_db
def test_sync_updates_job_when_source_url_only_differs_by_tracking(company):
    first = JobSyncService.upsert_job(
        {
            "source": "linkedin",
            "title": "Backend Engineer",
            "company_name": company.name,
            "source_url": "https://www.linkedin.com/jobs/view/4456520247/?refId=abc",
            "external_id": "",
        }
    )
    second = JobSyncService.upsert_job(
        {
            "source": "linkedin",
            "title": "Senior Backend Engineer",
            "company_name": company.name,
            "source_url": (
                "https://linkedin.com/jobs/view/backend-engineer-4456520247"
                "?trackingId=xyz"
            ),
            "external_id": "",
        }
    )

    assert first.created is True
    assert second.created is False
    assert second.job.pk == first.job.pk
    assert JobPost.objects.count() == 1


@pytest.mark.django_db
def test_sync_does_not_merge_same_external_id_across_sources(company):
    linkedin = JobSyncService.upsert_job(
        {
            "source": "linkedin",
            "title": "LinkedIn Role",
            "company_name": company.name,
            "source_url": "https://www.linkedin.com/jobs/view/123",
            "external_id": "123",
        }
    )
    greenhouse = JobSyncService.upsert_job(
        {
            "source": "greenhouse",
            "title": "Greenhouse Role",
            "company_name": company.name,
            "source_url": "https://boards.greenhouse.io/openai/jobs/123",
            "external_id": "123",
        }
    )

    assert linkedin.created is True
    assert greenhouse.created is True
    assert linkedin.job.pk != greenhouse.job.pk
    assert JobPost.objects.count() == 2


@pytest.mark.django_db
def test_sync_rejects_conflicting_url_and_external_id_identity(company):
    first = JobSyncService.upsert_job(
        {
            "source": "linkedin",
            "title": "First Role",
            "company_name": company.name,
            "source_url": "https://www.linkedin.com/jobs/view/100",
            "external_id": "100",
        }
    ).job
    second = JobSyncService.upsert_job(
        {
            "source": "linkedin",
            "title": "Second Role",
            "company_name": company.name,
            "source_url": "https://www.linkedin.com/jobs/view/200",
            "external_id": "200",
        }
    ).job

    with pytest.raises(ValueError, match="Job identity conflict"):
        JobSyncService.upsert_job(
            {
                "source": "linkedin",
                "title": "Conflicting Role",
                "company_name": company.name,
                "source_url": first.source_url,
                "external_id": second.external_id,
            }
        )

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.title == "First Role"
    assert second.title == "Second Role"


@pytest.mark.django_db
def test_job_form_reports_duplicate_canonical_url(company):
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/4456520247/?refId=abc",
    )
    form = JobPostForm(
        data={
            "company": company.name,
            "title": "Duplicate",
            "source_url": (
                "https://linkedin.com/jobs/view/backend-engineer-4456520247"
                "?trackingId=xyz"
            ),
            "external_id": "",
            "source_type": JobPost.SourceType.URL,
            "status": JobPost.StatusChoices.ACTIVE,
            "employment_type": "",
            "skill_keywords": "",
        }
    )

    assert form.is_valid() is False
    assert form.errors["source_url"] == [
        "A job with this canonical source URL already exists."
    ]


@pytest.mark.django_db
def test_job_api_rejects_duplicate_canonical_url(client, company):
    JobPost.objects.create(
        company=company,
        title="Backend Engineer",
        source_url="https://www.linkedin.com/jobs/view/4456520247/?refId=abc",
    )

    response = client.post(
        "/api/jobs/",
        data={
            "company": company.pk,
            "title": "Duplicate",
            "source_url": (
                "https://linkedin.com/jobs/view/backend-engineer-4456520247"
                "?trackingId=xyz"
            ),
        },
    )

    assert response.status_code == 400
    assert response.json()["source_url"] == [
        "A job with this canonical source URL already exists."
    ]
