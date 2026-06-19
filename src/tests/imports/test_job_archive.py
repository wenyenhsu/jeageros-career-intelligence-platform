import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.imports.models import JobArchiveRun, PipelineLog
from apps.imports.services.job_archive_service import JobArchiveService
from apps.jobs.models import JobPost
from apps.skills.models import SkillSet


@pytest.mark.django_db
def test_job_archive_service_archives_old_jobs_and_exports_payload(company):
    old_job = JobPost.objects.create(
        company=company,
        title="Legacy Backend Engineer",
        source_url="https://example.com/jobs/legacy",
    )
    recent_job = JobPost.objects.create(company=company, title="Recent Engineer")
    python = SkillSet.objects.create(name="Python")
    old_job.skill_sets.add(python)
    old_created_at = timezone.now() - timedelta(days=200)
    recent_created_at = timezone.now() - timedelta(days=20)
    JobPost.objects.filter(id=old_job.id).update(created_at=old_created_at)
    JobPost.objects.filter(id=recent_job.id).update(created_at=recent_created_at)

    archive_run = JobArchiveService.archive_old_jobs(age_months=3)
    old_job.refresh_from_db()
    recent_job.refresh_from_db()

    assert archive_run.jobs_archived == 1
    assert old_job.status == JobPost.StatusChoices.ARCHIVED
    assert recent_job.status == JobPost.StatusChoices.ACTIVE
    assert archive_run.payload["age_months"] == 3
    assert archive_run.payload["jobs"][0]["id"] == old_job.id
    assert archive_run.payload["jobs"][0]["skill_sets"][0]["name"] == "Python"
    assert PipelineLog.objects.filter(
        step_name="job_archive",
        status=PipelineLog.StatusChoices.SUCCESS,
    ).exists()


@pytest.mark.django_db
def test_job_archive_restore_sets_jobs_active_and_refreshes_created_at(company):
    old_job = JobPost.objects.create(company=company, title="Old Data Engineer")
    old_created_at = timezone.now() - timedelta(days=200)
    JobPost.objects.filter(id=old_job.id).update(created_at=old_created_at)
    archive_run = JobArchiveService.archive_old_jobs(age_months=3)
    old_job.refresh_from_db()
    assert old_job.status == JobPost.StatusChoices.ARCHIVED

    result = JobArchiveService.restore_archive(archive_run)
    archive_run.refresh_from_db()
    old_job.refresh_from_db()

    assert result["jobs_restored"] == 1
    assert archive_run.status == JobArchiveRun.StatusChoices.RESTORED
    assert archive_run.jobs_restored == 1
    assert archive_run.restored_at is not None
    assert old_job.status == JobPost.StatusChoices.ACTIVE
    assert old_job.created_at > old_created_at
    assert PipelineLog.objects.filter(step_name="job_archive_restore").exists()

    repeat_result = JobArchiveService.restore_archive(archive_run)
    archive_run.refresh_from_db()

    assert repeat_result["jobs_restored"] == 1
    assert archive_run.jobs_restored == 1


@pytest.mark.django_db
def test_monitoring_page_shows_job_archive_controls(client):
    response = client.get(reverse("monitoring-dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    assert "Job Archive" in content
    assert "Archive jobs" in content
    assert "Created before" in content
    assert reverse("job-archive-create") in content
    assert content.index("Analysis Pipeline") < content.index("Job Archive")
    assert content.index("Job Archive") < content.index("Top Error Sources")


@pytest.mark.django_db
def test_job_archive_views_create_download_and_restore(client, company):
    old_job = JobPost.objects.create(company=company, title="Old Platform Engineer")
    old_created_at = timezone.now() - timedelta(days=200)
    JobPost.objects.filter(id=old_job.id).update(created_at=old_created_at)

    archive_response = client.post(
        reverse("job-archive-create"),
        {"age_months": "3"},
        HTTP_ACCEPT="application/json",
    )
    archive_payload = archive_response.json()
    old_job.refresh_from_db()

    assert archive_response.status_code == 201
    assert archive_payload["jobs_archived"] == 1
    assert old_job.status == JobPost.StatusChoices.ARCHIVED

    download_response = client.get(
        reverse("job-archive-download", args=[archive_payload["archive_run_id"]])
    )
    download_payload = json.loads(download_response.content.decode())

    assert download_response.status_code == 200
    assert download_response["Content-Type"] == "application/json"
    assert "job-archive-" in download_response["Content-Disposition"]
    assert download_payload["jobs"][0]["id"] == old_job.id

    restore_response = client.post(
        reverse("job-archive-restore", args=[archive_payload["archive_run_id"]]),
        HTTP_ACCEPT="application/json",
    )
    old_job.refresh_from_db()

    assert restore_response.status_code == 200
    assert restore_response.json()["jobs_restored"] == 1
    assert old_job.status == JobPost.StatusChoices.ACTIVE
    assert old_job.created_at > old_created_at
