import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from apps.imports.models import PipelineLog
from apps.imports.services import CompanyJobRefreshService
from apps.jobs.models import JobPost


@pytest.mark.django_db
def test_company_job_refresh_queues_only_supported_non_archived_jobs(
    company, monkeypatch
):
    refreshable = JobPost.objects.create(
        company=company,
        title="Refreshable",
        source_url="https://www.linkedin.com/jobs/view/123/",
    )
    JobPost.objects.create(company=company, title="Manual")
    JobPost.objects.create(
        company=company,
        title="Drive Folder",
        source_url="https://drive.google.com/drive/folders/abc123",
    )
    JobPost.objects.create(
        company=company,
        title="Archived",
        source_url="https://example.com/jobs/archived",
        status=JobPost.StatusChoices.ARCHIVED,
    )
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id, **kwargs: queued.append((job_id, kwargs)),
    )

    result = CompanyJobRefreshService.queue(company)

    assert queued == [(refreshable.id, {"force": True})]
    assert result.total_jobs == 4
    assert result.queued_jobs == 1
    assert result.skipped_without_url == 1
    assert result.skipped_unsupported_url == 1
    assert result.skipped_archived == 1
    assert result.failed_jobs == 0
    assert PipelineLog.objects.filter(
        step_name="company_job_refresh_queue",
        status=PipelineLog.StatusChoices.SUCCESS,
        company=company,
        metadata__queued_jobs=1,
    ).exists()


@pytest.mark.django_db
def test_company_sync_view_reports_queue_and_skip_counts(client, company, monkeypatch):
    refreshable = JobPost.objects.create(
        company=company,
        title="Refreshable",
        source_url="https://example.com/jobs/123",
    )
    JobPost.objects.create(company=company, title="Manual")
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id, **kwargs: queued.append((job_id, kwargs)),
    )

    response = client.post(reverse("company-sync-jobs", args=[company.id]))

    assert response.status_code == 302
    assert response.url == reverse("company-detail", args=[company.id])
    assert queued == [(refreshable.id, {"force": True})]
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert any("Queued 1 job refresh task(s)." in message for message in messages)
    assert any("Skipped 1 without a source URL" in message for message in messages)


@pytest.mark.django_db
def test_company_sync_view_reports_when_no_jobs_are_refreshable(
    client, company, monkeypatch
):
    JobPost.objects.create(company=company, title="Manual")
    queued = []
    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        lambda job_id, **kwargs: queued.append((job_id, kwargs)),
    )

    response = client.post(reverse("company-sync-jobs", args=[company.id]))

    assert response.status_code == 302
    assert queued == []
    messages = [str(message) for message in get_messages(response.wsgi_request)]
    assert messages == [
        "No refreshable jobs found. Add a supported source URL to a non-archived job."
    ]


@pytest.mark.django_db
def test_company_job_refresh_records_task_queue_failure(company, monkeypatch):
    job = JobPost.objects.create(
        company=company,
        title="Refreshable",
        source_url="https://example.com/jobs/123",
    )

    def fail_to_queue(job_id, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "apps.imports.tasks.refresh_job_from_url.delay",
        fail_to_queue,
    )

    result = CompanyJobRefreshService.queue(company)

    assert result.queued_jobs == 0
    assert result.failed_jobs == 1
    assert PipelineLog.objects.filter(
        step_name="company_job_refresh_queue_item",
        status=PipelineLog.StatusChoices.FAILED,
        job=job,
        error_text__contains="broker unavailable",
    ).exists()
    assert PipelineLog.objects.filter(
        step_name="company_job_refresh_queue",
        status=PipelineLog.StatusChoices.FAILED,
        company=company,
        metadata__failed_jobs=1,
    ).exists()
